from __future__ import annotations

import json
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from ameli_app import __version__
from ameli_web.accounts.models import User, UserSession
from ameli_web.accounts.services import (
    change_password_for_user,
    create_user_account,
    delete_user_account,
    list_recent_audit_entries,
    list_recent_sessions,
    list_users,
    reset_user_password,
    revoke_session_record,
    serialize_user,
    summarize_users,
    update_user_account,
)


def _expects_json(request: HttpRequest) -> bool:
    content_type = request.headers.get("Content-Type", "")
    accept = request.headers.get("Accept", "")
    return (
        "application/json" in content_type
        or "application/json" in accept
        or bool(request.headers.get("X-CSRF-Token"))
    )


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json body") from exc


def superadmin_required(view_func):
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            if _expects_json(request):
                return _json_error("authentication required", status=401)
            return redirect(f"/login/?next={request.path}")
        if not user.is_staff:
            if _expects_json(request):
                return _json_error("admin access required", status=403)
            return redirect("/profile/")
        return view_func(request, *args, **kwargs)

    return _wrapped


@require_GET
@superadmin_required
def admin_panel(request: HttpRequest) -> HttpResponse:
    current_session_key = str(request.session.session_key or "")
    context = {
        "version": __version__,
        "users": list_users(),
        "current_user": serialize_user(request.user),
        "user_summary": summarize_users(),
        "audit_entries": list_recent_audit_entries(limit=20),
        "recent_sessions": list_recent_sessions(limit=20, current_session_key=current_session_key),
        "native_admin_url": "/django-admin/",
        "csrf_token": get_token(request),
    }
    return render(request, "admin/panel.html", context)


@superadmin_required
def admin_users(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        users = list_users()
        return JsonResponse({"ok": True, "users": users, "summary": summarize_users()})
    if request.method == "POST":
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
    return _json_error("method not allowed", status=405)


@require_GET
@superadmin_required
def admin_audit(request: HttpRequest) -> JsonResponse:
    limit = int(request.GET.get("limit", "30") or "30")
    actor = request.GET.get("actor")
    target = request.GET.get("target")
    return JsonResponse(
        {
            "ok": True,
            "items": list_recent_audit_entries(limit=limit, actor_username=actor, target_username=target),
        }
    )


@require_GET
@superadmin_required
def admin_sessions(request: HttpRequest) -> JsonResponse:
    limit = int(request.GET.get("limit", "30") or "30")
    current_session_key = str(request.session.session_key or "")
    return JsonResponse(
        {"ok": True, "items": list_recent_sessions(limit=limit, current_session_key=current_session_key)}
    )


@require_POST
@superadmin_required
def admin_revoke_session(request: HttpRequest, session_key: str) -> JsonResponse:
    session = UserSession.objects.select_related("user").filter(session_key=session_key).first()
    if session is None:
        return _json_error("session not found", status=404)
    revoke_session_record(session, actor=request.user, reason="admin-revoke")
    return JsonResponse({"ok": True, "status": "updated", "session_key": session_key})


@superadmin_required
def admin_update_user(request: HttpRequest, username: str) -> JsonResponse:
    if request.method == "DELETE":
        try:
            result = delete_user_account(actor_username=request.user.username, username=username)
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse(result)
    if request.method not in {"PATCH", "POST"}:
        return _json_error("method not allowed", status=405)
    payload = _json_body(request)
    try:
        result = update_user_account(
            actor_username=request.user.username,
            username=username,
            password=(str(payload["password"]).strip() if payload.get("password") else None),
            enabled=payload.get("enabled"),
            must_change_password=payload.get("must_change_password"),
            role=payload.get("role"),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
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
