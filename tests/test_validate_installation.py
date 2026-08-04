"""Coverage for scripts/validate_installation.sh acceptance checks.

Upstream finding T-6 (2026-08-04): an empty ``DATABASE_URL`` outside dev
silently falls back to SQLite — ``db-status`` still exits 0 (reporting
``configured: false``), ``/health`` returns 200, and production ships on a
throwaway file DB unnoticed. It cost a child fork ~2h with prod on SQLite.
The validator must FAIL loudly on that state, not report ``[OK]``.

Static analysis (reads the script text) — like test_install_sh_restart.py,
so it runs on every platform including win32.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATE_SH = (ROOT / "scripts" / "validate_installation.sh").read_text(encoding="utf-8")


def test_validate_fails_on_empty_database_url_outside_dev():
    # Must gate on both the environment and an empty DATABASE_URL, and
    # route to fail_check (a FAIL), not pass.
    assert '${APP_ENV}" != "dev"' in VALIDATE_SH
    assert '-z "${DATABASE_URL:-}"' in VALIDATE_SH
    # The check must reach fail_check with the DATABASE_URL_EMPTY label.
    empty_idx = VALIDATE_SH.find('DATABASE_URL:-}"')
    assert empty_idx >= 0
    window = VALIDATE_SH[empty_idx:empty_idx + 400]
    assert "fail_check" in window, "empty prod DATABASE_URL must be a FAIL"
    assert "DATABASE_URL_EMPTY" in window


def test_validate_still_runs_the_db_status_command():
    # The new guard complements, not replaces, the existing db-status probe.
    assert "DB_STATUS_COMMAND" in VALIDATE_SH


def test_validate_db_url_guard_does_not_fire_in_dev():
    # The SQLite fallback is a legitimate dev convenience — the guard is
    # explicitly scoped to non-dev.
    empty_idx = VALIDATE_SH.find('DATABASE_URL:-}"')
    window = VALIDATE_SH[max(0, empty_idx - 200):empty_idx]
    assert '"dev"' in window, "the DATABASE_URL guard must be scoped to non-dev"
