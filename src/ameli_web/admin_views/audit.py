"""Recent audit entries endpoint.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ameli_web.accounts.services import (
    list_recent_audit_entries,
)

from ._common import (
    superadmin_required,
)


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
