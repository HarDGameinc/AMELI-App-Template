"""Maintenance mode toggle + status.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from ameli_web.accounts.services import (
    disable_maintenance,
    enable_maintenance,
    get_maintenance_state,
)

from ._common import (
    _json_error,
    sudo_required,
    superadmin_required,
)


@require_POST
@superadmin_required
@sudo_required
def admin_maintenance_toggle(request: HttpRequest) -> JsonResponse:
    """Flip maintenance on/off. Requires sudo because the consequences
    (503 to writes) are operator-grade."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _json_error("invalid json body")
    action = str(body.get("action") or "").strip().lower()
    actor = request.user.username
    if action == "enable":
        message = str(body.get("message") or "").strip()
        read_only = bool(body.get("read_only", True))
        return JsonResponse(
            enable_maintenance(actor, message=message, read_only=read_only),
        )
    if action == "disable":
        return JsonResponse(disable_maintenance(actor))
    return _json_error("action must be 'enable' or 'disable'")


@require_GET
@superadmin_required
def admin_maintenance_status(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "state": get_maintenance_state()})
