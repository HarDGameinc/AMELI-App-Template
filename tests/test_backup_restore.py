"""Backup + restore-verify smoke tests.

We exercise the manifest + archive roundtrip without actually
touching the host file system (no /etc, no /var). The bash
scripts read most paths from ``_common.sh`` which derives them
from APP_SLUG/APP_ENV, so we can run them against scratch dirs
via env overrides.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SH = ROOT / "scripts" / "backup.sh"
RESTORE_SH = ROOT / "scripts" / "restore.sh"


@pytest.fixture()
def stage(tmp_path: Path) -> dict:
    """Build a fake ETC + DATA + BACKUP layout against a tmp_path so
    the bash scripts can run without root or system-level paths."""
    etc = tmp_path / "etc"
    data = tmp_path / "data"
    backup = tmp_path / "backup"
    app_dir = tmp_path / "app"
    for p in (etc, data, backup, app_dir):
        p.mkdir()
    (etc / "app.env").write_text("AMELI_APP_SECRET_KEY=test\n", encoding="utf-8")
    (data / "avatars" / ".keep").parent.mkdir()
    (data / "avatars" / ".keep").write_text("", encoding="utf-8")
    (data / "hello.bin").write_bytes(b"hello world")
    (app_dir / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    sqlite_path = data / "test.sqlite3"
    sqlite_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    return {
        "etc": etc,
        "data": data,
        "backup": backup,
        "app_dir": app_dir,
        "sqlite": sqlite_path,
        "instance": "ameli-app-template-test",
    }


def _run(script: Path, *args: str, env_extra: dict | None = None,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True, text=True, env=env, cwd=cwd,
    )


def _stage_env(stage: dict) -> dict:
    """Bypass _common.sh by exporting the same variable names it
    derives so the scripts skip the install layout detection."""
    return {
        "APP_INSTANCE": stage["instance"],
        "APP_DIR": str(stage["app_dir"]),
        "ETC_DIR": str(stage["etc"]),
        "DATA_DIR": str(stage["data"]),
        "LOG_DIR": str(stage["app_dir"]),
        "BACKUP_DIR": str(stage["backup"]),
        "RUN_USER": "nobody",
        "RUN_GROUP": "nobody",
        "AMELI_APP_SQLITE_PATH": str(stage["sqlite"]),
        "AMELI_APP_BACKUP_RETENTION_DAYS": "30",
    }


def test_backup_script_exists_and_is_executable():
    assert BACKUP_SH.is_file()
    assert os.access(BACKUP_SH, os.X_OK)


def test_restore_script_exists_and_is_executable():
    assert RESTORE_SH.is_file()
    assert os.access(RESTORE_SH, os.X_OK)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_backup_script_has_retention_block():
    text = BACKUP_SH.read_text(encoding="utf-8")
    assert "AMELI_APP_BACKUP_RETENTION_DAYS" in text
    assert "find" in text and "-mtime" in text
    # Retention pattern must be scoped to THIS instance only — a global
    # rm would wipe sibling deploys' backups.
    assert "${APP_INSTANCE}-" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_backup_script_supports_gpg_encryption():
    text = BACKUP_SH.read_text(encoding="utf-8")
    assert "AMELI_APP_BACKUP_GPG_RECIPIENT" in text
    assert "gpg --yes --batch --encrypt" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_restore_script_supports_verify_mode():
    text = RESTORE_SH.read_text(encoding="utf-8")
    assert "verify" in text
    assert "sha256sum --check" in text
    assert "--yes" in text  # destructive guard


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "restore.sh passes the archive to tar with a Windows drive-letter "
        "path (C:\\...), which GNU tar misreads as a remote host:path "
        "(`Cannot connect to C:`). POSIX-only; validated on the Linux CI."
    ),
)
def test_restore_verify_rejects_corrupted_manifest(stage, tmp_path):
    """Manually craft a fake archive with a mismatching checksum and
    confirm verify mode fails loudly."""
    import tarfile

    workdir = tmp_path / "fake"
    workdir.mkdir()
    (workdir / "etc").mkdir()
    (workdir / "data").mkdir()
    (workdir / "etc" / "app.env").write_text("real\n")
    (workdir / "data" / "ok.bin").write_bytes(b"ok")
    # Manifest lies about the contents.
    (workdir / "MANIFEST.sha256").write_text(
        "deadbeef0000deadbeef0000deadbeef0000deadbeef0000deadbeef00000000  ./etc/app.env\n",
        encoding="utf-8",
    )
    archive = tmp_path / "bogus.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(workdir, arcname=".")

    result = _run(
        RESTORE_SH, "verify", str(archive),
        env_extra=_stage_env(stage),
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "MANIFEST" in combined.upper() or "checksum" in combined.lower()


# ---------------------------------------------------------------------------
# Phase 2 #4 of 2026-06-20 roadmap — backup + restore ROUND TRIP test.
# Until now we tested backup.sh and restore.sh independently. This
# exercises the actual contract: a backup must be restorable AND the
# restore must reproduce the original state. SQLite path because
# Postgres CI services add another moving piece; the SQLite branch
# of backup.sh / restore.sh shares all the manifest + verify logic,
# so a round-trip there proves the contract is sound.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="backup.sh::require_root refuses non-root callers; CI runners are non-root by default",
)
def test_backup_restore_sqlite_round_trip(stage, tmp_path):
    """Plant a known row in SQLite → backup → wipe → restore →
    confirm the row is back. A backup that does not restore is
    not a backup; this is the only test that catches that.
    """
    import sqlite3

    # 1. Seed the staged SQLite with a known fixture row.
    sqlite_path = stage["sqlite"]
    sqlite_path.unlink()  # remove the placeholder bytes the fixture wrote
    conn = sqlite3.connect(str(sqlite_path))
    conn.executescript(
        "CREATE TABLE rt_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL); "
        "INSERT INTO rt_probe (id, value) VALUES (1, 'before-backup');"
    )
    conn.commit()
    conn.close()

    # 2. Run backup.sh; produces an archive in BACKUP_DIR.
    backup_result = _run(BACKUP_SH, env_extra=_stage_env(stage))
    assert backup_result.returncode == 0, (
        f"backup.sh failed: rc={backup_result.returncode}, "
        f"stderr={backup_result.stderr[-400:]!r}"
    )
    archives = list(stage["backup"].glob("*.tar.gz"))
    assert len(archives) == 1, f"expected exactly 1 archive, got {archives}"
    archive = archives[0]

    # 3. WIPE the live SQLite — restore.sh has to actually put it back.
    sqlite_path.unlink()
    assert not sqlite_path.exists()

    # 4. Run restore.sh restore --yes.
    restore_result = _run(
        RESTORE_SH, "restore", str(archive), "--yes",
        env_extra=_stage_env(stage),
    )
    assert restore_result.returncode == 0, (
        f"restore.sh failed: rc={restore_result.returncode}, "
        f"stderr={restore_result.stderr[-400:]!r}"
    )

    # 5. Verify the fixture row survived the round-trip.
    assert sqlite_path.exists(), "restore did not recreate the sqlite file"
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute("SELECT id, value FROM rt_probe").fetchall()
    finally:
        conn.close()
    assert rows == [(1, "before-backup")], (
        f"round-trip lost the seeded row; got: {rows!r}"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="backup.sh::require_root refuses non-root callers",
)
def test_backup_restore_round_trip_preserves_data_dir(stage, tmp_path):
    """Same contract but for the DATA_DIR side — user-uploaded
    media must survive the round-trip too. The ``stage`` fixture
    already seeds ``data/hello.bin``; wipe it after backup and
    confirm restore brings it back.
    """
    target = stage["data"] / "hello.bin"
    original_bytes = target.read_bytes()

    backup_result = _run(BACKUP_SH, env_extra=_stage_env(stage))
    assert backup_result.returncode == 0
    archive = next(stage["backup"].glob("*.tar.gz"))

    target.unlink()
    assert not target.exists()

    restore_result = _run(
        RESTORE_SH, "restore", str(archive), "--yes",
        env_extra=_stage_env(stage),
    )
    assert restore_result.returncode == 0

    assert target.exists(), "restore did not bring back data/hello.bin"
    assert target.read_bytes() == original_bytes


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_restore_script_strips_psycopg_url_suffix():
    """Mirror the backup.sh test — restore.sh must also strip the
    SQLAlchemy driver suffix before invoking pg_restore. Without
    it libpq silently falls back to socket + peer auth (same bug
    that PT-4 surfaced on 2026-06-19).
    """
    body = RESTORE_SH.read_text()
    assert "postgresql\\+" in body, \
        "restore.sh missing the driver-suffix sed for pg_restore URL"
