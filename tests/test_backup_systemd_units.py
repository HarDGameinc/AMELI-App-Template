"""Regression coverage for roadmap item #18 — backup.timer +
backup.service shipped in the template.

Closes #18. Before: ``scripts/backup.sh`` existed but had no
systemd unit, so backup ran only when an operator invoked it by
hand. After: ``deploy/systemd/ameli-app-backup.{service,timer}``
ship in the template, ``_common.sh`` registers them in
``ALL_UNIT_SUFFIXES`` and appends the timer to every
``APP_SYSTEMD_PROFILE`` via ``ENABLED_TIMER_UNITS``. The repo
contract is static — these tests pin it without invoking
systemctl.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEMD_DIR = ROOT / "deploy" / "systemd"
COMMON_SH = ROOT / "scripts" / "_common.sh"


def _read(path: Path) -> str:
    return path.read_text()


# ---------------------------------------------------------------------------
# Unit files exist + carry the expected directives
# ---------------------------------------------------------------------------

def test_backup_service_exists():
    assert (SYSTEMD_DIR / "ameli-app-backup.service").is_file()


def test_backup_timer_exists():
    assert (SYSTEMD_DIR / "ameli-app-backup.timer").is_file()


def test_backup_service_runs_as_root():
    """``scripts/backup.sh:30`` calls ``require_root``. Running as
    ``__RUN_USER__`` (the app user, like every other unit) would
    fail. Pin User=root explicitly so a future refactor of the
    template's render loop does not silently put the unit back on
    the app user.
    """
    body = _read(SYSTEMD_DIR / "ameli-app-backup.service")
    assert "User=root" in body
    assert "Group=root" in body
    # And NOT the placeholder — that would mean a copy-paste from
    # ameli-app-maintenance.service that the sed render would
    # substitute to the app user.
    assert "__RUN_USER__" not in body


def test_backup_service_invokes_backup_sh():
    body = _read(SYSTEMD_DIR / "ameli-app-backup.service")
    assert "ExecStart=__APP_DIR__/scripts/backup.sh" in body


def test_backup_service_is_oneshot():
    body = _read(SYSTEMD_DIR / "ameli-app-backup.service")
    assert "Type=oneshot" in body


def test_backup_timer_schedule_is_daily():
    body = _read(SYSTEMD_DIR / "ameli-app-backup.timer")
    assert "OnCalendar=*-*-* 04:10:00" in body
    assert "Persistent=true" in body
    # RandomizedDelaySec spreads multi-instance hosts.
    assert "RandomizedDelaySec=" in body


def test_backup_timer_points_at_backup_service():
    body = _read(SYSTEMD_DIR / "ameli-app-backup.timer")
    assert "Unit=__UNIT_PREFIX__-backup.service" in body


def test_backup_timer_installs_into_timers_target():
    body = _read(SYSTEMD_DIR / "ameli-app-backup.timer")
    assert "WantedBy=timers.target" in body


# ---------------------------------------------------------------------------
# _common.sh — registration in the install pipeline
# ---------------------------------------------------------------------------

def test_backup_units_registered_in_all_unit_suffixes():
    """``disable_known_units`` iterates ``ALL_UNIT_SUFFIXES`` to
    clean up an old install. If backup.{service,timer} are not
    in the list, an uninstall leaves stray units behind.
    """
    body = _read(COMMON_SH)
    assert '"backup.service"' in body
    assert '"backup.timer"' in body


def test_every_profile_enables_backup_timer():
    """The backup is cross-cutting (every deploy needs it), so
    ``resolve_systemd_profile`` should append the backup timer
    to ``ENABLED_TIMER_UNITS`` for every profile. Pin via a
    single global ``+=`` after the case statement so future
    profile additions inherit the backup without per-branch
    edits.
    """
    body = _read(COMMON_SH)
    assert 'ENABLED_TIMER_UNITS+=("$(timer_unit_name backup)")' in body
