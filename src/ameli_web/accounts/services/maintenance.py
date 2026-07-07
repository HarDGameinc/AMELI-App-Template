"""Maintenance mode — get/set the site-wide maintenance flag.

Moved from services/__init__.py (PC-1 step 7, 2026-06-30).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from ..models import MaintenanceMode
from .audit import record_audit

User = get_user_model()


def get_maintenance_state() -> dict[str, Any]:
    """Return the current MaintenanceMode singleton as a plain dict.

    Cheap enough to call on every request — the row is a single PK
    lookup and the table has at most one row.
    """
    row = MaintenanceMode.objects.filter(pk=MaintenanceMode.SINGLETON_PK).first()
    if row is None:
        return {
            "active": False,
            "read_only": True,
            "message": "",
            "activated_at": None,
            "activated_by": "",
        }
    return {
        "active": bool(row.active),
        "read_only": bool(row.read_only),
        "message": row.message or "",
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "activated_by": row.activated_by_username or "",
    }


def enable_maintenance(
    actor_username: str, *, message: str = "", read_only: bool = True,
) -> dict[str, Any]:
    """Flip the maintenance flag on; audit the change."""
    row, _ = MaintenanceMode.objects.get_or_create(pk=MaintenanceMode.SINGLETON_PK)
    if row.active:
        return {"ok": True, "status": "already-active", "state": get_maintenance_state()}
    row.active = True
    row.read_only = bool(read_only)
    row.message = message or ""
    row.activated_at = timezone.now()
    row.deactivated_at = None
    row.activated_by_username = actor_username or ""
    row.save()
    actor_obj = User.objects.filter(username__iexact=actor_username).first() if actor_username else None
    record_audit(
        "maintenance_enabled",
        actor=actor_obj,
        target_username="",
        payload={"read_only": row.read_only, "message_len": len(row.message)},
    )
    return {"ok": True, "status": "enabled", "state": get_maintenance_state()}


def disable_maintenance(actor_username: str) -> dict[str, Any]:
    """Flip the maintenance flag off; audit the change."""
    row = MaintenanceMode.objects.filter(pk=MaintenanceMode.SINGLETON_PK).first()
    if row is None or not row.active:
        return {"ok": True, "status": "already-inactive", "state": get_maintenance_state()}
    row.active = False
    row.deactivated_at = timezone.now()
    row.save()
    actor_obj = User.objects.filter(username__iexact=actor_username).first() if actor_username else None
    record_audit(
        "maintenance_disabled",
        actor=actor_obj,
        target_username="",
        payload={"was_message_len": len(row.message)},
    )
    return {"ok": True, "status": "disabled", "state": get_maintenance_state()}
