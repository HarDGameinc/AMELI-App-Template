"""Session listing + revoke endpoint.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import (
    list_recent_sessions,
    revoke_session_record,
)

from ._common import (
    _json_error,
    sudo_required,
    superadmin_required,
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
@sudo_required
def admin_revoke_session(request: HttpRequest, session_key: str) -> JsonResponse:
    session = UserSession.objects.select_related("user").filter(session_key=session_key).first()
    if session is None:
        return _json_error("session not found", status=404)
    revoke_session_record(session, actor=request.user, reason="admin-revoke")
    return JsonResponse({"ok": True, "status": "updated", "session_key": session_key})
