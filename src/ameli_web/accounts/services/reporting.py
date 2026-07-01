"""Reporting — user + email-queue summaries and audit-event serialization/pagination.

Moved from services/__init__.py (PC-1 cleanup, 2026-07-01).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from ameli_web.audit.models import AuditEvent
from ameli_web.utils import format_timestamp_ui

from ..models import OutboundEmail

User = get_user_model()


def summarize_users() -> dict[str, int]:
    rows = User.objects.values("is_active").annotate(count=Count("id"))
    total = User.objects.count()
    enabled = sum(item["count"] for item in rows if item["is_active"])
    disabled = total - enabled
    pending_password_changes = User.objects.filter(must_change_password=True).count()
    return {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "pending_password_changes": pending_password_changes,
    }


def summarize_email_queue() -> dict[str, Any]:
    """Operator-facing snapshot of the outbound retry queue.

    Fields:
      pending          — current rows waiting for a worker tick
      sent_last_24h    — successfully delivered in the last 24 h
      failed_last_24h  — permanently failed in the last 24 h
      expired_last_24h — dropped before delivery in the last 24 h
      oldest_pending_age_seconds — how long the oldest pending row
                                   has been waiting (None when the
                                   queue is empty)
      next_retry_at_iso — ISO timestamp of the soonest pending row
                          (None when empty)
      top_error_classes — list of {error_class, count} for failed +
                          permanently-failed rows in the last 24 h
                          so the operator sees the dominant cause
    """
    now = timezone.now()
    cutoff = now - timedelta(hours=24)
    qs = OutboundEmail.objects

    counts_by_status = dict(
        qs.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    pending = counts_by_status.get(OutboundEmail.STATUS_PENDING, 0)
    sent_last_24h = qs.filter(
        status=OutboundEmail.STATUS_SENT, updated_at__gte=cutoff,
    ).count()
    failed_qs = qs.filter(
        status=OutboundEmail.STATUS_FAILED, updated_at__gte=cutoff,
    )
    failed_last_24h = failed_qs.exclude(last_error="expired before delivery").count()
    expired_last_24h = failed_qs.filter(last_error="expired before delivery").count()

    oldest = qs.filter(status=OutboundEmail.STATUS_PENDING).order_by("created_at").first()
    soonest = qs.filter(status=OutboundEmail.STATUS_PENDING).order_by("next_retry_at").first()

    # Group failed-row error_class (excluding the "expired" bucket
    # since that lives in its own metric). ``last_error`` is the
    # operational detail; the class prefix before the colon is what's
    # safe to surface to the widget.
    top_error_classes: list[dict[str, Any]] = []
    error_buckets: dict[str, int] = {}
    real_failures = failed_qs.exclude(last_error="expired before delivery")
    for row in real_failures.only("last_error").iterator(chunk_size=500):
        first = (row.last_error or "").split(":", 1)[0].strip() or "unknown"
        error_buckets[first] = error_buckets.get(first, 0) + 1
    for cls, count in sorted(
        error_buckets.items(), key=lambda kv: kv[1], reverse=True,
    )[:5]:
        top_error_classes.append({"error_class": cls, "count": count})

    return {
        "pending": pending,
        "sent_last_24h": sent_last_24h,
        "failed_last_24h": failed_last_24h,
        "expired_last_24h": expired_last_24h,
        "oldest_pending_age_seconds": (
            int((now - oldest.created_at).total_seconds()) if oldest else None
        ),
        "next_retry_at_iso": (
            soonest.next_retry_at.isoformat() if soonest else None
        ),
        "top_error_classes": top_error_classes,
        "generated_at_iso": now.isoformat(),
    }


def _display_tone_for_action(action: str) -> str:
    if action.endswith("_failed") or action in {"admin_access_denied"}:
        return "FALLA"
    if action.startswith("delete_") or action.startswith("revoke_"):
        return "DEGRADADO"
    return "OPERATIVO"


def serialize_audit_event(item: AuditEvent) -> dict[str, Any]:
    payload = item.payload or {}
    return {
        "id": item.id,
        "actor_username": item.actor_username,
        "target_username": item.target_username,
        "action": item.action,
        "payload": payload,
        "created_at": item.created_at.isoformat(),
        "display_time": format_timestamp_ui(item.created_at),
        "display_action": item.action.replace("_", " "),
        "display_actor": item.actor_username or "anon",
        "display_target": item.target_username or "-",
        "display_tone": _display_tone_for_action(item.action),
        "display_result_label": "ERROR" if item.action.endswith("_failed") else "OK",
        "display_result_class": "error" if item.action.endswith("_failed") else "ok",
        "display_auth_mode": payload.get("auth_mode"),
        "display_path": payload.get("path"),
        "display_reason": payload.get("reason"),
    }


def list_recent_audit_entries(*, limit: int = 30, actor_username: str | None = None, target_username: str | None = None) -> list[dict[str, Any]]:
    queryset = AuditEvent.objects.all().order_by("-created_at")
    if actor_username:
        queryset = queryset.filter(actor_username__iexact=actor_username)
    if target_username:
        queryset = queryset.filter(target_username__iexact=target_username)
    return [serialize_audit_event(item) for item in queryset[: max(1, limit)]]


def _audit_queryset_for_filters(
    *,
    actor: str = "",
    target: str = "",
    action: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
    payload: str = "",
):
    """Build the AuditEvent queryset for the admin panel filters.

    Extracted so the pagination view and the CSV/JSON export endpoint can
    share the exact same filter semantics. ``date_from``/``date_to`` accept
    ISO ``YYYY-MM-DD`` strings; invalid values are silently ignored so the
    operator does not get a 500 from a typo in a date input. ``payload``
    is a substring matched against the JSON-serialised payload text so it
    works the same on Postgres and SQLite.
    """
    from datetime import datetime, time

    from django.db.models import TextField
    from django.db.models.functions import Cast

    queryset = AuditEvent.objects.all().order_by("-created_at", "-id")

    actor_term = (actor or "").strip()
    if actor_term:
        queryset = queryset.filter(actor_username__icontains=actor_term)

    target_term = (target or "").strip()
    if target_term:
        queryset = queryset.filter(target_username__icontains=target_term)

    action_term = (action or "").strip()
    if action_term:
        queryset = queryset.filter(action__icontains=action_term)

    outcome_value = (outcome or "").strip().lower()
    if outcome_value == "ok":
        queryset = queryset.exclude(action__endswith="_failed")
    elif outcome_value == "error":
        queryset = queryset.filter(action__endswith="_failed")

    raw_from = (date_from or "").strip()
    if raw_from:
        try:
            dt_from = datetime.combine(datetime.strptime(raw_from, "%Y-%m-%d").date(), time.min)
        except ValueError:
            dt_from = None
        if dt_from is not None:
            queryset = queryset.filter(created_at__gte=timezone.make_aware(dt_from))

    raw_to = (date_to or "").strip()
    if raw_to:
        try:
            dt_to = datetime.combine(datetime.strptime(raw_to, "%Y-%m-%d").date(), time.max)
        except ValueError:
            dt_to = None
        if dt_to is not None:
            queryset = queryset.filter(created_at__lte=timezone.make_aware(dt_to))

    payload_term = (payload or "").strip()
    if payload_term:
        # Cast the JSONField to text so the search is portable across
        # Postgres and SQLite. Postgres benefits from a GIN index on the
        # JSON column for high-volume installs, but the icontains path is
        # the predictable baseline.
        queryset = queryset.annotate(_payload_text=Cast("payload", TextField())).filter(
            _payload_text__icontains=payload_term
        )

    return queryset


def paginate_audit_for_admin(
    *,
    page: int = 1,
    per_page: int = 30,
    actor: str = "",
    target: str = "",
    action: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
    payload: str = "",
):
    """Return a paginated, filtered slice of audit events for the admin panel.

    Filters are all icontains (``actor``, ``target``, ``action``) so the
    operator can search by substring. ``outcome`` accepts ``ok``/``error``
    and maps onto the ``_failed`` action suffix convention used by the rest
    of the audit pipeline. ``date_from``/``date_to`` accept ISO date
    strings (``YYYY-MM-DD``) and bound ``created_at``.
    """
    from ameli_web.pagination import Page, paginate_queryset

    queryset = _audit_queryset_for_filters(
        actor=actor,
        target=target,
        action=action,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        payload=payload,
    )

    body = paginate_queryset(queryset, page=page, per_page=per_page)
    items = [serialize_audit_event(item) for item in body.items]
    return Page(
        items=items,
        page=body.page,
        per_page=body.per_page,
        total=body.total,
        total_pages=body.total_pages,
        has_prev=body.has_prev,
        has_next=body.has_next,
        start_index=body.start_index,
        end_index=body.end_index,
    )


def filtered_audit_queryset(
    *,
    actor: str = "",
    target: str = "",
    action: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
    payload: str = "",
):
    """Public alias for the filtered queryset, used by the export endpoint."""
    return _audit_queryset_for_filters(
        actor=actor,
        target=target,
        action=action,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        payload=payload,
    )
