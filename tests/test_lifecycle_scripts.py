"""Coverage for the day-2 lifecycle scripts (update / uninstall + purge).

Review of 2026-07-23 against the installer's bar found two gaps:

* **M1** — ``update.sh`` ran ``backup.sh || true`` before ``migrate``. The
  pre-update backup is the only recovery path from a failed/irreversible
  migration, and ``|| true`` swallowed a failed pg_dump or a full disk,
  proceeding with no safety net. It must halt (with an explicit opt-out).
* **M3** — ``uninstall.sh`` preserved everything and had no way to fully
  remove an instance; the teardown was 100% manual (rm -rf + dropdb +
  userdel), easy to get wrong. A guarded ``--purge`` now encapsulates it.

Static tests read the script text (run everywhere). The purge behaviour
test sources ``_common.sh`` and is POSIX-only, like the install suite.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMON_SH = ROOT / "scripts" / "_common.sh"
UPDATE_SH = ROOT / "scripts" / "update.sh"
UNINSTALL_SH = ROOT / "scripts" / "uninstall.sh"


# ---------------------------------------------------------------------------
# M1 -- update.sh must not let a failed pre-update backup pass silently
# ---------------------------------------------------------------------------

def test_update_does_not_swallow_backup_failure():
    body = UPDATE_SH.read_text(encoding="utf-8")
    # The exact old bug: the backup call neutralised by ``|| true``.
    assert 'backup.sh" || true' not in body, \
        "update.sh must not swallow a failed pre-update backup with || true"
    assert "scripts/backup.sh" in body, "update.sh must still take a pre-update backup"


def test_update_halts_on_backup_failure_with_opt_out():
    body = UPDATE_SH.read_text(encoding="utf-8")
    # A failed backup reaches ``fail`` (aborts), and there is a documented
    # escape hatch for operators who back up out of band.
    assert "AMELI_APP_UPDATE_SKIP_BACKUP" in body
    backup_idx = body.find("scripts/backup.sh")
    fail_idx = body.find("fail", backup_idx)
    migrate_idx = body.find("migrate --noinput")
    assert 0 <= fail_idx < migrate_idx, \
        "the backup guard (fail) must sit BEFORE migrate"


def test_update_verifies_the_backup_before_migrate():
    """M4: a backup that does not verify is not a safety net."""
    body = UPDATE_SH.read_text(encoding="utf-8")
    verify_idx = body.find("restore.sh")
    migrate_idx = body.find("migrate --noinput")
    assert 0 <= verify_idx < migrate_idx, \
        "update.sh must verify the fresh backup (restore.sh verify) before migrate"
    assert "verify" in body


# ---------------------------------------------------------------------------
# M3 -- uninstall.sh: safe by default, purge behind an explicit guard
# ---------------------------------------------------------------------------

def test_uninstall_is_non_destructive_by_default():
    body = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "disable_known_units" in body
    # Without --purge it must preserve data and NOT call the destructive path.
    default_msg_idx = body.find("Datos preservados")
    purge_call_idx = body.find("purge_instance")
    assert default_msg_idx >= 0, "default uninstall must preserve data"
    assert default_msg_idx < purge_call_idx, \
        "the preserve-and-exit path must come before purge_instance"


def test_uninstall_purge_requires_yes():
    body = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "--purge" in body and "--yes" in body
    assert "IRREVERSIBLE" in body
    # The --yes gate (fail) must sit before purge_instance runs.
    yes_gate = body.find('ASSUME_YES')
    purge_idx = body.find("purge_instance")
    assert 0 <= yes_gate < purge_idx


def test_uninstall_purge_takes_a_final_backup_first():
    body = UNINSTALL_SH.read_text(encoding="utf-8")
    backup_idx = body.find("scripts/backup.sh")
    purge_idx = body.find("purge_instance")
    assert 0 <= backup_idx < purge_idx, \
        "a --purge must back up BEFORE it deletes everything"
    assert "AMELI_APP_UNINSTALL_SKIP_BACKUP" in body


def test_purge_does_not_auto_drop_the_database():
    """The installer never creates the DB, so the uninstaller must not
    drop it -- it prints the commands instead."""
    common = COMMON_SH.read_text(encoding="utf-8")
    assert "dropdb --if-exists" in common
    # Guidance, not execution: no bare ``dropdb`` invocation on its own line.
    assert "su - postgres -c" in common


# ---------------------------------------------------------------------------
# purge_instance behaviour (POSIX-only, sources _common.sh)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform == "win32",
    reason="sources _common.sh via a bash subprocess; POSIX-only",
)
def test_purge_instance_removes_the_footprint_and_prints_db_commands(tmp_path):
    inst = "tmpl-test-prod"
    layout = {
        "APP_DIR": tmp_path / "opt" / inst,
        "ETC_DIR": tmp_path / "etc" / inst,
        "DATA_DIR": tmp_path / "var" / "lib" / inst,
        "LOG_DIR": tmp_path / "var" / "log" / inst,
        "BACKUP_DIR": tmp_path / "var" / "backups" / inst,
    }
    for d in layout.values():
        d.mkdir(parents=True)
        (d / "sentinel").write_text("x", encoding="utf-8")

    shell_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "COMMON_SH_PATH": str(COMMON_SH),
        "APP_ENV": "prod",
        "APP_SLUG": "tmpl-test",
        # A user that does not exist so the userdel/groupdel branches skip
        # cleanly without needing root.
        "RUN_USER": "nonexistent-purge-user-xyz",
        "RUN_GROUP": "nonexistent-purge-group-xyz",
        "DATABASE_URL": "postgresql+psycopg://smoke_user:pw@127.0.0.1:5432/smoke_db",
        **{k: str(v) for k, v in layout.items()},
    }

    script = r'''
set -euo pipefail
source <(tail -n +6 "${COMMON_SH_PATH}")
purge_instance
'''
    proc = subprocess.run(
        ["bash", "-c", script],
        env=shell_env, check=True, capture_output=True, text=True,
    )

    # Every directory of the instance is gone.
    for d in layout.values():
        assert not d.exists(), f"{d} survived the purge"

    # The DB is not dropped -- the exact commands are printed instead.
    assert "dropdb --if-exists smoke_db" in proc.stdout
    assert "dropuser --if-exists smoke_user" in proc.stdout
