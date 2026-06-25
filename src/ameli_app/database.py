"""DB connectivity health check using the Django ORM.

Previously this module used a thin SQLAlchemy engine to run
``SELECT 1`` against the configured database. The SQLAlchemy
dependency cost ~5 MB at install time for a single 7-line health
probe with no other consumer in the runtime — so we replaced it
with Django's ``connection.cursor()``. The CLI now bootstraps
Django on demand (mirrors the lazy pattern in
``ameli_app.workers.notify._ensure_django``) so ``ameli-app
db-status`` keeps working without a wrapping ``manage.py`` call.

The web-side caller (``ameli_web.dashboard.views._dashboard_payload``)
runs under a fully initialised Django stack — for that path
``_ensure_django`` is a no-op (``apps.ready`` returns ``True``).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .config import Settings


def _ensure_django() -> bool:
    """Bootstrap Django on demand. Returns True on success.

    Mirrors ``ameli_app.workers.notify._ensure_django`` so the CLI
    can hit the Django ORM without ``manage.py``. Idempotent —
    Django's own ``apps.ready`` flag short-circuits on subsequent
    calls inside the same process.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    project_root = Path(__file__).resolve().parents[2]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import django
    from django.apps import apps

    if apps.ready:
        return True
    try:
        django.setup()
        return True
    except Exception:  # pragma: no cover - boot failures depend on environment
        return False


def database_status(settings: Settings) -> dict[str, Any]:
    if not settings.database_url:
        return {
            "ok": True,
            "configured": False,
            "message": "DATABASE_URL is not configured; database checks skipped.",
        }

    if not _ensure_django():
        return {
            "ok": False,
            "configured": True,
            "message": "Django bootstrap failed; database check could not run.",
        }

    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        value = row[0] if row else None
        return {"ok": value == 1, "configured": True, "message": "Database reachable."}
    except Exception as exc:  # pragma: no cover - depends on external service
        return {
            "ok": False,
            "configured": True,
            "message": str(exc),
        }
