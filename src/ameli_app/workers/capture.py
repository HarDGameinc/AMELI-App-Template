"""Capture worker — extension point for child apps.

This module is INTENTIONALLY a placeholder. The template ships the
systemd scaffolding (``ameli-app-capture@.service`` + the
``@primary`` / ``@secondary`` timers in ``deploy/systemd/``) and a
``ameli-app worker-once`` CLI command that calls ``run_once`` here.
Child apps replace ``run_once`` with their own ingestion logic
(e.g. polling an external API, draining a queue, snapshotting a
data source). The placeholder returns a structured ack so a fresh
install can verify the wiring end-to-end before any real capture
code exists.

If your child app does not need a capture worker, leave this module
alone and disable the ``ameli-app-capture-*.timer`` units in your
install (they are off by default).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ameli_app.config import Settings


def run_once(settings: Settings) -> dict[str, Any]:
    return {
        "ok": True,
        "worker": "capture",
        "app": settings.app_slug,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Capture worker placeholder executed.",
    }
