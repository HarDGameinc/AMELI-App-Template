"""Password reset by email — request/verify/complete the reset flow.

Moved from services/__init__.py (PC-1 step 7, 2026-06-30).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .audit import record_audit
from .email_queue import _PasswordResetEmail, send_with_retry
from .session import revoke_other_sessions
from .user import _validate_password_value, serialize_user, sync_user_groups

User = get_user_model()


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
