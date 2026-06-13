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
