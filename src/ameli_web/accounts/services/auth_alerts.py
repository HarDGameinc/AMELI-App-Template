"""Auth-failure alert — notify user when the per-username lockout threshold is crossed (ASVS V2.2.3).

Moved from services/__init__.py (PC-1 cleanup, 2026-07-01).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from .audit import record_audit
from .email_queue import _PasswordResetEmail, send_with_retry
from .throttle import _throttle_settings

User = get_user_model()


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
