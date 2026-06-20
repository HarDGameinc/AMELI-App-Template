"""Regression coverage for install.sh restarting running daemons.

2026-06-20 wire test on ha-report2 caught: ``install.sh`` called
``enable_selected_units`` (which uses ``systemctl enable --now``)
but NOT ``restart_selected_units``. ``--now`` starts STOPPED
units; it does NOT restart already-running daemons. So an
in-place upgrade left the api/notifier daemons on the old
Python bytecode — operators saw the new VERSION via CLI but
``/health`` reported the previous one.

These tests pin the contract by static analysis: install.sh
must call ``restart_selected_units`` AFTER
``enable_selected_units`` so the upgrade picks up new code.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "scripts" / "install.sh"


def _read() -> str:
    return INSTALL_SH.read_text()


def test_install_sh_calls_restart_after_enable():
    body = _read()
    enable_idx = body.find("enable_selected_units")
    restart_idx = body.find("restart_selected_units")
    assert enable_idx >= 0, "install.sh must call enable_selected_units"
    assert restart_idx >= 0, \
        "install.sh must call restart_selected_units after enable_selected_units; " \
        "without it, in-place upgrades leave daemons on old bytecode."
    # Ordering matters: enable first (so brand-new units are
    # started), then restart (so already-running ones pick up
    # new code).
    assert enable_idx < restart_idx, \
        "restart_selected_units must come AFTER enable_selected_units"


def test_install_sh_documents_why_restart_is_needed():
    """The comment in install.sh has to explicitly call out the
    "--now does not restart" trap so a future cleanup pass does
    not remove the restart call thinking it's redundant.
    """
    body = _read()
    assert "enable --now" in body, \
        "install.sh must document that --now only starts stopped units"
    assert "restart" in body
