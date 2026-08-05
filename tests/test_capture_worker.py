"""Upstream finding T-4 (2026-08-04): the capture worker ships instanced
timers (``@primary`` / ``@secondary``) differentiated only by
``AMELI_APP_CAPTURE_MODE=%i``, but ``run_once`` never read it — so a fork
that enables both processes the whole fleet twice.

Cheap latch against re-divergence: if the instanced units ship,
``capture.py`` must reference the env var.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYSTEMD = ROOT / "deploy" / "systemd"
CAPTURE = ROOT / "src" / "ameli_app" / "workers" / "capture.py"


def test_capture_reads_mode_when_instanced_timers_ship():
    instanced = (
        list(SYSTEMD.glob("*capture@*.service"))
        + list(SYSTEMD.glob("*capture-primary.timer"))
        + list(SYSTEMD.glob("*capture-secondary.timer"))
    )
    if not instanced:
        pytest.skip("no instanced capture timers ship")
    body = CAPTURE.read_text(encoding="utf-8")
    assert "AMELI_APP_CAPTURE_MODE" in body, (
        "the @primary/@secondary units set AMELI_APP_CAPTURE_MODE; run_once "
        "must read it or the fleet is processed twice (T-4)"
    )


def test_run_once_surfaces_capture_mode(monkeypatch):
    from types import SimpleNamespace

    from ameli_app.workers.capture import run_once

    monkeypatch.setenv("AMELI_APP_CAPTURE_MODE", "primary")
    ack = run_once(SimpleNamespace(app_slug="x", environment="dev"))
    assert ack["capture_mode"] == "primary"

    monkeypatch.delenv("AMELI_APP_CAPTURE_MODE", raising=False)
    ack = run_once(SimpleNamespace(app_slug="x", environment="dev"))
    assert ack["capture_mode"] is None
