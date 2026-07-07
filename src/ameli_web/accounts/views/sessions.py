"""Session revocation + admin session JSON.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from ..models import UserSession
from ..permissions import can_access_admin_panel
from ..services import (
    revoke_other_sessions,
    revoke_session_record,
    serialize_user,
)
from ._common import (
    _expects_json,
    _json_error,
)


@login_required
@require_POST
def revoke_other_sessions_view(request: HttpRequest) -> HttpResponse:
    revoked = revoke_other_sessions(request.user, current_session_key=str(request.session.session_key or ""))
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "revoked_sessions": revoked})
    messages.success(request, f"Se revocaron {revoked} sesiones.")
    return redirect("accounts:profile")


@login_required
@require_POST
def revoke_session_view(request: HttpRequest, session_key: str) -> HttpResponse:
    session_record = get_object_or_404(UserSession, user=request.user, session_key=session_key)
    if session_record.session_key == str(request.session.session_key or ""):
        if _expects_json(request):
            return _json_error("cannot revoke current session")
        messages.error(request, "No puedes revocar la sesion que estas usando ahora.")
        return redirect("accounts:profile")
    revoke_session_record(session_record, actor=request.user, reason="manual-revoke")
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "session_key": session_key})
    messages.success(request, "Sesion revocada.")
    return redirect("accounts:profile")


@login_required
@require_GET
def admin_session_json(request: HttpRequest) -> JsonResponse:
    payload = {
        "ok": True,
        "enabled": True,
        "authenticated": True,
        "auth_mode": "session",
        "csrf_token": get_token(request),
        "user": serialize_user(request.user),
        "can_access_admin": can_access_admin_panel(request.user),
    }
    return JsonResponse(payload)
