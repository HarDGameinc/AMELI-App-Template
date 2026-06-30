from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.mail import EmailMessage
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from ameli_app.password_policy import generate_compliant_password
from ameli_web.audit.models import AuditEvent
from ameli_web.utils import format_timestamp_ui

from ..models import (
    EmailChangeRequest,
    MaintenanceMode,
    MFAEmailChallenge,
    MFARecoveryCode,
    OutboundEmail,
    ThrottleCounter,
    UserSession,
)

User = get_user_model()
ROLE_GROUPS = {
    "public": "public",
    "superadmin": "superadmin",
}


def _validate_password_value(password: str, *, user=None) -> None:
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise ValueError("; ".join(exc.messages)) from exc


def ensure_role_groups(*args, **kwargs) -> None:
    for name in ROLE_GROUPS.values():
        Group.objects.get_or_create(name=name)


def sync_user_groups(user) -> None:
    desired = ROLE_GROUPS.get(user.role)
    if not desired:
        return
    groups = Group.objects.filter(name__in=ROLE_GROUPS.values())
    user.groups.set(groups.filter(name=desired))


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


def _trusted_proxies() -> set[str]:
    """List of REMOTE_ADDR values whose ``X-Forwarded-For`` we trust.

    Without a whitelist a malicious client can put any value in
    ``X-Forwarded-For`` and bypass rate limiting, poison audit IPs, and
    confuse account lockout. We only look at the header when the immediate
    peer (``REMOTE_ADDR``) is on this list — typically the loopback
    address of the local Caddy/nginx reverse proxy.
    """
    from django.conf import settings as django_settings

    raw = getattr(django_settings, "TRUSTED_PROXIES", None)
    if raw is None:
        return {"127.0.0.1", "::1"}  # the local reverse proxy is the only safe default
    return {str(item).strip() for item in raw if str(item).strip()}


def client_ip(request) -> str:
    """Return the originating client IP, only honoring proxy headers from
    trusted intermediaries."""
    remote = str(request.META.get("REMOTE_ADDR") or "")
    if remote in _trusted_proxies():
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            # ``X-Forwarded-For`` is ``client, proxy1, proxy2``; the leftmost
            # is the original client (as injected by the trusted proxy).
            return forwarded.split(",", 1)[0].strip()
    return remote


def sync_request_session(request) -> UserSession | None:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return None
    if not request.session.session_key:
        request.session.save()
    session_key = str(request.session.session_key or "")
    if not session_key:
        return None
    session_record, created = UserSession.objects.get_or_create(
        session_key=session_key,
        defaults={
            "user": user,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:512],
            "ip_address": client_ip(request)[:128],
        },
    )
    if session_record.user_id != user.id:
        session_record.user = user
        session_record.revoked_at = None
    if session_record.revoked_at:
        Session.objects.filter(session_key=session_key).delete()
        auth_logout(request)
        return session_record
    session_record.user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]
    session_record.ip_address = client_ip(request)[:128]
    session_record.last_seen_at = timezone.now()
    if created:
        session_record.created_at = session_record.last_seen_at
    session_record.save(update_fields=["user", "user_agent", "ip_address", "last_seen_at", "revoked_at"])
    return session_record


def revoke_session_record(session_record: UserSession, *, actor=None, reason: str = "manual-revoke") -> None:
    if session_record.revoked_at is None:
        session_record.revoked_at = timezone.now()
        session_record.save(update_fields=["revoked_at"])
    Session.objects.filter(session_key=session_record.session_key).delete()
    record_audit(
        "revoke_session",
        actor=actor,
        target_username=session_record.user.username,
        payload={"session_key": session_record.session_key, "reason": reason},
    )


def revoke_other_sessions(user, *, current_session_key: str) -> int:
    queryset = UserSession.objects.filter(user=user, revoked_at__isnull=True).exclude(session_key=current_session_key)
    count = queryset.count()
    for item in queryset:
        revoke_session_record(item, actor=user, reason="revoke-others")
    return count


def serialize_user(user) -> dict[str, Any]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "display_identity_name": user.display_identity_name,
        "display_alias_value": user.display_alias_value,
        "display_avatar_value": user.display_avatar_value,
        "display_theme_label": user.display_theme_label,
        "initials": user.initials,
        "avatar_url": user.avatar_url,
        "theme_preference": user.theme_preference,
        "role": user.role,
        "enabled": user.is_active,
        "has_avatar": bool(user.avatar),
        "must_change_password": user.must_change_password,
        "mfa_enabled": bool(user.mfa_enabled),
        "mfa_required": bool(user.mfa_required),
        "mfa_totp_enabled": bool(user.mfa_totp_enabled),
        "mfa_email_enabled": bool(user.mfa_email_enabled),
        "email": user.email or "",
        "created_at": user.created_at.isoformat() if getattr(user, "created_at", None) else None,
        "updated_at": user.updated_at.isoformat() if getattr(user, "updated_at", None) else None,
        "display_created_at": format_timestamp_ui(getattr(user, "created_at", None)),
        "display_updated_at": format_timestamp_ui(getattr(user, "updated_at", None)),
        "display_last_login_at": format_timestamp_ui(user.last_login),
        "last_login_at": user.last_login.isoformat() if user.last_login else None,
        # Permanent-lockout state (N3). When ``locked_at`` is set,
        # ``check_login_throttle`` refuses every attempt regardless of
        # password; the admin panel surfaces an "Desbloquear" button so
        # the operator can clear the flag.
        "locked": getattr(user, "locked_at", None) is not None,
        "locked_at": user.locked_at.isoformat() if getattr(user, "locked_at", None) else None,
        "display_locked_at": format_timestamp_ui(getattr(user, "locked_at", None)),
        "locked_reason": getattr(user, "locked_reason", "") or "",
    }


def serialize_session(session: UserSession, *, current_session_key: str | None = None) -> dict[str, Any]:
    # ASVS V3.3.3 — surface the absolute ceiling timestamp so the user
    # can see when re-auth will be forced. Computed from ``created_at +
    # SESSION_ABSOLUTE_MAX_AGE_SECONDS``; ``None`` when the ceiling is
    # disabled (setting == 0).
    from datetime import timedelta

    from django.conf import settings as django_settings

    max_age = int(getattr(django_settings, "SESSION_ABSOLUTE_MAX_AGE_SECONDS", 0) or 0)
    if max_age > 0:
        absolute_expires_at = session.created_at + timedelta(seconds=max_age)
    else:
        absolute_expires_at = None
    return {
        "username": session.user.username,
        "session_key": session.session_key,
        "session_id": session.session_key,
        "is_current": bool(current_session_key and current_session_key == session.session_key),
        "created_at": format_timestamp_ui(session.created_at),
        "display_created_at": format_timestamp_ui(session.created_at),
        "last_seen_at": format_timestamp_ui(session.last_seen_at),
        "display_last_seen_at": format_timestamp_ui(session.last_seen_at),
        "revoked_at": format_timestamp_ui(session.revoked_at),
        "display_revoked_at": format_timestamp_ui(session.revoked_at),
        "absolute_expires_at": format_timestamp_ui(absolute_expires_at) if absolute_expires_at else "",
        "display_absolute_expires_at": format_timestamp_ui(absolute_expires_at) if absolute_expires_at else "",
        "user_agent": session.user_agent,
        "display_user_agent": session.user_agent,
        "ip_address": session.ip_address,
        "revoked": session.revoked_at is not None,
    }


def list_user_sessions(user, *, current_session_key: str | None = None) -> list[dict[str, Any]]:
    return [serialize_session(item, current_session_key=current_session_key) for item in user.web_sessions.all()]


def paginate_user_sessions(
    user,
    *,
    page: int = 1,
    per_page: int = 20,
    current_session_key: str | None = None,
):
    """Return a paginated, already-serialised slice of the user's sessions.

    Order follows ``UserSession.Meta.ordering`` (``-last_seen_at``), which
    naturally places the actively used session near the top.
    """
    from ameli_web.pagination import Page, paginate_queryset

    body = paginate_queryset(user.web_sessions.all(), page=page, per_page=per_page)
    items = [
        serialize_session(item, current_session_key=current_session_key) for item in body.items
    ]
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


def list_recent_sessions(*, limit: int = 20, current_session_key: str | None = None) -> list[dict[str, Any]]:
    queryset = UserSession.objects.select_related("user").order_by("-last_seen_at")[: max(1, limit)]
    return [serialize_session(item, current_session_key=current_session_key) for item in queryset]


def _admin_sessions_queryset_for_filters(*, search: str = "", status: str = "", ip: str = ""):
    """Build the UserSession queryset for the admin panel filters.

    ``search`` matches against ``user.username`` (icontains). ``status``
    accepts ``active`` (revoked_at is null) or ``revoked``. ``ip`` matches
    against ``ip_address`` (icontains, so ``192.168`` finds a whole subnet).
    """
    queryset = UserSession.objects.select_related("user").order_by("-last_seen_at")

    term = (search or "").strip()
    if term:
        queryset = queryset.filter(user__username__icontains=term)

    status_value = (status or "").strip().lower()
    if status_value == "active":
        queryset = queryset.filter(revoked_at__isnull=True)
    elif status_value == "revoked":
        queryset = queryset.filter(revoked_at__isnull=False)

    ip_term = (ip or "").strip()
    if ip_term:
        queryset = queryset.filter(ip_address__icontains=ip_term)

    return queryset


def paginate_admin_sessions(
    *,
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    status: str = "",
    ip: str = "",
    current_session_key: str | None = None,
):
    """Return a paginated, filtered slice of all UserSessions for admins."""
    from ameli_web.pagination import Page, paginate_queryset

    queryset = _admin_sessions_queryset_for_filters(search=search, status=status, ip=ip)

    body = paginate_queryset(queryset, page=page, per_page=per_page)
    items = [
        serialize_session(item, current_session_key=current_session_key) for item in body.items
    ]
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


def get_maintenance_state() -> dict[str, Any]:
    """Return the current MaintenanceMode singleton as a plain dict.

    Cheap enough to call on every request — the row is a single PK
    lookup and the table has at most one row.
    """
    row = MaintenanceMode.objects.filter(pk=MaintenanceMode.SINGLETON_PK).first()
    if row is None:
        return {
            "active": False,
            "read_only": True,
            "message": "",
            "activated_at": None,
            "activated_by": "",
        }
    return {
        "active": bool(row.active),
        "read_only": bool(row.read_only),
        "message": row.message or "",
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "activated_by": row.activated_by_username or "",
    }


def enable_maintenance(
    actor_username: str, *, message: str = "", read_only: bool = True,
) -> dict[str, Any]:
    """Flip the maintenance flag on; audit the change."""
    row, _ = MaintenanceMode.objects.get_or_create(pk=MaintenanceMode.SINGLETON_PK)
    if row.active:
        return {"ok": True, "status": "already-active", "state": get_maintenance_state()}
    row.active = True
    row.read_only = bool(read_only)
    row.message = message or ""
    row.activated_at = timezone.now()
    row.deactivated_at = None
    row.activated_by_username = actor_username or ""
    row.save()
    actor_obj = User.objects.filter(username__iexact=actor_username).first() if actor_username else None
    record_audit(
        "maintenance_enabled",
        actor=actor_obj,
        target_username="",
        payload={"read_only": row.read_only, "message_len": len(row.message)},
    )
    return {"ok": True, "status": "enabled", "state": get_maintenance_state()}


def disable_maintenance(actor_username: str) -> dict[str, Any]:
    """Flip the maintenance flag off; audit the change."""
    row = MaintenanceMode.objects.filter(pk=MaintenanceMode.SINGLETON_PK).first()
    if row is None or not row.active:
        return {"ok": True, "status": "already-inactive", "state": get_maintenance_state()}
    row.active = False
    row.deactivated_at = timezone.now()
    row.save()
    actor_obj = User.objects.filter(username__iexact=actor_username).first() if actor_username else None
    record_audit(
        "maintenance_disabled",
        actor=actor_obj,
        target_username="",
        payload={"was_message_len": len(row.message)},
    )
    return {"ok": True, "status": "disabled", "state": get_maintenance_state()}


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


def replace_avatar(user, uploaded_file) -> None:
    old_name = user.avatar.name if user.avatar else ""
    user.avatar.save(uploaded_file.name, uploaded_file, save=False)
    user.save(update_fields=["avatar", "updated_at"])
    if old_name and old_name != user.avatar.name and default_storage.exists(old_name):
        default_storage.delete(old_name)


def delete_avatar(user) -> None:
    old_name = user.avatar.name if user.avatar else ""
    if old_name:
        user.avatar.delete(save=False)
        user.avatar = None
        user.save(update_fields=["avatar", "updated_at"])
        if default_storage.exists(old_name):
            default_storage.delete(old_name)


def list_users() -> list[dict[str, Any]]:
    return [serialize_user(user) for user in User.objects.all().order_by("username")]


def _users_queryset_for_filters(*, search: str = "", role: str = "", status: str = ""):
    """Build the User queryset for the admin panel filters.

    Extracted so the pagination view and the CSV/JSON export endpoint can
    share the exact same filter semantics — see the equivalent
    ``_audit_queryset_for_filters`` for the audit log.
    """
    from django.db.models import Q

    queryset = User.objects.all().order_by("username")

    term = (search or "").strip()
    if term:
        queryset = queryset.filter(
            Q(username__icontains=term) | Q(display_name__icontains=term)
        )

    role_value = (role or "").strip().lower()
    if role_value in {User.ROLE_SUPERADMIN, User.ROLE_PUBLIC}:
        queryset = queryset.filter(role=role_value)

    status_value = (status or "").strip().lower()
    if status_value == "enabled":
        queryset = queryset.filter(is_active=True)
    elif status_value == "disabled":
        queryset = queryset.filter(is_active=False)

    return queryset


def paginate_users_for_admin(
    *,
    page: int = 1,
    per_page: int = 25,
    search: str = "",
    role: str = "",
    status: str = "",
):
    """Return a paginated, filtered slice of users for the admin panel.

    ``search`` matches against ``username`` and ``display_name`` (icontains).
    ``role`` accepts the literal role values (``superadmin``/``public``);
    other values are ignored. ``status`` accepts ``enabled``/``disabled``
    and maps onto ``is_active``.
    """
    from ameli_web.pagination import Page, paginate_queryset

    queryset = _users_queryset_for_filters(search=search, role=role, status=status)

    body = paginate_queryset(queryset, page=page, per_page=per_page)
    items = [serialize_user(user) for user in body.items]
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


def filtered_users_queryset(*, search: str = "", role: str = "", status: str = ""):
    """Public alias for the filtered queryset, used by the export endpoint."""
    return _users_queryset_for_filters(search=search, role=role, status=status)


def bootstrap_superadmin(username: str, password: str, *, must_change_password: bool = False) -> dict[str, Any]:
    existing = User.objects.filter(role=User.ROLE_SUPERADMIN).order_by("username").first()
    if existing:
        return {
            "ok": True,
            "status": "skipped",
            "reason": "superadmin-already-exists",
            "username": existing.username,
        }
    _validate_password_value(password)
    user = User.objects.create_user(
        username=username,
        password=password,
        role=User.ROLE_SUPERADMIN,
        is_active=True,
        must_change_password=must_change_password,
    )
    sync_user_groups(user)
    record_audit("bootstrap_superadmin", actor=user, target_username=user.username, payload={})
    return {"ok": True, "status": "created", "username": user.username, "role": user.role}


def create_user_account(
    actor_username: str,
    username: str,
    password: str,
    *,
    role: str = User.ROLE_PUBLIC,
    must_change_password: bool = False,
) -> dict[str, Any]:
    if User.objects.filter(username__iexact=username).exists():
        raise ValueError("username already exists")
    if role not in {User.ROLE_PUBLIC, User.ROLE_SUPERADMIN}:
        raise ValueError("role must be public or superadmin")
    _validate_password_value(password)
    user = User.objects.create_user(
        username=username,
        password=password,
        role=role,
        is_active=True,
        must_change_password=must_change_password,
    )
    sync_user_groups(user)
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit("create_user", actor=actor, target_username=user.username, payload={"role": user.role})
    return {"ok": True, "status": "created", "username": user.username, "role": user.role, "enabled": user.is_active}


def create_public_user(actor_username: str, username: str, password: str, *, must_change_password: bool = False) -> dict[str, Any]:
    return create_user_account(
        actor_username,
        username,
        password,
        role=User.ROLE_PUBLIC,
        must_change_password=must_change_password,
    )


def update_user_account(actor_username: str, username: str, *, password: str | None = None, enabled: bool | None = None, must_change_password: bool | None = None, role: str | None = None, mfa_required: bool | None = None) -> dict[str, Any]:
    is_self = (actor_username or "").lower() == (username or "").lower()
    if is_self and enabled is False:
        raise ValueError("cannot disable your own account")
    if is_self and role is not None:
        raise ValueError("cannot change your own role")
    if is_self and mfa_required is not None:
        raise ValueError("cannot toggle your own mfa requirement; manage 2fa from your profile")
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    if password:
        _validate_password_value(password, user=user)
        user.set_password(password)
    if enabled is not None:
        user.is_active = enabled
    if must_change_password is not None:
        user.must_change_password = must_change_password
    if role in {User.ROLE_PUBLIC, User.ROLE_SUPERADMIN}:
        user.role = role
    if mfa_required is not None:
        user.mfa_required = bool(mfa_required)
    user.save()
    sync_user_groups(user)
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit(
        "update_user",
        actor=actor,
        target_username=user.username,
        payload={
            "enabled": user.is_active,
            "role": user.role,
            "mfa_required": user.mfa_required,
        },
    )
    return {"ok": True, "status": "updated", "user": serialize_user(user)}


def delete_user_account(actor_username: str, username: str) -> dict[str, Any]:
    from ..permissions import is_protected_account

    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    if is_protected_account(user):
        raise ValueError("superadmin cannot be deleted")
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit("delete_user", actor=actor, target_username=user.username, payload={})
    user.delete()
    return {"ok": True, "status": "deleted", "username": username}


def reset_user_password(actor_username: str, username: str, *, password: str | None = None, must_change_password: bool = True) -> dict[str, Any]:
    if (actor_username or "").lower() == (username or "").lower():
        raise ValueError("use change password from your profile to reset your own account")
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    temporary_password = None
    if password:
        _validate_password_value(password, user=user)
        next_password = password
    else:
        next_password = generate_compliant_password()
        _validate_password_value(next_password, user=user)
        temporary_password = next_password
    user.set_password(next_password)
    user.must_change_password = must_change_password
    user.save()
    sync_user_groups(user)
    for session_record in UserSession.objects.filter(user=user, revoked_at__isnull=True):
        revoke_session_record(session_record, actor=user, reason="password-reset")
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit(
        "reset_user_password",
        actor=actor,
        target_username=user.username,
        payload={"must_change_password": must_change_password},
    )
    response = {"ok": True, "status": "updated", "username": user.username}
    if temporary_password:
        response["temporary_password"] = temporary_password
    return response


def change_password_for_user(username: str, current_password: str, new_password: str, *, current_session_key: str | None = None) -> dict[str, Any]:
    user = User.objects.filter(username__iexact=username).first()
    if user is None or not user.is_active:
        raise ValueError("user not found")
    if not user.check_password(current_password):
        raise ValueError("current password is invalid")
    _validate_password_value(new_password, user=user)
    user.set_password(new_password)
    user.must_change_password = False
    user.save()
    sync_user_groups(user)
    revoked = revoke_other_sessions(user, current_session_key=current_session_key or "")
    record_audit("password_change", actor=user, target_username=user.username, payload={"revoked_sessions": revoked})
    return {"ok": True, "status": "updated", "revoked_sessions": revoked, "user": serialize_user(user)}


def change_email_for_self(actor_username: str, new_email: str, *, current_password: str) -> dict[str, Any]:
    """Update the calling user's email.

    If the user had email-based MFA enabled, the new address would not be
    able to receive the next challenge (which is still hashed against the
    old user record but addressed to the new mailbox) so we proactively
    disable the email factor and delete pending challenges. The user keeps
    TOTP and recovery codes if they had any.

    Requires ``current_password`` re-confirmation: a cookie alone must
    NOT be able to swap the account's email out from under the
    legitimate user (which would also disable the email MFA factor as
    a side-effect). The runtime callers go through
    ``request_email_change`` (double-opt-in flow); this entry point is
    kept for tests / future admin / CLI surfaces and the password gate
    is the safety net.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    normalized = (new_email or "").strip().lower()
    if normalized == (user.email or "").strip().lower():
        return {"ok": True, "status": "unchanged", "email": user.email, "mfa_email_disabled": False}
    user.email = normalized
    mfa_email_disabled = False
    update_fields = ["email", "updated_at"]
    if user.mfa_email_enabled:
        user.mfa_email_enabled = False
        user.mfa_enabled = bool(user.mfa_totp_enabled)
        update_fields.extend(["mfa_email_enabled", "mfa_enabled"])
        mfa_email_disabled = True
    user.save(update_fields=update_fields)
    if mfa_email_disabled:
        MFAEmailChallenge.objects.filter(user=user).delete()
        if not user.mfa_enabled:
            MFARecoveryCode.objects.filter(user=user).delete()
    record_audit(
        "update_my_email",
        actor=user,
        target_username=user.username,
        payload={"mfa_email_disabled": mfa_email_disabled},
    )
    return {
        "ok": True,
        "status": "updated",
        "email": user.email,
        "mfa_email_disabled": mfa_email_disabled,
    }


_PROFILE_TEST_EMAIL_COOLDOWN_SECONDS = 30


def send_profile_test_email(user, *, last_sent_at: datetime | None = None) -> dict[str, Any]:
    """Send a plain-text confirmation email to the user's address.

    ``last_sent_at`` is supplied by the view (typically from the user's
    session) so we can enforce a small cooldown without persisting state.
    """
    if not user.email:
        raise ValueError("no email on file for this account")
    if last_sent_at is not None:
        elapsed = (timezone.now() - last_sent_at).total_seconds()
        if elapsed < _PROFILE_TEST_EMAIL_COOLDOWN_SECONDS:
            wait = int(_PROFILE_TEST_EMAIL_COOLDOWN_SECONDS - elapsed) or 1
            raise ValueError(f"esperá {wait} segundos antes de pedir otro envio")
    app_name = django_settings.CFG.app_name
    body = (
        f"Hola @{user.username},\n\n"
        f"Este es un correo de prueba enviado desde {app_name}.\n"
        f"Si lo recibiste, tu direccion {user.email} esta funcionando "
        f"y vas a poder usar 2FA por email cuando lo actives.\n\n"
        f"Si vos no pediste este correo, ignoralo.\n\n"
        f"Saludos,\n{app_name}\n"
    )
    subject = f"[{app_name}] Prueba de correo"
    message_class = EmailMessage
    try:
        body.encode("us-ascii")
        subject.encode("us-ascii")
        message_class = _PasswordResetEmail
    except UnicodeEncodeError:
        pass
    email = message_class(
        subject=subject,
        body=body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.send(fail_silently=False)
    record_audit(
        "profile_test_email_sent",
        actor=user,
        target_username=user.username,
        payload={"email": user.email},
    )
    return {"ok": True, "email": user.email, "sent_at": timezone.now().isoformat()}


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


# ---------------------------------------------------------------------------
# Password reset by email
# ---------------------------------------------------------------------------


def _find_user_for_reset(identifier: str):
    if not identifier:
        return None
    clean = identifier.strip()
    if not clean:
        return None
    user = User.objects.filter(username__iexact=clean).first()
    if user is not None:
        return user
    if "@" in clean:
        return User.objects.filter(email__iexact=clean, is_active=True).first()
    return None


def _build_reset_url(uidb64: str, token: str, base_url: str) -> str:
    path = f"/login/reset/{uidb64}/{token}/"
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    return path


def _send_password_reset_email(user, reset_url: str) -> dict[str, Any]:
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "display_name": user.display_identity_name,
        "reset_url": reset_url,
        "timeout_seconds": django_settings.PASSWORD_RESET_TIMEOUT,
        "timeout_minutes": django_settings.PASSWORD_RESET_TIMEOUT // 60,
    }
    body = render_to_string("accounts/password_reset_email.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Restablecer tu contrasena"
    # If the body is plain ASCII (the bundled template is), use the
    # 7bit variant so the URL stays on a single line. Fall back to a
    # regular EmailMessage when the body contains non-ASCII text;
    # real email clients decode the resulting quoted-printable.
    message_class = EmailMessage
    try:
        body.encode("us-ascii")
        subject.encode("us-ascii")
        message_class = _PasswordResetEmail
    except UnicodeEncodeError:
        pass
    email = message_class(
        subject=subject,
        body=body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    # The reset URL is only valid for PASSWORD_RESET_TIMEOUT seconds
    # — past that the queued copy is useless, so expire it in the
    # queue too. send_with_retry returns soft-success on transient
    # SMTP failure: the request handler still tells the user "we
    # sent it" (identical-response design) and the notify worker
    # delivers eventually.
    expires_at = timezone.now() + timedelta(seconds=django_settings.PASSWORD_RESET_TIMEOUT)
    return send_with_retry(
        email,
        audit_action="password_reset_email_delivered",
        target_username=user.username,
        expires_at=expires_at,
    )


def request_password_reset(identifier: str, *, base_url: str = "") -> dict[str, Any]:
    """Trigger a password reset email if the identifier matches a user.

    The response is intentionally identical for found and not-found cases so
    a caller cannot enumerate registered users. Audit events distinguish the
    two so an admin can still investigate failures.
    """
    user = _find_user_for_reset(identifier)
    if user is None or not user.is_active:
        record_audit(
            "password_reset_requested",
            actor=None,
            target_username=identifier or "",
            payload={"status": "user-not-found"},
        )
        return {"ok": True, "status": "requested"}
    if not user.email:
        record_audit(
            "password_reset_requested",
            actor=None,
            target_username=user.username,
            payload={"status": "no-email-on-file"},
        )
        return {"ok": True, "status": "requested"}
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = _build_reset_url(uidb64, token, base_url)
    _send_password_reset_email(user, reset_url)
    record_audit(
        "password_reset_requested",
        actor=None,
        target_username=user.username,
        payload={"status": "email-sent"},
    )
    return {"ok": True, "status": "requested"}


def _decode_uid(uidb64: str):
    try:
        uid_bytes = urlsafe_base64_decode(uidb64)
        return int(uid_bytes)
    except (TypeError, ValueError, OverflowError):
        return None


def get_user_for_reset_token(uidb64: str, token: str):
    """Return the user matching (uidb64, token) or None."""
    uid = _decode_uid(uidb64)
    if uid is None:
        return None
    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None:
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user


def complete_password_reset(uidb64: str, token: str, new_password: str) -> dict[str, Any]:
    """Validate the token and update the user's password.

    Once the password is changed, the token is implicitly invalidated
    because PasswordResetTokenGenerator signs over the password hash.
    """
    user = get_user_for_reset_token(uidb64, token)
    if user is None:
        record_audit(
            "password_reset_token_invalid",
            actor=None,
            target_username="",
            payload={"uidb64": uidb64},
        )
        raise ValueError("invalid or expired reset link")
    _validate_password_value(new_password, user=user)
    user.set_password(new_password)
    user.must_change_password = False
    user.save()
    sync_user_groups(user)
    revoke_other_sessions(user, current_session_key="")
    record_audit(
        "password_reset_completed",
        actor=user,
        target_username=user.username,
        payload={},
    )
    return {"ok": True, "status": "completed", "user": serialize_user(user)}


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



# ============================ PII lifecycle ============================
#
# Two paths to drop a user record + scrub the associated identifiers:
# the operator-side CLI prune (``purge_inactive_users``) for accounts
# that have been disabled long enough to count as stale, and the
# user-side self-service request (``delete_my_account``) that the
# /profile/delete-account endpoint exposes.
#
# Both produce a tombstone audit row so the chain still records "this
# user existed and was removed" — the row's payload only carries the
# username (which the operator already had access to), never the
# email, display_name or any other PII the user gave us.


def purge_inactive_users(*, days: int = 365, dry_run: bool = False) -> dict[str, Any]:
    """Delete users that have been ``is_active=False`` longer than ``days``.

    The sweep is operator-initiated (CLI) rather than worker-scheduled
    because deleting a user is a destructive PII action that benefits
    from explicit operator intent. Returns a structured summary that
    the CLI prints so the operator can confirm before re-running
    without ``--dry-run``.

    Superadmin accounts are never touched, even if disabled — losing
    them silently would brick the deploy. Operators who really want
    a superadmin gone must run ``ameli-app create-user`` against a
    fresh username first.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=max(1, days))
    qs = User.objects.filter(
        is_active=False,
        updated_at__lt=cutoff,
    ).exclude(role=User.ROLE_SUPERADMIN)
    candidates = list(qs.values_list("username", flat=True))
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "candidates": candidates,
            "count": len(candidates),
            "cutoff": cutoff.isoformat(),
        }
    deleted = 0
    for username in candidates:
        # Re-fetch in the loop so we can record the tombstone with
        # the actual username, then delete. ``cascade`` removes the
        # user's sessions + outbound emails + email-change records
        # via the FK defaults declared on those models.
        user = User.objects.filter(username=username).first()
        if user is None:
            continue
        username_snapshot = user.username
        user.delete()
        record_audit(
            "user_purged_for_inactivity",
            actor=None,
            target_username=username_snapshot,
            payload={"reason": f"inactive >{days}d"},
        )
        deleted += 1
    return {
        "ok": True,
        "dry_run": False,
        "deleted": deleted,
        "cutoff": cutoff.isoformat(),
    }


def delete_my_account(*, user, password: str) -> dict[str, Any]:
    """User-initiated account deletion. Requires the current password
    so a stolen cookie alone cannot wipe the account.

    Superadmins cannot self-delete — they must promote another
    superadmin first and then run the CLI prune. This avoids the
    lockout where the only operator deletes themselves.
    """
    from ..permissions import can_self_delete, is_authenticated

    if not is_authenticated(user):
        raise ValueError("autenticacion requerida")
    if not can_self_delete(user):
        raise ValueError(
            "los superadmin no pueden auto-eliminarse; promove a otro "
            "superadmin y usa el CLI"
        )
    if not user.check_password(password or ""):
        raise ValueError("contrasena incorrecta")
    username_snapshot = user.username
    # Audit BEFORE delete so the row references the user pk that
    # is about to disappear via the snapshot in target_username.
    record_audit(
        "user_self_deleted",
        actor=user,
        target_username=username_snapshot,
        payload={},
    )
    user.delete()
    return {"ok": True, "deleted_username": username_snapshot}
