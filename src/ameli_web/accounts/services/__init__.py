from __future__ import annotations

import hmac
from datetime import timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone

from ameli_web.audit.models import AuditEvent
from ameli_web.utils import format_timestamp_ui

from ..models import (
    EmailChangeRequest,
    MFAEmailChallenge,
    OutboundEmail,
    ThrottleCounter,
    UserSession,
)

User = get_user_model()


# Audit chain — moved to services/audit.py (PC-1 step 2, 2026-06-27).
# Re-exported here so external callers (views, admin_views, tests)
# keep working without touching their imports.
from .audit import (  # noqa: E402, I001
    _audit_canonical as _audit_canonical,
    _audit_hmac,
    _audit_hmac_key,
    _normalise_audit_payload as _normalise_audit_payload,
    apply_audit_key_to_env_file as apply_audit_key_to_env_file,
    record_audit,
    rotate_audit_key as rotate_audit_key,
    verify_audit_chain as verify_audit_chain,
)


# Email queue (transport layer) — moved to services/email_queue.py (PC-1 step 5, 2026-06-30).
# Re-exported here so external callers (workers, tests) keep working without
# touching their imports.
from .email_queue import (  # noqa: E402, I001
    _PasswordResetEmail,
    process_email_queue as process_email_queue,
    send_with_retry as send_with_retry,
)

# MFA domain (TOTP + email-based MFA + recovery codes) — moved to
# services/mfa.py (PC-1 step 6, 2026-06-30). Re-exported here so external
# callers (views, admin_views, tests) keep working without touching their
# imports.
from .mfa import (  # noqa: E402, I001
    _check_email_mfa_rate_limit as _check_email_mfa_rate_limit,
    _create_and_send_email_challenge as _create_and_send_email_challenge,
    _send_mfa_disabled_by_admin_notification as _send_mfa_disabled_by_admin_notification,
    _send_mfa_email_code as _send_mfa_email_code,
    admin_disable_mfa_for_user as admin_disable_mfa_for_user,
    confirm_mfa_email_enrollment as confirm_mfa_email_enrollment,
    confirm_mfa_enrollment as confirm_mfa_enrollment,
    consume_email_mfa_code as consume_email_mfa_code,
    consume_recovery_code as consume_recovery_code,
    disable_mfa_email_for_self as disable_mfa_email_for_self,
    disable_mfa_for_self as disable_mfa_for_self,
    disable_mfa_totp_for_self as disable_mfa_totp_for_self,
    regenerate_recovery_codes as regenerate_recovery_codes,
    send_mfa_email_login_code as send_mfa_email_login_code,
    serialize_mfa_status as serialize_mfa_status,
    start_mfa_email_enrollment as start_mfa_email_enrollment,
    start_mfa_enrollment as start_mfa_enrollment,
)

# Session domain (UserSession sync/revoke/listing) — moved to
# services/session.py (PC-1 step 7, 2026-06-30). Re-exported here so
# external callers (middleware, views, admin_views, tests) keep working
# without touching their imports.
from .session import (  # noqa: E402, I001
    _admin_sessions_queryset_for_filters as _admin_sessions_queryset_for_filters,
    _trusted_proxies as _trusted_proxies,
    client_ip as client_ip,
    list_recent_sessions as list_recent_sessions,
    list_user_sessions as list_user_sessions,
    paginate_admin_sessions as paginate_admin_sessions,
    paginate_user_sessions as paginate_user_sessions,
    revoke_other_sessions as revoke_other_sessions,
    revoke_session_record as revoke_session_record,
    serialize_session as serialize_session,
    sync_request_session as sync_request_session,
)

# Maintenance mode — moved to services/maintenance.py (PC-1 step 7,
# 2026-06-30). Re-exported here so external callers (middleware, admin
# views, tests) keep working without touching their imports.
from .maintenance import (  # noqa: E402, I001
    disable_maintenance as disable_maintenance,
    enable_maintenance as enable_maintenance,
    get_maintenance_state as get_maintenance_state,
)

# Password reset by email — moved to services/password_reset.py (PC-1
# step 7, 2026-06-30). Re-exported here so external callers (views,
# tests) keep working without touching their imports.
from .password_reset import (  # noqa: E402, I001
    _build_reset_url as _build_reset_url,
    _decode_uid as _decode_uid,
    _find_user_for_reset as _find_user_for_reset,
    _send_password_reset_email as _send_password_reset_email,
    complete_password_reset as complete_password_reset,
    get_user_for_reset_token as get_user_for_reset_token,
    request_password_reset as request_password_reset,
)

# User domain (CRUD + serialize + avatars + password/email change for
# self + account deletion) — moved to services/user.py (PC-1 step 8,
# 2026-06-30). Re-exported here so external callers (views, admin_views,
# CLI, signals, tests) keep working without touching their imports.
from .user import (  # noqa: E402, I001
    ROLE_GROUPS as ROLE_GROUPS,
    _validate_password_value as _validate_password_value,
    bootstrap_superadmin as bootstrap_superadmin,
    change_email_for_self as change_email_for_self,
    change_password_for_user as change_password_for_user,
    create_public_user as create_public_user,
    create_user_account as create_user_account,
    delete_avatar as delete_avatar,
    delete_my_account as delete_my_account,
    delete_user_account as delete_user_account,
    ensure_role_groups as ensure_role_groups,
    filtered_users_queryset as filtered_users_queryset,
    list_users as list_users,
    paginate_users_for_admin as paginate_users_for_admin,
    purge_inactive_users as purge_inactive_users,
    replace_avatar as replace_avatar,
    reset_user_password as reset_user_password,
    send_profile_test_email as send_profile_test_email,
    serialize_user as serialize_user,
    sync_user_groups as sync_user_groups,
    update_user_account as update_user_account,
)


def run_retention_sweep(
    *,
    sessions_revoked_max_age_days: int = 30,
    outbound_email_sent_max_age_days: int = 30,
    throttle_counter_max_age_days: int = 1,
    email_change_resolved_max_age_days: int = 30,
    mfa_email_challenge_consumed_max_age_days: int = 7,
    audit_max_age_days: int | None = None,
) -> dict[str, Any]:
    """Purge old operational rows so the DB doesn't grow without bound.

    The sweep is conservative and idempotent: only resolved /
    expired / revoked rows are touched, never anything still in
    flight. Defaults align with what an operator would expect from
    a baseline retention policy on a fresh deploy; callers can
    override per-knob for tighter or looser windows.

    Returns a dict of ``{table: rows_deleted}`` plus an ``audit_*``
    summary so the operator can confirm the run in journalctl /
    /admin/.

    ``audit_max_age_days=None`` skips the audit prune — the audit
    chain is the long-term log of "who did what" and most policies
    keep it. Pass an integer to enforce a horizon (rows older are
    deleted and a fresh chain anchor is written so verify-audit
    stays clean — anchor logic lives in
    :func:`_anchor_audit_chain_after_prune`).
    """
    from datetime import timedelta

    now = timezone.now()
    counts: dict[str, int] = {}

    # 1) Revoked / stale UserSession rows.
    cutoff = now - timedelta(days=sessions_revoked_max_age_days)
    n, _ = UserSession.objects.filter(
        revoked_at__isnull=False, revoked_at__lt=cutoff,
    ).delete()
    counts["user_sessions"] = n

    # 2) Sent / failed OutboundEmail rows.
    cutoff = now - timedelta(days=outbound_email_sent_max_age_days)
    n, _ = OutboundEmail.objects.filter(
        status__in=[OutboundEmail.STATUS_SENT, OutboundEmail.STATUS_FAILED],
        updated_at__lt=cutoff,
    ).delete()
    counts["outbound_emails"] = n

    # 3) ThrottleCounter rows whose window is well in the past.
    cutoff = now - timedelta(days=throttle_counter_max_age_days)
    n, _ = ThrottleCounter.objects.filter(window_start__lt=cutoff).delete()
    counts["throttle_counters"] = n

    # 4) Resolved (confirmed / cancelled) EmailChangeRequest rows.
    cutoff = now - timedelta(days=email_change_resolved_max_age_days)
    n, _ = EmailChangeRequest.objects.filter(
        created_at__lt=cutoff,
    ).exclude(confirmed_at__isnull=True, cancelled_at__isnull=True).delete()
    counts["email_change_requests"] = n

    # 5) Used / expired MFA email challenges.
    cutoff = now - timedelta(days=mfa_email_challenge_consumed_max_age_days)
    n, _ = MFAEmailChallenge.objects.filter(
        created_at__lt=cutoff,
    ).filter(used_at__isnull=False).delete()
    counts["mfa_email_challenges"] = n

    counts["audit_events"] = 0
    if audit_max_age_days is not None:
        counts["audit_events"] = _prune_audit_with_anchor(
            cutoff=now - timedelta(days=audit_max_age_days),
        )

    record_audit(
        "retention_sweep",
        target_username="",
        payload={"counts": dict(counts)},
    )
    return {"ok": True, "counts": counts, "swept_at": now.isoformat()}


def _prune_audit_with_anchor(*, cutoff) -> int:
    """Delete audit rows older than ``cutoff`` and re-anchor the chain.

    The chain links each row to the previous one via ``prev_hmac``;
    naively deleting the head would orphan the tail. We:

    1. Delete the rows older than ``cutoff`` in one transaction.
    2. Re-chain every surviving row that already carried an hmac
       under the LIVE key: the first survivor restarts with
       ``prev_hmac=""``, subsequent rows chain forward through the
       new hmacs. This keeps post-prune rows cryptographically
       anchored — a DB-write attacker that edits a surviving row
       cannot rehash it without the key — while accepting that we
       lose the cryptographic link back to the now-deleted head.
       Rows that pre-dated the chain (``hmac=""``) stay legacy and
       reset the prev pointer the same way :func:`verify_audit_chain`
       does.
    3. Write a ``retention_audit_anchor`` row that becomes the new
       head of the chain, chained from the last re-chained survivor.

    Old behaviour demoted survivors to ``hmac=""`` which made the
    post-prune tail invisible to ``verify_audit_chain`` and let any
    attacker with DB write access tamper undetected; the re-chain
    above preserves that guarantee going forward. Operators that
    need to keep the original hmacs (e.g. proof of integrity over
    the pruned window) should archive the audit table externally
    before running this prune — the prune still re-stamps surviving
    rows, so the canonical bytes change.
    """
    from django.db import transaction

    deleted = 0
    with transaction.atomic():
        deleted, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        if not deleted:
            return 0

        key = _audit_hmac_key()
        new_prev = ""
        if key:
            # 2) Walk survivors in id order, re-chain each chained row.
            survivors = (
                AuditEvent.objects.filter(created_at__gte=cutoff)
                .order_by("id")
            )
            for row in survivors.iterator(chunk_size=500):
                if not row.hmac:
                    # Pre-chain legacy row; mirror verify_audit_chain
                    # by leaving it alone and restarting prev.
                    new_prev = ""
                    continue
                new_hmac = _audit_hmac(
                    key=key,
                    prev_hmac=new_prev,
                    action=row.action,
                    actor_username=row.actor_username,
                    target_username=row.target_username,
                    payload=row.payload,
                    created_at=row.created_at,
                )
                AuditEvent.objects.filter(pk=row.pk).update(
                    prev_hmac=new_prev, hmac=new_hmac,
                )
                new_prev = new_hmac
        else:
            # No key configured: the chain is already empty, so
            # surviving rows have nothing to re-stamp. Reset prev
            # so the anchor still writes with prev_hmac="".
            AuditEvent.objects.filter(created_at__gte=cutoff).update(prev_hmac="")

        # 3) Fresh anchor chained from the last re-chained survivor.
        event = AuditEvent.objects.create(
            actor_username="",
            target_username="",
            action="retention_audit_anchor",
            payload={"deleted_rows": deleted, "cutoff": cutoff.isoformat()},
            prev_hmac=new_prev,
        )
        if key:
            event.refresh_from_db(fields=["created_at"])
            event.hmac = _audit_hmac(
                key=key,
                prev_hmac=new_prev,
                action=event.action,
                actor_username=event.actor_username,
                target_username=event.target_username,
                payload=event.payload,
                created_at=event.created_at,
            )
            event.save(update_fields=["hmac"])
    return deleted


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


# ASVS V2.2.3 — notify user of failed auth attempt burst.
#
# Triggered from ``record_login_failure`` when the per-username counter
# crosses ``LOGIN_LOCKOUT_USER_MAX`` (i.e. the moment the account hit
# the lockout threshold for the current window). The notification
# itself is throttled by a cooldown on ``User.last_auth_alert_sent_at``
# so an attacker that sustains the burst does not turn the user's inbox
# into a spam channel — they get one alert per cooldown period
# (default 24 h, configurable via ``settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS``).

AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT = 24


def _auth_failures_alert_cooldown() -> timedelta:
    """Resolve the alert cooldown from settings, falling back to 24 h.

    Operators can shorten it for sensitive environments (a financial
    deploy might want 1 h) or lengthen it for low-noise setups. The
    floor of 1 hour guards against a misconfiguration that would let
    the alert ride every fail.
    """
    hours = getattr(django_settings, "AUTH_FAILURES_ALERT_COOLDOWN_HOURS",
                    AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT)
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT
    if hours < 1:
        hours = AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT
    return timedelta(hours=hours)


def _send_auth_failures_alert(user, *, failure_count: int, ip: str = "") -> bool:
    """Notify the affected user that their account just crossed the
    lockout threshold (ASVS V2.2.3).

    Returns True when an email was actually attempted, False when
    skipped (no email on record, inside cooldown window, etc.).
    Delivery exceptions are swallowed via ``send_with_retry`` — the
    lockout itself is the security control, the email is a courtesy
    that must not block the auth path if SMTP is broken.

    The cooldown is enforced by reading ``user.last_auth_alert_sent_at``
    and rejecting the call when the gap is smaller than the configured
    window. The timestamp is updated immediately (before the send)
    so a concurrent fail that triggers a second crossing in the same
    window cannot fire a duplicate. The send may then queue (transient
    SMTP failure) without affecting the cooldown — the eventual
    delivery audit still references the original timestamp.
    """
    if not (user.email or "").strip():
        return False
    cooldown = _auth_failures_alert_cooldown()
    now = timezone.now()
    last = getattr(user, "last_auth_alert_sent_at", None)
    if last is not None and (now - last) < cooldown:
        # Inside the cooldown window. The audit chain records the
        # suppression so an operator can reason about why a flood of
        # lockouts produced only one email.
        record_audit(
            "auth_failures_alert_suppressed",
            target_username=user.username,
            payload={
                "reason": "cooldown",
                "ip": ip or "",
                "failure_count": int(failure_count),
                "cooldown_hours": int(cooldown.total_seconds() / 3600),
            },
        )
        return False
    # Stamp the cooldown anchor BEFORE attempting send. A concurrent
    # second crossing then sees the fresh timestamp and short-circuits
    # via the cooldown branch above.
    user.last_auth_alert_sent_at = now
    user.save(update_fields=["last_auth_alert_sent_at", "updated_at"])
    cooldown_hours = int(cooldown.total_seconds() / 3600)
    # ``_build_public_base_url`` requires a request to derive the
    # absolute URL; this hook fires from ``record_login_failure`` which
    # has no request handle. We read the configured base from
    # ``CFG.public_url_base`` directly and fall back to relative paths
    # in dev (the dev user has the dashboard open at localhost anyway).
    configured_base = (
        getattr(getattr(django_settings, "CFG", None), "public_url_base", "") or ""
    ).rstrip("/")
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "failure_count": int(failure_count),
        "window_minutes": int(_throttle_settings()["user_window"] / 60),
        "cooldown_hours": cooldown_hours,
        "change_password_url": f"{configured_base}/profile/password/" if configured_base else "/profile/password/",
        "reset_password_url": f"{configured_base}/forgot-password/" if configured_base else "/forgot-password/",
    }
    body = render_to_string("accounts/auth_failures_alert.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Actividad sospechosa en tu cuenta"
    message_class = EmailMessage
    try:
        body.encode("us-ascii")
        subject.encode("us-ascii")
        message_class = _PasswordResetEmail
    except UnicodeEncodeError:
        pass
    email = message_class(subject=subject, body=body, to=[user.email])
    result = send_with_retry(
        email,
        audit_action="auth_failures_alert_sent",
        target_username=user.username,
        audit_payload={
            "email": user.email,
            "ip": ip or "",
            "failure_count": int(failure_count),
        },
        # A "your account just got locked" email that arrives 2 h late
        # is no longer actionable — the lockout window has elapsed and
        # the user is likely back in. Keep the queue retry window short.
        expires_at=now + timedelta(hours=2),
    )
    if result["status"] == "queued":
        record_audit(
            "auth_failures_alert_queued",
            target_username=user.username,
            payload={"queue_id": result.get("queue_id"), "ip": ip or "", "failure_count": int(failure_count)},
        )
        return True
    record_audit(
        "auth_failures_alert_sent",
        target_username=user.username,
        payload={"email": user.email, "ip": ip or "", "failure_count": int(failure_count)},
    )
    return True


def _maybe_alert_for_auth_failures_burst(*, username: str, new_count: int, ip: str) -> None:
    """Glue from ``record_login_failure`` to ``_send_auth_failures_alert``.

    Fires exactly at the moment the per-username counter crosses the
    lockout threshold for the current window. Subsequent fails within
    the same window do not trigger again because the count is already
    past ``LOGIN_LOCKOUT_USER_MAX``. The cooldown on the User row
    additionally guards against the next window producing a duplicate.

    Username is normalised to lowercase before lookup; the throttle
    counter is keyed the same way so the trigger fires exactly once
    per crossing per case-insensitive username.
    """
    if not username:
        return
    cfg = _throttle_settings()
    if new_count != cfg["user_max"]:
        return
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        # Login attempt against a non-existent username (typo or
        # enumeration probe). Nothing to alert — silently drop.
        return
    try:
        _send_auth_failures_alert(user, failure_count=new_count, ip=ip)
    except Exception as exc:  # noqa: BLE001
        # Swallow — the auth path itself is the security control; an
        # alert send error must not break the login response. Capture
        # the failure in the audit chain so operators see it.
        record_audit(
            "auth_failures_alert_error",
            target_username=user.username,
            payload={"ip": ip or "", "error_class": type(exc).__name__},
        )


# ============================ Login throttle ============================
#
# All three rate-limit helpers below (login, forgot-password, mfa-resend)
# back onto an atomic counter table — see :class:`ThrottleCounter`. The
# previous implementation counted rows in :class:`AuditEvent` with a
# plain ``COUNT(*)`` and decided based on the result; two workers racing
# past the read could both observe "below threshold" and slip an extra
# attempt past the limit (a TOCTOU window). Routing every check through
# the same ``select_for_update`` + ``F("count") + 1`` pattern means the
# increment and the threshold comparison run inside a single transaction
# that the database serialises for us.
#
# Audit rows still fire on every relevant action so the historical view
# in the admin keeps working; they are no longer the source of truth for
# whether a request gets blocked.


# Throttle counters + login lockout + auxiliary rate limits
# moved to services/throttle.py (PC-1 step 3, 2026-06-27).
# Re-exported here so external callers keep working without
# touching their imports.
from .throttle import (  # noqa: E402, I001
    AccountLocked as AccountLocked,
    FORGOT_PASSWORD_IP_MAX_DEFAULT as FORGOT_PASSWORD_IP_MAX_DEFAULT,
    FORGOT_PASSWORD_IP_WINDOW_DEFAULT as FORGOT_PASSWORD_IP_WINDOW_DEFAULT,
    LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT as LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT,
    LOGIN_LOCKOUT_USER_MAX_DEFAULT as LOGIN_LOCKOUT_USER_MAX_DEFAULT,
    LOGIN_LOCKOUT_USER_WINDOW_DEFAULT as LOGIN_LOCKOUT_USER_WINDOW_DEFAULT,
    LOGIN_THROTTLE_IP_MAX_DEFAULT as LOGIN_THROTTLE_IP_MAX_DEFAULT,
    LOGIN_THROTTLE_IP_WINDOW_DEFAULT as LOGIN_THROTTLE_IP_WINDOW_DEFAULT,
    LoginThrottled as LoginThrottled,
    MFA_RESEND_IP_MAX_DEFAULT as MFA_RESEND_IP_MAX_DEFAULT,
    MFA_RESEND_IP_WINDOW_DEFAULT as MFA_RESEND_IP_WINDOW_DEFAULT,
    _bump_throttle_counter as _bump_throttle_counter,
    _consecutive_lockouts_for as _consecutive_lockouts_for,
    _count_recent_audit_by_action as _count_recent_audit_by_action,
    _count_recent_login_failures as _count_recent_login_failures,
    _read_throttle_counter as _read_throttle_counter,
    _read_throttle_counter_sliding as _read_throttle_counter_sliding,
    _throttle_settings,
    _window_start_for as _window_start_for,
    admin_unlock_user as admin_unlock_user,
    check_forgot_password_throttle as check_forgot_password_throttle,
    check_login_throttle as check_login_throttle,
    check_mfa_resend_throttle as check_mfa_resend_throttle,
    maybe_permanently_lock as maybe_permanently_lock,
    record_login_failure as record_login_failure,
)


# ============================ Email change (double-opt-in) ============================
#
# Without double-opt-in, anyone who steals a session can change the email
# to one they own and then trigger a password reset to take over the
# account. We make the change conditional on three things:
#
#  1. The actor knows the current password (proves they are not just a
#     cookie thief),
#  2. The new address actually receives mail (proves the operator did
#     not typo it and locks an attacker out of redirecting to a random
#     mailbox they do not control),
#  3. The legitimate user always sees an alert at the OLD address with a
#     cancel link, so a hijacked session cannot quietly redirect mail.

EMAIL_CHANGE_TTL_HOURS_DEFAULT = 12
EMAIL_CHANGE_TOKEN_BYTES = 32


def _hash_email_change_token(plaintext: str) -> str:
    import hashlib

    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _build_email_change_urls(
    request, *, request_id: int, token_plaintext: str
) -> tuple[str, str]:
    """Return (confirm_url, cancel_url) for an email change request."""
    base = _build_public_base_url(request)
    return (
        f"{base}/profile/email-change/confirm/{request_id}/{token_plaintext}/",
        f"{base}/profile/email-change/cancel/{request_id}/{token_plaintext}/",
    )


def _build_public_base_url(request) -> str:
    """Same guard as the password-reset helper: never trust the request
    ``Host`` header outside dev, because an attacker can spoof it and
    redirect the confirm link to a server they control."""
    from django.conf import settings as django_settings

    configured = getattr(getattr(django_settings, "CFG", None), "public_url_base", "")
    if configured:
        return configured.rstrip("/")
    if not django_settings.DEBUG and getattr(django_settings, "ENV_NAME", "dev") != "dev":
        raise RuntimeError(
            "public_url_base is not configured. Set ``dashboard.public_url_base`` "
            "in app.yaml (or AMELI_APP_PUBLIC_URL_BASE) so confirmation links "
            "in change-email mails do not depend on the request Host header."
        )
    absolute = request.build_absolute_uri("/")
    return absolute.rstrip("/")


def _send_email_change_confirmation(*, user, new_email, confirm_url, ttl_hours) -> None:
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "new_email": new_email,
        "confirm_url": confirm_url,
        "ttl_hours": ttl_hours,
    }
    body = render_to_string("accounts/email_change_confirm.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Confirma el cambio de email"
    message_class = EmailMessage
    try:
        body.encode("us-ascii")
        subject.encode("us-ascii")
        message_class = _PasswordResetEmail
    except UnicodeEncodeError:
        pass
    message_class(subject=subject, body=body, to=[new_email]).send(fail_silently=False)


def _send_email_change_alert(*, user, new_email, cancel_url, ttl_hours) -> None:
    if not (user.email or "").strip():
        return
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "new_email": new_email,
        "cancel_url": cancel_url,
        "ttl_hours": ttl_hours,
    }
    body = render_to_string("accounts/email_change_alert.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Pediste cambiar tu email"
    message_class = EmailMessage
    try:
        body.encode("us-ascii")
        subject.encode("us-ascii")
        message_class = _PasswordResetEmail
    except UnicodeEncodeError:
        pass
    message_class(subject=subject, body=body, to=[user.email]).send(fail_silently=False)


def request_email_change(
    user, *, new_email: str, current_password: str, request, ip: str = ""
) -> dict[str, Any]:
    """Initiate a double-opt-in change. Returns the persisted request as
    a serialisable dict; the plaintext token is mailed to the user only.

    Raises :class:`ValueError` for any validation problem so the caller
    can surface a single feedback message to the form.
    """
    import secrets

    from django.conf import settings as django_settings
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import validate_email

    if not user or not user.is_authenticated:
        raise ValueError("autenticacion requerida")
    cleaned = (new_email or "").strip().lower()
    if not cleaned:
        raise ValueError("ingresa la nueva direccion de email")
    try:
        validate_email(cleaned)
    except DjangoValidationError as exc:
        raise ValueError("la direccion de email no es valida") from exc
    if cleaned == (user.email or "").strip().lower():
        raise ValueError("la nueva direccion es igual a la actual")
    if not user.check_password(current_password or ""):
        raise ValueError("contrasena actual incorrecta")
    # Invalidate any previous pending request — keeping multiple alive
    # complicates UX (which link cancels which?) for no benefit.
    EmailChangeRequest.objects.filter(
        user=user, confirmed_at__isnull=True, cancelled_at__isnull=True
    ).update(cancelled_at=timezone.now(), cancel_reason="superseded")

    ttl_hours = int(
        getattr(django_settings, "EMAIL_CHANGE_TTL_HOURS", EMAIL_CHANGE_TTL_HOURS_DEFAULT)
    )
    ttl_hours = max(1, ttl_hours)
    token_plaintext = secrets.token_urlsafe(EMAIL_CHANGE_TOKEN_BYTES)
    record = EmailChangeRequest.objects.create(
        user=user,
        new_email=cleaned,
        token_hash=_hash_email_change_token(token_plaintext),
        expires_at=timezone.now() + timedelta(hours=ttl_hours),
        ip_address=(ip or "")[:128],
    )
    confirm_url, cancel_url = _build_email_change_urls(
        request, request_id=record.id, token_plaintext=token_plaintext
    )
    # Send confirm first; if the alert mailer fails we still proceed but
    # audit the failure.
    _send_email_change_confirmation(
        user=user, new_email=cleaned, confirm_url=confirm_url, ttl_hours=ttl_hours
    )
    try:
        _send_email_change_alert(
            user=user, new_email=cleaned, cancel_url=cancel_url, ttl_hours=ttl_hours
        )
    except Exception as exc:  # noqa: BLE001 - alert is best effort
        record_audit(
            "email_change_alert_failed",
            actor=user,
            target_username=user.username,
            payload={"reason": f"{exc.__class__.__name__}: {exc}"},
        )
    record_audit(
        "email_change_requested",
        actor=user,
        target_username=user.username,
        payload={
            "request_id": record.id,
            "new_email": cleaned,
            "old_email": user.email or "",
            "ip": ip,
        },
    )
    return {
        "ok": True,
        "status": "pending",
        "request_id": record.id,
        "new_email": cleaned,
        "expires_at": record.expires_at.isoformat(),
    }


def _find_email_change_request(*, request_id: int, token_plaintext: str):
    record = EmailChangeRequest.objects.select_related("user").filter(id=request_id).first()
    if record is None:
        return None
    # ASVS V2.10 / constant-time hash compare. ``!=`` on Python str is
    # short-circuit and leaks early-mismatch timing; ``hmac.compare_digest``
    # is the constant-time primitive used elsewhere in this module
    # (recovery / email codes) and is the right call here too.
    expected = _hash_email_change_token(token_plaintext or "")
    if not hmac.compare_digest(record.token_hash, expected):
        return None
    return record


def confirm_email_change(*, request_id: int, token_plaintext: str) -> dict[str, Any]:
    record = _find_email_change_request(request_id=request_id, token_plaintext=token_plaintext)
    if record is None:
        raise ValueError("enlace de confirmacion invalido")
    if record.cancelled_at is not None:
        raise ValueError("este pedido de cambio fue cancelado")
    if record.confirmed_at is not None:
        raise ValueError("este pedido ya fue confirmado")
    if record.is_expired():
        raise ValueError("el enlace caduco; volve a iniciar el cambio")
    user = record.user
    old_email = user.email or ""
    user.email = record.new_email
    update_fields = ["email", "updated_at"]
    # Email MFA is bound to the address. The legitimate user might still
    # have an active enrolment pointing at the OLD address — disable it
    # so the new owner of the inbox does not get a free 2FA on their side.
    if user.mfa_email_enabled:
        user.mfa_email_enabled = False
        update_fields.append("mfa_email_enabled")
        MFAEmailChallenge.objects.filter(user=user).delete()
        if not user.mfa_totp_enabled:
            user.mfa_enabled = False
            update_fields.append("mfa_enabled")
    user.save(update_fields=update_fields)
    record.confirmed_at = timezone.now()
    record.save(update_fields=["confirmed_at"])
    record_audit(
        "email_change_confirmed",
        actor=user,
        target_username=user.username,
        payload={
            "request_id": record.id,
            "old_email": old_email,
            "new_email": user.email,
        },
    )
    return {
        "ok": True,
        "status": "confirmed",
        "new_email": user.email,
        "old_email": old_email,
    }


def cancel_email_change(*, request_id: int, token_plaintext: str, reason: str = "user_cancel") -> dict[str, Any]:
    record = _find_email_change_request(request_id=request_id, token_plaintext=token_plaintext)
    if record is None:
        raise ValueError("enlace de cancelacion invalido")
    if record.confirmed_at is not None:
        raise ValueError("este pedido ya fue confirmado; no puede cancelarse")
    if record.cancelled_at is not None:
        return {"ok": True, "status": "already-cancelled", "new_email": record.new_email}
    record.cancelled_at = timezone.now()
    record.cancel_reason = (reason or "")[:64]
    record.save(update_fields=["cancelled_at", "cancel_reason"])
    record_audit(
        "email_change_cancelled",
        actor=record.user,
        target_username=record.user.username,
        payload={
            "request_id": record.id,
            "new_email": record.new_email,
            "reason": reason,
        },
    )
    return {"ok": True, "status": "cancelled", "new_email": record.new_email}


def pending_email_change_for(user) -> dict[str, Any] | None:
    if not user or not user.is_authenticated:
        return None
    record = (
        EmailChangeRequest.objects.filter(
            user=user, confirmed_at__isnull=True, cancelled_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if record is None:
        return None
    return {
        "request_id": record.id,
        "new_email": record.new_email,
        "created_at": record.created_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "expired": record.is_expired(),
    }


# Sudo grants for sensitive admin actions
# moved to services/sudo.py (PC-1 step 4, 2026-06-27).
# Re-exported here so external callers keep working without
# touching their imports.
from .sudo import (  # noqa: E402, I001
    SUDO_GRACE_SECONDS_DEFAULT as SUDO_GRACE_SECONDS_DEFAULT,
    SudoRequired as SudoRequired,
    _check_sudo_throttle as _check_sudo_throttle,
    _record_sudo_failure as _record_sudo_failure,
    _sudo_throttle_key as _sudo_throttle_key,
    grant_sudo as grant_sudo,
    revoke_sudo as revoke_sudo,
    send_sudo_email_code as send_sudo_email_code,
    session_in_sudo as session_in_sudo,
    verify_sudo_credentials as verify_sudo_credentials,
)


