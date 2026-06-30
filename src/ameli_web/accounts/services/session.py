"""Session domain — UserSession sync, revoke, listing/pagination for
profile and admin views.

Moved from services/__init__.py (PC-1 step 7, 2026-06-30).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth import logout as auth_logout
from django.contrib.sessions.models import Session
from django.utils import timezone

from ameli_web.utils import format_timestamp_ui

from ..models import UserSession
from .audit import record_audit


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
