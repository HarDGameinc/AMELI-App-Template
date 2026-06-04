from __future__ import annotations
from typing import Any

from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db.models import Count
from django.utils import timezone

from django.conf import settings as django_settings

from ameli_app.password_policy import generate_compliant_password
from ameli_web.audit.models import AuditEvent
from ameli_web.utils import format_timestamp_ui

from . import mfa
from .models import MFARecoveryCode, UserSession

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


def record_audit(action: str, *, actor=None, target_username: str | None = None, payload: dict[str, Any] | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        actor_username=(getattr(actor, "username", None) or ""),
        target_username=(target_username or ""),
        action=action,
        payload=payload or {},
    )


def client_ip(request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.META.get("REMOTE_ADDR"):
        return str(request.META["REMOTE_ADDR"])
    return ""


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
        "created_at": user.created_at.isoformat() if getattr(user, "created_at", None) else None,
        "updated_at": user.updated_at.isoformat() if getattr(user, "updated_at", None) else None,
        "display_created_at": format_timestamp_ui(getattr(user, "created_at", None)),
        "display_updated_at": format_timestamp_ui(getattr(user, "updated_at", None)),
        "display_last_login_at": format_timestamp_ui(user.last_login),
        "last_login_at": user.last_login.isoformat() if user.last_login else None,
    }


def serialize_session(session: UserSession, *, current_session_key: str | None = None) -> dict[str, Any]:
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
        "user_agent": session.user_agent,
        "display_user_agent": session.user_agent,
        "ip_address": session.ip_address,
        "revoked": session.revoked_at is not None,
    }


def list_user_sessions(user, *, current_session_key: str | None = None) -> list[dict[str, Any]]:
    return [serialize_session(item, current_session_key=current_session_key) for item in user.web_sessions.all()]


def list_recent_sessions(*, limit: int = 20, current_session_key: str | None = None) -> list[dict[str, Any]]:
    queryset = UserSession.objects.select_related("user").order_by("-last_seen_at")[: max(1, limit)]
    return [serialize_session(item, current_session_key=current_session_key) for item in queryset]


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


def update_user_account(actor_username: str, username: str, *, password: str | None = None, enabled: bool | None = None, must_change_password: bool | None = None, role: str | None = None) -> dict[str, Any]:
    is_self = (actor_username or "").lower() == (username or "").lower()
    if is_self and enabled is False:
        raise ValueError("cannot disable your own account")
    if is_self and role is not None:
        raise ValueError("cannot change your own role")
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
    user.save()
    sync_user_groups(user)
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit("update_user", actor=actor, target_username=user.username, payload={"enabled": user.is_active, "role": user.role})
    return {"ok": True, "status": "updated", "user": serialize_user(user)}


def delete_user_account(actor_username: str, username: str) -> dict[str, Any]:
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    if user.role == User.ROLE_SUPERADMIN:
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


# ---------------------------------------------------------------------------
# MFA / TOTP
# ---------------------------------------------------------------------------


def serialize_mfa_status(user) -> dict[str, Any]:
    """Return the MFA snapshot used to render the profile and admin views."""
    pending = bool(user.mfa_secret) and not user.mfa_enabled
    remaining = (
        MFARecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
        if user.mfa_enabled
        else 0
    )
    return {
        "enabled": bool(user.mfa_enabled),
        "pending_enrollment": pending,
        "required_by_admin": bool(user.mfa_required),
        "recovery_codes_remaining": remaining,
    }


def start_mfa_enrollment(actor_username: str) -> dict[str, Any]:
    """Generate a fresh TOTP secret for the user and return enrollment data.

    Any existing pending enrollment is overwritten. Already-enrolled users
    must call disable first.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if user.mfa_enabled:
        raise ValueError("mfa is already enabled; disable it before re-enrolling")
    secret = mfa.generate_secret()
    user.mfa_secret = secret
    user.mfa_enabled = False
    user.save(update_fields=["mfa_secret", "mfa_enabled", "updated_at"])
    MFARecoveryCode.objects.filter(user=user).delete()
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
    if user.mfa_enabled:
        raise ValueError("mfa is already enabled")
    if not user.mfa_secret:
        raise ValueError("no pending enrollment; start enrollment first")
    if not mfa.verify_totp(user.mfa_secret, code):
        raise ValueError("invalid verification code")
    user.mfa_enabled = True
    user.mfa_required = False
    user.save(update_fields=["mfa_enabled", "mfa_required", "updated_at"])
    codes = mfa.generate_recovery_codes()
    MFARecoveryCode.objects.bulk_create(
        [MFARecoveryCode(user=user, code_hash=mfa.hash_recovery_code(code_value)) for code_value in codes]
    )
    record_audit(
        "mfa_enrollment_completed",
        actor=user,
        target_username=user.username,
        payload={"recovery_codes_count": len(codes)},
    )
    return {
        "ok": True,
        "status": "enabled",
        "recovery_codes": codes,
    }


def disable_mfa_for_self(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Disable MFA for the calling user after re-confirming their password."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not user.mfa_enabled and not user.mfa_secret:
        return {"ok": True, "status": "already-disabled"}
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.save(update_fields=["mfa_enabled", "mfa_secret", "updated_at"])
    MFARecoveryCode.objects.filter(user=user).delete()
    record_audit("mfa_disabled_by_self", actor=user, target_username=user.username, payload={})
    return {"ok": True, "status": "disabled"}


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
