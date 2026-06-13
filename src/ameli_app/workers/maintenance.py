from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ameli_app.config import Settings


def _ensure_django() -> bool:
    """Bootstrap Django on demand.

    Mirrors the lazy bootstrap in ``ameli_app.workers.notify`` so the
    maintenance tick can run from the CLI without a wrapping
    ``manage.py`` invocation.
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
    except Exception:  # noqa: BLE001
        return False
    return True


def _run_retention(settings: Settings) -> dict[str, Any]:
    if not _ensure_django():
        return {"ok": False, "error": "django setup failed"}
    from ameli_web.accounts.services import run_retention_sweep

    audit_max = getattr(settings, "audit_retention_max_age_days", None)
    return run_retention_sweep(
        audit_max_age_days=audit_max if isinstance(audit_max, int) else None,
    )


def run_once(settings: Settings) -> dict[str, Any]:
    retention = _run_retention(settings)
    return {
        "ok": bool(retention.get("ok", False)),
        "worker": "maintenance",
        "app": settings.app_slug,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
        "retention": retention,
    }
