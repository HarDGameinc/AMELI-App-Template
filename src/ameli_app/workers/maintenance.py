from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ameli_app.config import Settings


def run_once(settings: Settings) -> dict[str, Any]:
    return {
        "ok": True,
        "worker": "maintenance",
        "app": settings.app_slug,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Maintenance placeholder executed.",
    }
