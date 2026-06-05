from __future__ import annotations

import argparse
from pathlib import Path

from ameli_app.cli import _autodetect_env_file, _effective_env_file


def _args(env_file: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(env_file=env_file)


def test_autodetect_returns_none_when_not_under_opt(monkeypatch, tmp_path):
    fake_python = tmp_path / "some" / "path" / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.touch()
    monkeypatch.setattr("sys.executable", str(fake_python))

    assert _autodetect_env_file() is None


def test_autodetect_returns_path_when_install_layout_matches(monkeypatch, tmp_path):
    opt_dir = tmp_path / "opt"
    install_dir = opt_dir / "ameli-app-template-dev"
    venv_bin = install_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").touch()

    etc_root = tmp_path / "etc"
    (etc_root / "ameli-app-template-dev").mkdir(parents=True)
    env_file = etc_root / "ameli-app-template-dev" / "app.env"
    env_file.write_text("AMELI_APP_DJANGO_SECRET_KEY=test\n")

    monkeypatch.setattr("sys.executable", str(venv_bin / "python"))

    assert _autodetect_env_file(etc_root=etc_root) == str(env_file)


def test_autodetect_returns_none_when_env_file_missing(monkeypatch, tmp_path):
    opt_dir = tmp_path / "opt"
    install_dir = opt_dir / "ameli-app-template-dev"
    venv_bin = install_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").touch()

    etc_root = tmp_path / "etc"
    etc_root.mkdir()

    monkeypatch.setattr("sys.executable", str(venv_bin / "python"))

    assert _autodetect_env_file(etc_root=etc_root) is None


def test_effective_env_file_prefers_cli_flag(monkeypatch):
    monkeypatch.setenv("AMELI_APP_ENV_FILE", "/etc/already/set/app.env")
    result = _effective_env_file(_args(env_file="/explicit/path.env"))
    assert result == "/explicit/path.env"


def test_effective_env_file_yields_to_existing_env_var(monkeypatch):
    monkeypatch.setenv("AMELI_APP_ENV_FILE", "/etc/already/set/app.env")
    # Returns None so load_settings picks up AMELI_APP_ENV_FILE itself.
    assert _effective_env_file(_args(env_file=None)) is None


def test_effective_env_file_returns_autodetected(monkeypatch):
    monkeypatch.delenv("AMELI_APP_ENV_FILE", raising=False)
    monkeypatch.setattr("ameli_app.cli._autodetect_env_file", lambda: "/etc/autodetected/app.env")

    assert _effective_env_file(_args(env_file=None)) == "/etc/autodetected/app.env"


def test_effective_env_file_returns_none_when_nothing_detected(monkeypatch):
    monkeypatch.delenv("AMELI_APP_ENV_FILE", raising=False)
    monkeypatch.setattr("ameli_app.cli._autodetect_env_file", lambda: None)

    assert _effective_env_file(_args(env_file=None)) is None
