from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.sessions.models import Session
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import User, UserSession
from .services import client_ip, ensure_role_groups, record_audit, sync_user_groups


@receiver(post_save, sender=User)
def _sync_user_groups(sender, instance: User, **kwargs):
    ensure_role_groups()
    sync_user_groups(instance)


@receiver(user_logged_in)
def _record_login(sender, request, user: User, **kwargs):
    if not request.session.session_key:
        request.session.save()
    session_key = str(request.session.session_key or "")
    if session_key:
        session, _ = UserSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "user": user,
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:512],
                "ip_address": client_ip(request)[:128],
            },
        )
        session.user = user
        session.revoked_at = None
        session.user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]
        session.ip_address = client_ip(request)[:128]
        session.last_seen_at = timezone.now()
        session.save()
    record_audit("login", actor=user, target_username=user.username, payload={"auth_mode": "session"})
    # Reserve-then-verify login gate: a successful auth clears the per-user
    # attempt counter so earlier fumbles don't count against the rest of
    # the window. Single success hook for both the login form and MFA.
    from .services import reset_login_throttle

    reset_login_throttle(user.username)


@receiver(user_logged_out)
def _record_logout(sender, request, user, **kwargs):
    if user is None:
        return
    session_key = str(getattr(request.session, "session_key", "") or "")
    if session_key:
        session = UserSession.objects.filter(session_key=session_key).first()
        if session and session.revoked_at is None:
            session.revoked_at = timezone.now()
            session.save(update_fields=["revoked_at"])
        Session.objects.filter(session_key=session_key).delete()
    record_audit("logout", actor=user, target_username=user.username, payload={"auth_mode": "session"})


@receiver(user_login_failed)
def _record_login_failed(sender, credentials, request, **kwargs):
    from .services import record_login_failure

    username = str((credentials or {}).get("username") or "")
    ip = client_ip(request) if request else ""
    # Bump the atomic throttle counters first so a concurrent burst
    # observes the increment immediately; the audit row that follows is
    # for the historical view in the admin and does not gate anything.
    record_login_failure(username=username, ip=ip)
    record_audit(
        "login_failed",
        actor=None,
        target_username=username or None,
        payload={
            "path": getattr(request, "path", "/login/") if request else "/login/",
            "reason": "invalid-credentials",
            "ip_address": ip,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:256] if request else "",
        },
    )
