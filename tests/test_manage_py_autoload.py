"""Regression coverage for roadmap item #20 — manage.py auto-loads
APP_CONFIG and the matching app.env.

Closes #20. Before: a wire test on ``ha-report2`` had to manually
``export APP_CONFIG=...`` and source ``app.env`` via an
IFS-safe shell loop because plain ``set -a; . app.env`` blows up
on shell metas in the values. After: ``python manage.py shell``
discovers ``/etc/<slug>/app.yaml`` and ``/etc/<slug>/app.env``
automatically and parses the env file in Python (no bash IFS
gotcha).

These tests exercise the discovery + parsing helpers directly so
they do not depend on Django being imported. The integration
contract — "running manage.py picks up APP_CONFIG" — is covered
by the wire test recorded in the day's handoff.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Make ``manage`` importable as a module without invoking ``main()``.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
manage = importlib.import_module("manage")


# ---------------------------------------------------------------------------
# _project_slug
# ---------------------------------------------------------------------------

def test_project_slug_reads_pyproject_name():
    assert manage._project_slug(ROOT) == "ameli-app-template"


def test_project_slug_falls_back_to_dirname_when_pyproject_missing(tmp_path):
    # Empty dir with no pyproject — slug = dir name.
    assert manage._project_slug(tmp_path) == tmp_path.name


def test_project_slug_falls_back_when_pyproject_invalid(tmp_path):
    (tmp_path / "pyproject.toml").write_text("not = valid = toml = here")
    assert manage._project_slug(tmp_path) == tmp_path.name


# ---------------------------------------------------------------------------
# _load_env_file_safe — the bash IFS gotcha exists ONLY in bash; Python
# splits the line literally and never re-evaluates. The tests pin that.
# ---------------------------------------------------------------------------

def test_load_env_file_safe_parses_basic_key_value(tmp_path, monkeypatch):
    env = tmp_path / "app.env"
    env.write_text("FOO=bar\nBAZ=qux\n")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    manage._load_env_file_safe(env)
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_env_file_safe_preserves_trailing_equals(tmp_path, monkeypatch):
    """A Fernet key ends in ``=`` (base64 padding). ``IFS='='; read``
    would silently eat it; the Python split-on-first-equals never does.
    """
    env = tmp_path / "app.env"
    env.write_text("MFA_KEY=vPSzwzxSheDNfkfLHj3GgA1d9g2V4y1AKDjkA332zmw=\n")
    monkeypatch.delenv("MFA_KEY", raising=False)
    manage._load_env_file_safe(env)
    assert os.environ["MFA_KEY"] == "vPSzwzxSheDNfkfLHj3GgA1d9g2V4y1AKDjkA332zmw="


def test_load_env_file_safe_handles_shell_metachars(tmp_path, monkeypatch):
    """``set -a; . app.env`` re-evaluates ``(`` / ``)`` / ``!``. Python
    parser does not — this test pins that the loader survives a real
    secret containing those characters.
    """
    env = tmp_path / "app.env"
    env.write_text("SECRET=mzlZ!fF)WqLxlez+sP@H!lW0iEDBV#D8Bx3b8y@XtC@VT5O4s4A)&krGb3LrrA+j\n")
    monkeypatch.delenv("SECRET", raising=False)
    manage._load_env_file_safe(env)
    assert os.environ["SECRET"] == "mzlZ!fF)WqLxlez+sP@H!lW0iEDBV#D8Bx3b8y@XtC@VT5O4s4A)&krGb3LrrA+j"


def test_load_env_file_safe_skips_comments_and_blank_lines(tmp_path, monkeypatch):
    env = tmp_path / "app.env"
    env.write_text("# a comment\n\nFOO=bar\n# another\nBAZ=qux\n")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    manage._load_env_file_safe(env)
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_env_file_safe_strips_outer_matching_quotes(tmp_path, monkeypatch):
    env = tmp_path / "app.env"
    env.write_text('FOO="bar"\nBAZ=\'qux\'\nMIXED="not\'paired\n')
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    monkeypatch.delenv("MIXED", raising=False)
    manage._load_env_file_safe(env)
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"
    # Mismatched quotes are left literal — explicit beats clever.
    assert os.environ["MIXED"] == '"not\'paired'


def test_load_env_file_safe_does_not_override_existing_env(tmp_path, monkeypatch):
    env = tmp_path / "app.env"
    env.write_text("FOO=from_file\n")
    monkeypatch.setenv("FOO", "from_env")
    manage._load_env_file_safe(env)
    assert os.environ["FOO"] == "from_env"


def test_load_env_file_safe_is_silent_when_file_missing(tmp_path):
    # Should not raise.
    manage._load_env_file_safe(tmp_path / "does-not-exist.env")


# ---------------------------------------------------------------------------
# _autodetect_app_config
# ---------------------------------------------------------------------------

def test_autodetect_respects_explicit_app_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "/explicit/path/app.yaml")
    monkeypatch.delenv("AMELI_APP_CONFIG", raising=False)
    manage._autodetect_app_config(tmp_path)
    assert os.environ["APP_CONFIG"] == "/explicit/path/app.yaml"


def test_autodetect_uses_project_root_config_yaml_example_as_fallback(tmp_path, monkeypatch):
    """Fresh clone with only ``config/app.yaml.example`` — that file
    should be picked so the suite boots without setup.
    """
    monkeypatch.delenv("APP_CONFIG", raising=False)
    monkeypatch.delenv("AMELI_APP_CONFIG", raising=False)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "app.yaml.example").write_text("app: {}\n")
    # No pyproject — slug falls back to tmp_path.name, /etc/<that>/app.yaml
    # does not exist, so the loader falls through to config/.
    manage._autodetect_app_config(tmp_path)
    assert os.environ["APP_CONFIG"].endswith("app.yaml.example")


def test_autodetect_prefers_config_yaml_over_example(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_CONFIG", raising=False)
    monkeypatch.delenv("AMELI_APP_CONFIG", raising=False)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "app.yaml.example").write_text("app: {}\n")
    (cfg_dir / "app.yaml").write_text("app: {}\n")
    manage._autodetect_app_config(tmp_path)
    assert os.environ["APP_CONFIG"].endswith("/config/app.yaml")


def test_autodetect_loads_env_file_alongside_config(tmp_path, monkeypatch):
    """When APP_CONFIG is set explicitly to /etc/.../app.yaml, the
    matching app.env in the same dir should also be loaded — that's
    the actual wire-test flow on ha-report2.
    """
    etc = tmp_path / "etc"
    etc.mkdir()
    cfg = etc / "app.yaml"
    cfg.write_text("app: {}\n")
    env = etc / "app.env"
    env.write_text("AUTODETECT_PROBE=picked_up\n")
    monkeypatch.setenv("APP_CONFIG", str(cfg))
    monkeypatch.delenv("AMELI_APP_CONFIG", raising=False)
    monkeypatch.delenv("AUTODETECT_PROBE", raising=False)
    manage._autodetect_app_config(tmp_path)
    assert os.environ["AUTODETECT_PROBE"] == "picked_up"


# ---------------------------------------------------------------------------
# End-to-end smoke — sentinel-cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_autodetect_probe(monkeypatch):
    monkeypatch.delenv("AUTODETECT_PROBE", raising=False)
    yield
