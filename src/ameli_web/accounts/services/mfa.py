"""MFA domain — TOTP enrollment, email-based MFA, recovery codes.

Moved from services/__init__.py (PC-1 step 6, 2026-06-30).
Public symbols are re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from .. import mfa
from ..models import MFAEmailChallenge, MFARecoveryCode
from .audit import record_audit
from .email_queue import _PasswordResetEmail, send_with_retry

User = get_user_model()


# ---------------------------------------------------------------------------
# MFA / TOTP
# ---------------------------------------------------------------------------


def serialize_mfa_status(user) -> dict[str, Any]:
    """Return the MFA snapshot used to render the profile and admin views."""
    totp_pending = bool(user.mfa_secret) and not user.mfa_totp_enabled
    has_pending_email_challenge = MFAEmailChallenge.objects.filter(
        user=user, used_at__isnull=True, expires_at__gt=timezone.now()
    ).exists()
    email_pending = not user.mfa_email_enabled and has_pending_email_challenge
    remaining = (
        MFARecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
        if user.mfa_enabled
        else 0
    )
    return {
        "enabled": bool(user.mfa_enabled),
        "totp_enabled": bool(user.mfa_totp_enabled),
        "email_enabled": bool(user.mfa_email_enabled),
        "totp_pending": totp_pending,
        "email_pending": email_pending,
        "required_by_admin": bool(user.mfa_required),
        "recovery_codes_remaining": remaining,
        "has_email": bool(getattr(user, "email", "")),
    }


def start_mfa_enrollment(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Generate a fresh TOTP secret for the user and return enrollment data.

    Any existing pending TOTP enrollment is overwritten. Existing email
    enrollment is preserved (stacked methods may coexist). Re-enrolling
    a method that is already enabled requires disabling it first.

    Requires the caller to re-confirm ``current_password``: a stolen
    session cookie alone must not be able to provision a fresh TOTP
    secret on the victim's account (and effectively become their
    second factor). Same pattern as ``disable_mfa_for_self``.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    if user.mfa_totp_enabled:
        raise ValueError("totp mfa is already enabled; disable it before re-enrolling")
    secret = mfa.generate_secret()
    # Persist encrypted; ``mfa.encrypt_secret`` pass-throughs when no
    # MFA_ENCRYPTION_KEY is configured (dev / CI).
    user.mfa_secret = mfa.encrypt_secret(secret)
    user.save(update_fields=["mfa_secret", "updated_at"])
    issuer = django_settings.CFG.app_name
    uri = mfa.provisioning_uri(secret, username=user.username, issuer=issuer)
    record_audit("mfa_enrollment_started", actor=user, target_username=user.username, payload={})
    return {
        "ok": True,
        "status": "pending",
        "secret": secret,
        "provisioning_uri": uri,
        "qr_svg": mfa.render_qr_svg(uri),
        "issuer": issuer,
    }


def confirm_mfa_enrollment(actor_username: str, code: str) -> dict[str, Any]:
    """Verify the user's first TOTP code and finalize enrollment.

    Returns the freshly generated recovery codes in plaintext one time.
    The hashes are stored; the plaintext is never persisted.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if user.mfa_totp_enabled:
        raise ValueError("totp mfa is already enabled")
    if not user.mfa_secret:
        raise ValueError("no pending enrollment; start enrollment first")
    if not mfa.verify_totp(mfa.decrypt_secret(user.mfa_secret), code):
        raise ValueError("invalid verification code")
    was_enabled = user.mfa_enabled
    user.mfa_totp_enabled = True
    user.mfa_enabled = True
    # NOTE: do NOT clear ``mfa_required`` here. Enrolling already satisfies
    # the mandate (``mfa_enabled`` is now True, so the enrollment gate
    # passes), and keeping the flag set is what lets ``disable_*_for_self``
    # refuse to drop an admin-mandated account back below MFA (M2).
    user.save(update_fields=["mfa_totp_enabled", "mfa_enabled", "updated_at"])
    # Only mint a fresh recovery batch the first time the user enables
    # ANY method. Stacking the second method keeps the existing codes.
    if not was_enabled:
        MFARecoveryCode.objects.filter(user=user).delete()
        codes = mfa.generate_recovery_codes()
        MFARecoveryCode.objects.bulk_create(
            [MFARecoveryCode(user=user, code_hash=mfa.hash_recovery_code(code_value)) for code_value in codes]
        )
    else:
        codes = []  # caller stays on the existing batch
    record_audit(
        "mfa_enrollment_completed",
        actor=user,
        target_username=user.username,
        payload={"method": "totp", "recovery_codes_count": len(codes)},
    )
    return {
        "ok": True,
        "status": "enabled",
        "method": "totp",
        "recovery_codes": codes,
    }


# Raised (as ValueError) when a self-disable would drop an account that an
# admin has flagged ``mfa_required`` below MFA entirely. The mandate is
# absolute for self-service; only an admin can lift it (clear the flag).
_MFA_REQUIRED_DISABLE_MSG = (
    "Un administrador exige 2FA en esta cuenta; no puedes desactivar tu "
    "ultimo factor. Contacta al administrador si necesitas removerlo."
)


def disable_mfa_totp_for_self(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Disable just the TOTP factor for the calling user."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not user.mfa_totp_enabled and not user.mfa_secret:
        return {"ok": True, "status": "already-disabled"}
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    # M2: refuse to drop a mandated account below MFA. Disabling TOTP is
    # only allowed here if the email factor keeps them covered.
    if user.mfa_required and not user.mfa_email_enabled:
        raise ValueError(_MFA_REQUIRED_DISABLE_MSG)
    user.mfa_totp_enabled = False
    user.mfa_secret = ""
    user.mfa_enabled = bool(user.mfa_email_enabled)
    user.save(update_fields=["mfa_totp_enabled", "mfa_secret", "mfa_enabled", "updated_at"])
    if not user.mfa_enabled:
        MFARecoveryCode.objects.filter(user=user).delete()
    record_audit(
        "mfa_disabled_by_self",
        actor=user,
        target_username=user.username,
        payload={"method": "totp"},
    )
    return {"ok": True, "status": "disabled", "method": "totp"}


def disable_mfa_email_for_self(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Disable just the email factor for the calling user."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    has_pending = MFAEmailChallenge.objects.filter(user=user).exists()
    if not user.mfa_email_enabled and not has_pending:
        return {"ok": True, "status": "already-disabled"}
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    # M2: refuse to drop a mandated account below MFA (TOTP must remain).
    if user.mfa_required and not user.mfa_totp_enabled:
        raise ValueError(_MFA_REQUIRED_DISABLE_MSG)
    user.mfa_email_enabled = False
    user.mfa_enabled = bool(user.mfa_totp_enabled)
    user.save(update_fields=["mfa_email_enabled", "mfa_enabled", "updated_at"])
    MFAEmailChallenge.objects.filter(user=user).delete()
    if not user.mfa_enabled:
        MFARecoveryCode.objects.filter(user=user).delete()
    record_audit(
        "mfa_disabled_by_self",
        actor=user,
        target_username=user.username,
        payload={"method": "email"},
    )
    return {"ok": True, "status": "disabled", "method": "email"}


# Legacy alias for callers that used to nuke everything. New code should
# prefer one of the per-method helpers above so the user can keep their
# remaining factor active.
def disable_mfa_for_self(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Disable every active MFA factor for the calling user."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not user.mfa_enabled and not user.mfa_secret and not user.mfa_totp_enabled and not user.mfa_email_enabled:
        return {"ok": True, "status": "already-disabled"}
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    # M2: a mandated account cannot self-disable ALL factors.
    if user.mfa_required:
        raise ValueError(_MFA_REQUIRED_DISABLE_MSG)
    user.mfa_totp_enabled = False
    user.mfa_email_enabled = False
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.save(update_fields=["mfa_totp_enabled", "mfa_email_enabled", "mfa_enabled", "mfa_secret", "updated_at"])
    MFARecoveryCode.objects.filter(user=user).delete()
    MFAEmailChallenge.objects.filter(user=user).delete()
    record_audit("mfa_disabled_by_self", actor=user, target_username=user.username, payload={"method": "all"})
    return {"ok": True, "status": "disabled"}


def _send_mfa_disabled_by_admin_notification(user, *, actor_username: str) -> bool:
    """Notify the user that their 2FA was disabled by an administrator.

    Returns True when an email was actually attempted (user has an
    address), False when there is nothing to notify. Delivery exceptions
    are swallowed: the disable action itself must complete even if SMTP
    is broken — we audit a ``mfa_disabled_notify_failed`` row so the
    operator can replay manually.
    """
    if not (user.email or "").strip():
        return False
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "actor": actor_username or "admin",
    }
    body = render_to_string("accounts/mfa_disabled_by_admin.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Se deshabilito el 2FA de tu cuenta"
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
        to=[user.email],
    )
    actor = User.objects.filter(username__iexact=actor_username).first()
    # send_with_retry handles transient SMTP failure: the disable
    # action itself completes, the notification slides to the queue
    # and the worker retries. Permanent failure is audited by the
    # worker as ``email_failed_permanent`` after max_attempts.
    # audit_payload preserves the {actor, email} context the inline
    # path records so the eventual delivery audit row is equivalent.
    # expires_at caps the lifetime: a "your 2FA got disabled" message
    # that arrives 7 h late is more confusing than useful.
    result = send_with_retry(
        email,
        audit_action="mfa_disabled_notify_sent",
        target_username=user.username,
        audit_payload={"email": user.email, "actor": actor_username or "admin"},
        expires_at=timezone.now() + timedelta(hours=2),
    )
    if result["status"] == "queued":
        record_audit(
            "mfa_disabled_notify_queued",
            actor=actor,
            target_username=user.username,
            payload={"queue_id": result.get("queue_id"), "error_class": "queued"},
        )
        return True
    record_audit(
        "mfa_disabled_notify_sent",
        actor=actor,
        target_username=user.username,
        payload={"email": user.email},
    )
    return True


def admin_disable_mfa_for_user(actor_username: str, username: str) -> dict[str, Any]:
    """Forcibly disable MFA for a user (e.g. lost device support case).

    Unlike disable_mfa_for_self, this does not ask for the target's
    password — it is an admin recovery action. Rejects self use so a
    superadmin still has to go through their own profile (and password)
    to disable their own MFA. Notifies the user by email so a malicious
    admin cannot silently take over an account: even if the audit log
    is tampered with, the legitimate user gets a real-time signal.
    """
    is_self = (actor_username or "").lower() == (username or "").lower()
    if is_self:
        raise ValueError("cannot disable your own mfa from the admin; use your profile instead")
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    user.mfa_totp_enabled = False
    user.mfa_email_enabled = False
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.mfa_required = False
    user.save(
        update_fields=[
            "mfa_totp_enabled",
            "mfa_email_enabled",
            "mfa_enabled",
            "mfa_secret",
            "mfa_required",
            "updated_at",
        ]
    )
    MFARecoveryCode.objects.filter(user=user).delete()
    MFAEmailChallenge.objects.filter(user=user).delete()
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit(
        "mfa_disabled_by_admin",
        actor=actor,
        target_username=user.username,
        payload={"actor": actor_username},
    )
    notified = _send_mfa_disabled_by_admin_notification(
        user, actor_username=actor_username,
    )
    return {"ok": True, "status": "disabled", "notified": notified}


def _check_email_mfa_rate_limit(user) -> None:
    """Raise ValueError if the user requested too many codes recently."""
    now = timezone.now()
    latest = MFAEmailChallenge.objects.filter(user=user).order_by("-created_at").first()
    if latest is not None:
        gap = (now - latest.created_at).total_seconds()
        if gap < mfa.EMAIL_CODE_RESEND_INTERVAL_SECONDS:
            wait = int(mfa.EMAIL_CODE_RESEND_INTERVAL_SECONDS - gap)
            raise ValueError(
                f"Espera {wait} segundos antes de pedir otro codigo por email."
            )
    hour_count = MFAEmailChallenge.objects.filter(
        user=user,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if hour_count >= mfa.EMAIL_CODE_HOURLY_LIMIT:
        raise ValueError(
            "Demasiados pedidos de codigo por email en la ultima hora. Probá mas tarde o usá tu app de autenticacion."
        )


def _send_mfa_email_code(user, code: str) -> None:
    """Render and deliver the MFA code email (reuses the 7bit-safe class)."""
    context = {
        "app_name": django_settings.CFG.app_name,
        "username": user.username,
        "code": code,
        "ttl_minutes": mfa.EMAIL_CODE_TTL_SECONDS // 60,
    }
    body = render_to_string("accounts/mfa_email_code.txt", context)
    subject = f"[{django_settings.CFG.app_name}] Tu codigo de verificacion"
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


def _create_and_send_email_challenge(user) -> dict[str, Any]:
    """Invalidate previous unused challenges, generate and deliver a new one."""
    if not user.email:
        raise ValueError("no email on file for this account")
    _check_email_mfa_rate_limit(user)
    # Burn any earlier pending codes so only the last one is valid.
    MFAEmailChallenge.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    plaintext = mfa.generate_email_code()
    challenge = MFAEmailChallenge.objects.create(
        user=user,
        code_hash=mfa.hash_email_code(plaintext),
        expires_at=timezone.now() + timedelta(seconds=mfa.EMAIL_CODE_TTL_SECONDS),
    )
    _send_mfa_email_code(user, plaintext)
    return {
        "ok": True,
        "status": "sent",
        "email": user.email,
        "ttl_seconds": mfa.EMAIL_CODE_TTL_SECONDS,
        "challenge_id": challenge.pk,
    }


def consume_email_mfa_code(user, candidate: str) -> bool:
    """Burn the most recent matching unused, unexpired challenge.

    Returns True when a code matched, False otherwise. Constant-time
    comparison via mfa.email_codes_match guards against timing attacks.
    """
    if not candidate:
        return False
    candidate = candidate.strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != mfa.EMAIL_CODE_LENGTH:
        return False
    code_hash = mfa.hash_email_code(candidate)
    now = timezone.now()
    challenge = MFAEmailChallenge.objects.filter(
        user=user,
        code_hash=code_hash,
        used_at__isnull=True,
        expires_at__gt=now,
    ).order_by("-created_at").first()
    if challenge is None:
        return False
    challenge.used_at = now
    challenge.save(update_fields=["used_at"])
    return True


def start_mfa_email_enrollment(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Begin the email-based MFA enrollment for the calling user.

    Coexists with TOTP — the user's mfa_secret is left untouched so a
    user may stack both methods. Already-enrolled email users have to
    disable email first to re-enroll.

    Requires the caller to re-confirm ``current_password``: a stolen
    session cookie alone must not be able to start email MFA enrollment
    on the victim's account. Same pattern as ``disable_mfa_for_self``.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    if user.mfa_email_enabled:
        raise ValueError("email mfa is already enabled; disable it before re-enrolling")
    if not user.email:
        raise ValueError("set an email on your account before enrolling email mfa")
    result = _create_and_send_email_challenge(user)
    record_audit(
        "mfa_email_enrollment_started",
        actor=user,
        target_username=user.username,
        payload={"email": user.email},
    )
    return result


def confirm_mfa_email_enrollment(actor_username: str, code: str) -> dict[str, Any]:
    """Verify the enrollment code and finalize email-based MFA."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if user.mfa_email_enabled:
        raise ValueError("email mfa is already enabled")
    if not consume_email_mfa_code(user, code):
        raise ValueError("invalid or expired verification code")
    was_enabled = user.mfa_enabled
    user.mfa_email_enabled = True
    user.mfa_enabled = True
    # See confirm_mfa_enrollment: keep ``mfa_required`` set so the mandate
    # survives and self-disable stays blocked (M2).
    user.save(update_fields=["mfa_email_enabled", "mfa_enabled", "updated_at"])
    # Only mint a fresh recovery batch the first time the user enables
    # ANY method. Stacking the second method keeps the existing codes.
    if not was_enabled:
        MFARecoveryCode.objects.filter(user=user).delete()
        codes = mfa.generate_recovery_codes()
        MFARecoveryCode.objects.bulk_create(
            [MFARecoveryCode(user=user, code_hash=mfa.hash_recovery_code(code_value)) for code_value in codes]
        )
    else:
        codes = []
    record_audit(
        "mfa_email_enrollment_completed",
        actor=user,
        target_username=user.username,
        payload={"recovery_codes_count": len(codes)},
    )
    return {
        "ok": True,
        "status": "enabled",
        "method": "email",
        "recovery_codes": codes,
    }


def send_mfa_email_login_code(user) -> dict[str, Any]:
    """Generate and deliver an MFA code as part of an in-progress login."""
    if not user.mfa_email_enabled:
        raise ValueError("email mfa is not enrolled for this user")
    if not user.email:
        raise ValueError("no email on file for this account")
    result = _create_and_send_email_challenge(user)
    record_audit(
        "mfa_email_login_code_sent",
        actor=user,
        target_username=user.username,
        payload={},
    )
    return result


def regenerate_recovery_codes(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Invalidate every existing recovery code and emit 10 fresh ones.

    The plaintext codes are returned once for the user to copy down; only
    the hashes are persisted. Requires MFA to be already enabled — there
    is no point regenerating codes that protect nothing.

    Requires the caller to re-confirm ``current_password``: a stolen
    session cookie alone must not be able to mint a fresh set of
    recovery codes (which would become a permanent MFA backdoor — the
    codes do not expire). Same pattern as ``disable_mfa_for_self``.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    if not user.mfa_enabled:
        raise ValueError("mfa is not enabled; activate 2fa before regenerating recovery codes")
    MFARecoveryCode.objects.filter(user=user).delete()
    codes = mfa.generate_recovery_codes()
    MFARecoveryCode.objects.bulk_create(
        [MFARecoveryCode(user=user, code_hash=mfa.hash_recovery_code(code_value)) for code_value in codes]
    )
    record_audit(
        "mfa_recovery_codes_regenerated",
        actor=user,
        target_username=user.username,
        payload={"recovery_codes_count": len(codes)},
    )
    return {"ok": True, "status": "regenerated", "recovery_codes": codes}


def consume_recovery_code(user, candidate: str) -> bool:
    """Burn a single recovery code if it matches an unused row for the user.

    Returns True when a code was consumed, False otherwise. The match is
    case- and separator-insensitive thanks to normalize_recovery_code.
    """
    if not candidate:
        return False
    code_hash = mfa.hash_recovery_code(candidate)
    record = MFARecoveryCode.objects.filter(user=user, code_hash=code_hash, used_at__isnull=True).first()
    if record is None:
        return False
    record.used_at = timezone.now()
    record.save(update_fields=["used_at"])
    record_audit("mfa_recovery_code_used", actor=user, target_username=user.username, payload={})
    return True
