from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ameli_app.config import Settings


def _process_email_queue() -> dict[str, Any]:
    """Lazy import so the worker can run before Django is bootstrapped
    in unit contexts that don't touch the queue."""
    import os
    import sys
    from pathlib import Path

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import django

    if not getattr(django, "_setup_complete_for_notify", False):
        try:
            django.setup()
            django._setup_complete_for_notify = True
        except Exception:  # noqa: BLE001 - notify-once should still report cleanly
            return {"ok": False, "error": "django setup failed"}

    from ameli_web.accounts.services import process_email_queue

    return process_email_queue()


def run_once(settings: Settings) -> dict[str, Any]:
    queue_result = _process_email_queue()
    return {
        "ok": bool(queue_result.get("ok", False)),
        "worker": "notify",
        "app": settings.app_slug,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
        "queue": queue_result,
    }
