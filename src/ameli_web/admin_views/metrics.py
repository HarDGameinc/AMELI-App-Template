"""Admin dashboard live metrics (email queue).

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ameli_web.accounts.services import (
    summarize_email_queue,
)

from ._common import (
    superadmin_required,
)


@require_GET
@superadmin_required
def admin_email_queue_metrics(request: HttpRequest) -> JsonResponse:
    """Snapshot of the OutboundEmail retry queue for the admin widget.

    Read-only and not gated behind sudo — same posture as the audit
    and sessions listings, which the operator already polls to keep
    an eye on the system without re-confirming credentials every
    refresh.
    """
    return JsonResponse({"ok": True, "summary": summarize_email_queue()})
