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

**Partitioning contract (``AMELI_APP_CAPTURE_MODE``).** The template
ships a PAIR of instanced timers — ``…-capture@primary.timer`` and
``…-capture@secondary.timer`` — that run this same worker on staggered
schedules, told apart only by ``Environment=AMELI_APP_CAPTURE_MODE=%i``
(``"primary"`` / ``"secondary"``). That env var is HALF a fleet-split
mechanism; the OTHER half is yours: **a real ``run_once`` that enables
both timers MUST read ``AMELI_APP_CAPTURE_MODE`` and process only its
partition.** If it ignores the mode, the full fleet is processed TWICE by
two overlapping cycles (duplicate work against the target APIs, and — for
apps that alert — duplicate notifications). systemd does not prevent it:
``@primary`` and ``@secondary`` are DISTINCT units, so the "don't start an
already-active oneshot" guard never applies between them. If you don't
partition, enable only ONE timer. (Upstream finding T-4.)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from ameli_app.config import Settings


def run_once(settings: Settings) -> dict[str, Any]:
    # Read the partition even though the placeholder does no real work, so
    # a fork that copies this exemplar inherits the read (and surfaces the
    # mode in the ack) instead of silently ignoring it. See the module
    # docstring for the contract a real run_once must honour.
    capture_mode = os.environ.get("AMELI_APP_CAPTURE_MODE", "")
    return {
        "ok": True,
        "worker": "capture",
        "app": settings.app_slug,
        "environment": settings.environment,
        "capture_mode": capture_mode or None,
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Capture worker placeholder executed.",
    }
