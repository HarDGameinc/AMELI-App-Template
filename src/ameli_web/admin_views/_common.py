"""Cross-view helpers, session/pagination cookies, decorators."""
from __future__ import annotations

import json
from functools import wraps
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect

USERS_PER_PAGE_COOKIE = "ps_users_per_page"
AUDIT_PER_PAGE_COOKIE = "ps_audit_per_page"
SESSIONS_PER_PAGE_COOKIE = "ps_admin_sessions_per_page"


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


def _is_fetch_request(request: HttpRequest) -> bool:
    marker = request.headers.get("X-Requested-With", "").lower()
    return marker in {"fetch", "xmlhttprequest"}


def _json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json body") from exc


def superadmin_required(view_func):
    """Decorator: allow only superadmins; anon → login, other roles → 403."""
    from ameli_web.accounts.permissions import can_access_admin_panel

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect("/login/")
        if not can_access_admin_panel(user):
            return _json_error("forbidden", status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


def sudo_required(view_func):
    """Refuse a write action when the session is not in active sudo.

    Used in addition to ``superadmin_required`` for state-changing admin
    endpoints. The JSON response carries ``need_sudo: true`` so the UI
    can prompt for re-authentication and retry transparently. Read-only
    endpoints (lists, exports) keep using ``superadmin_required`` alone.
    """
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        from ameli_web.accounts.services import session_in_sudo

        if not session_in_sudo(request.session):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "sudo required",
                    "need_sudo": True,
                    "sudo_url": "/admin/sudo/",
                },
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped
