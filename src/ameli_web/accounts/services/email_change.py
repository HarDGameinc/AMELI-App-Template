"""Email-change double-opt-in flow — request/confirm/cancel changes to the user's email address.

Moved from services/__init__.py (PC-1 cleanup, 2026-07-01).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.

Without double-opt-in, anyone who steals a session can change the email
to one they own and then trigger a password reset to take over the
account. We make the change conditional on three things:

 1. The actor knows the current password (proves they are not just a
    cookie thief),
 2. The new address actually receives mail (proves the operator did
    not typo it and locks an attacker out of redirecting to a random
    mailbox they do not control),
 3. The legitimate user always sees an alert at the OLD address with a
    cancel link, so a hijacked session cannot quietly redirect mail.
"""
from __future__ import annotations

import hmac
from datetime import timedelta
from typing import Any

from django.conf import settings as django_settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import EmailChangeRequest, MFAEmailChallenge
from .audit import record_audit
from .email_queue import _PasswordResetEmail

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
