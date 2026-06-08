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
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from ameli_app.password_policy import generate_compliant_password
from ameli_web.audit.models import AuditEvent
from ameli_web.utils import format_timestamp_ui

from datetime import datetime, timedelta

from . import mfa
from .models import MFAEmailChallenge, MFARecoveryCode, UserSession

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


def start_mfa_enrollment(actor_username: str) -> dict[str, Any]:
    """Generate a fresh TOTP secret for the user and return enrollment data.

    Any existing pending TOTP enrollment is overwritten. Existing email
    enrollment is preserved (stacked methods may coexist). Re-enrolling
    a method that is already enabled requires disabling it first.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if user.mfa_totp_enabled:
        raise ValueError("totp mfa is already enabled; disable it before re-enrolling")
    secret = mfa.generate_secret()
    user.mfa_secret = secret
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
    if not mfa.verify_totp(user.mfa_secret, code):
        raise ValueError("invalid verification code")
    was_enabled = user.mfa_enabled
    user.mfa_totp_enabled = True
    user.mfa_enabled = True
    user.mfa_required = False
    user.save(update_fields=["mfa_totp_enabled", "mfa_enabled", "mfa_required", "updated_at"])
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


def disable_mfa_totp_for_self(actor_username: str, *, current_password: str) -> dict[str, Any]:
    """Disable just the TOTP factor for the calling user."""
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
    if not user.mfa_totp_enabled and not user.mfa_secret:
        return {"ok": True, "status": "already-disabled"}
    if not current_password or not user.check_password(current_password):
        raise ValueError("current password is invalid")
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
    user.mfa_totp_enabled = False
    user.mfa_email_enabled = False
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.save(update_fields=["mfa_totp_enabled", "mfa_email_enabled", "mfa_enabled", "mfa_secret", "updated_at"])
    MFARecoveryCode.objects.filter(user=user).delete()
    MFAEmailChallenge.objects.filter(user=user).delete()
    record_audit("mfa_disabled_by_self", actor=user, target_username=user.username, payload={"method": "all"})
    return {"ok": True, "status": "disabled"}


def change_email_for_self(actor_username: str, new_email: str) -> dict[str, Any]:
    """Update the calling user's email.

    If the user had email-based MFA enabled, the new address would not be
    able to receive the next challenge (which is still hashed against the
    old user record but addressed to the new mailbox) so we proactively
    disable the email factor and delete pending challenges. The user keeps
    TOTP and recovery codes if they had any.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
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


def admin_disable_mfa_for_user(actor_username: str, username: str) -> dict[str, Any]:
    """Forcibly disable MFA for a user (e.g. lost device support case).

    Unlike disable_mfa_for_self, this does not ask for the target's
    password — it is an admin recovery action. Rejects self use so a
    superadmin still has to go through their own profile (and password)
    to disable their own MFA.
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
        payload={},
    )
    return {"ok": True, "status": "disabled"}


def _check_email_mfa_rate_limit(user) -> None:
    """Raise ValueError if the user requested too many codes recently."""
    now = timezone.now()
    latest = MFAEmailChallenge.objects.filter(user=user).order_by("-created_at").first()
    if latest is not None:
        gap = (now - latest.created_at).total_seconds()
        if gap < mfa.EMAIL_CODE_RESEND_INTERVAL_SECONDS:
            wait = int(mfa.EMAIL_CODE_RESEND_INTERVAL_SECONDS - gap)
            raise ValueError(f"too many requests; wait {wait} seconds before asking for a new code")
    hour_count = MFAEmailChallenge.objects.filter(
        user=user,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if hour_count >= mfa.EMAIL_CODE_HOURLY_LIMIT:
        raise ValueError("too many requests in the last hour; try again later")


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


def start_mfa_email_enrollment(actor_username: str) -> dict[str, Any]:
    """Begin the email-based MFA enrollment for the calling user.

    Coexists with TOTP — the user's mfa_secret is left untouched so a
    user may stack both methods. Already-enrolled email users have to
    disable email first to re-enroll.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
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
    user.mfa_required = False
    user.save(update_fields=["mfa_email_enabled", "mfa_enabled", "mfa_required", "updated_at"])
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


def regenerate_recovery_codes(actor_username: str) -> dict[str, Any]:
    """Invalidate every existing recovery code and emit 10 fresh ones.

    The plaintext codes are returned once for the user to copy down; only
    the hashes are persisted. Requires MFA to be already enabled — there
    is no point regenerating codes that protect nothing.
    """
    user = User.objects.filter(username__iexact=actor_username).first()
    if user is None:
        raise ValueError("user not found")
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


class _PasswordResetEmail(EmailMessage):
    """EmailMessage variant that forces a 7bit body so the long reset URL
    is never soft-wrapped with ``=\\n`` by Python's quoted-printable encoder.

    Setting ``EmailMessage.encoding = 'us-ascii'`` is not enough: depending
    on the Python / Django version the body still ends up encoded as
    quoted-printable when any individual line exceeds 76 characters, which
    breaks the reset URL when a developer copies it out of journalctl. By
    rewriting the MIME payload with no charset/encoding and stamping the
    Content-Transfer-Encoding header back to ``7bit`` we guarantee a
    passthrough body, regardless of line length.
    """

    def message(self, *args, **kwargs):  # type: ignore[override]
        # Python 3.13 introduced a ``policy`` keyword on
        # ``EmailMessage.message()``; older versions had no extra args.
        # Forwarding ``*args``/``**kwargs`` keeps both signatures happy.
        msg = super().message(*args, **kwargs)
        if "Content-Transfer-Encoding" in msg:
            del msg["Content-Transfer-Encoding"]
        msg["Content-Transfer-Encoding"] = "7bit"
        msg.set_payload(self.body, charset=None)
        msg.set_param("charset", "us-ascii")
        return msg


def _send_password_reset_email(user, reset_url: str) -> None:
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
    email.send(fail_silently=False)


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
