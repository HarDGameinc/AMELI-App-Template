"""User domain — CRUD, serialization, password change, avatars, account deletion.

Moved from services/__init__.py (PC-1 step 8, 2026-06-30).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.mail import EmailMessage
from django.utils import timezone

from ameli_app.password_policy import generate_compliant_password
from ameli_web.utils import format_timestamp_ui

from ..models import MFAEmailChallenge, MFARecoveryCode, UserSession
from .audit import record_audit
from .email_queue import _PasswordResetEmail
from .session import revoke_other_sessions, revoke_session_record

User = get_user_model()
ROLE_GROUPS = {
    "public": "public",
    "superadmin": "superadmin",
}

_PROFILE_TEST_EMAIL_COOLDOWN_SECONDS = 30


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


def replace_avatar(user, uploaded_file) -> None:
    from .images import transform_avatar

    old_name = user.avatar.name if user.avatar else ""
    # D-5: normalise the upload (resize + WebP + EXIF strip) before it
    # hits storage. ``transform_avatar`` returns ``None`` when the
    # operator opted out (``AVATAR_FORMAT=keep``) or the transform
    # failed — in either case we fall back to storing the file verbatim.
    transformed = transform_avatar(uploaded_file, filename=uploaded_file.name)
    if transformed is not None:
        content, name = transformed
        user.avatar.save(name, content, save=False)
    else:
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
