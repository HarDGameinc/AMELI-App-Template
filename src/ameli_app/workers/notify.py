from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ameli_app.config import Settings


def _ensure_django() -> bool:
    """Bootstrap Django if it isn't already configured.

    ``django.setup()`` is idempotent and ``django.apps.apps.ready`` is
    the canonical sentinel — no need to stash a flag on the module.
    Returns ``True`` on success so the caller can short-circuit on
    a misconfigured environment without crashing the worker loop.
    """
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import django
    from django.apps import apps

    if apps.ready:
        return True
    try:
        django.setup()
    except Exception:  # noqa: BLE001 - notify-once should still report cleanly
        return False
    return True


def _process_email_queue() -> dict[str, Any]:
    if not _ensure_django():
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
