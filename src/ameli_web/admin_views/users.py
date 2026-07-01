"""Users listing + CRUD + password reset + MFA disable + unlock.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from ameli_web.accounts.models import User
from ameli_web.accounts.services import (
    admin_disable_mfa_for_user,
    change_password_for_user,
    create_user_account,
    delete_user_account,
    list_users,
    reset_user_password,
    summarize_users,
    update_user_account,
)

from ._common import (
    _json_body,
    _json_error,
    sudo_required,
    superadmin_required,
)


@require_http_methods(["GET", "POST"])
@superadmin_required
def admin_users(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        users = list_users()
        return JsonResponse({"ok": True, "users": users, "summary": summarize_users()})
    # POST creates a new user, possibly a superadmin. Require sudo so a
    # leaked admin session cannot silently mint additional superadmins.
    from ameli_web.accounts.services import session_in_sudo

    if not session_in_sudo(request.session):
        return JsonResponse(
            {"ok": False, "error": "sudo required", "need_sudo": True, "sudo_url": "/admin/sudo/"},
            status=401,
        )
    payload = _json_body(request)
    try:
        result = create_user_account(
            actor_username=request.user.username,
            username=str(payload.get("username") or "").strip(),
            password=str(payload.get("password") or "").strip(),
            role=str(payload.get("role") or User.ROLE_PUBLIC).strip(),
            must_change_password=bool(payload.get("must_change_password")),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_http_methods(["POST", "PATCH", "DELETE"])
@superadmin_required
@sudo_required
def admin_update_user(request: HttpRequest, username: str) -> JsonResponse:
    if request.method == "DELETE":
        try:
            result = delete_user_account(actor_username=request.user.username, username=username)
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse(result)
    payload = _json_body(request)
    try:
        result = update_user_account(
            actor_username=request.user.username,
            username=username,
            password=(str(payload["password"]).strip() if payload.get("password") else None),
            enabled=payload.get("enabled"),
            must_change_password=payload.get("must_change_password"),
            role=payload.get("role"),
            mfa_required=payload.get("mfa_required"),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
@sudo_required
def admin_disable_user_mfa(request: HttpRequest, username: str) -> JsonResponse:
    try:
        result = admin_disable_mfa_for_user(actor_username=request.user.username, username=username)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
@sudo_required
def admin_reset_user_password(request: HttpRequest, username: str) -> JsonResponse:
    payload = _json_body(request)
    try:
        result = reset_user_password(
            actor_username=request.user.username,
            username=username,
            password=(str(payload["password"]).strip() if payload.get("password") else None),
            must_change_password=bool(payload.get("must_change_password", True)),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
def admin_change_password(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    try:
        result = change_password_for_user(
            request.user.username,
            str(payload.get("current_password") or "").strip(),
            str(payload.get("new_password") or "").strip(),
            current_session_key=str(request.session.session_key or ""),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


_AUDIT_EXPORT_COLUMNS = [
    "id",
    "created_at",
    "actor_username",
    "target_username",
    "action",
    "display_result_label",
    "payload",
]


@require_POST
@superadmin_required
@sudo_required
def admin_unlock_user(request: HttpRequest, username: str) -> JsonResponse:
    """Clear the ``locked_at`` flag for a user that hit the permanent-
    lockout threshold. Sudo-gated like every other write."""
    from ameli_web.accounts.services import admin_unlock_user as _unlock

    try:
        result = _unlock(actor_username=request.user.username, username=username)
    except ValueError as exc:
        return _json_error(str(exc), status=404)
    return JsonResponse(result)
