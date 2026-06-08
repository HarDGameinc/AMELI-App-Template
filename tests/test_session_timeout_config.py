from __future__ import annotations

import importlib

import pytest

from ameli_app.config import load_settings, settings_summary


def test_settings_summary_includes_session_age_and_idle(tmp_path, monkeypatch):
    monkeypatch.delenv("AMELI_APP_SESSION_IDLE_RENEWAL", raising=False)
    monkeypatch.delenv("AMELI_APP_SESSION_EXPIRE_AT_BROWSER_CLOSE", raising=False)

    settings = load_settings(config_path="config/app.yaml.example")
    summary = settings_summary(settings)

    assert "session_max_age_seconds" in summary
    assert "session_idle_renewal" in summary
    assert "session_expire_at_browser_close" in summary


def test_settings_default_idle_renewal_is_true(monkeypatch):
    monkeypatch.delenv("AMELI_APP_SESSION_IDLE_RENEWAL", raising=False)
    settings = load_settings(config_path="config/app.yaml.example")
    assert settings.session_idle_renewal is True


def test_settings_default_expire_at_browser_close_is_false(monkeypatch):
    monkeypatch.delenv("AMELI_APP_SESSION_EXPIRE_AT_BROWSER_CLOSE", raising=False)
    settings = load_settings(config_path="config/app.yaml.example")
    assert settings.session_expire_at_browser_close is False


@pytest.mark.parametrize("env_value,expected", [
    ("1", True), ("true", True), ("yes", True),
    ("0", False), ("false", False), ("no", False),
])
def test_settings_session_idle_renewal_env_override(monkeypatch, env_value, expected):
    monkeypatch.setenv("AMELI_APP_SESSION_IDLE_RENEWAL", env_value)
    settings = load_settings(config_path="config/app.yaml.example")
    assert settings.session_idle_renewal is expected


@pytest.mark.parametrize("env_value,expected", [
    ("1", True), ("0", False),
])
def test_settings_session_expire_at_browser_close_env_override(monkeypatch, env_value, expected):
    monkeypatch.setenv("AMELI_APP_SESSION_EXPIRE_AT_BROWSER_CLOSE", env_value)
    settings = load_settings(config_path="config/app.yaml.example")
    assert settings.session_expire_at_browser_close is expected


def test_django_settings_pick_up_session_options(monkeypatch):
    """Verify that django settings.py reflects the config values."""
    monkeypatch.setenv("AMELI_APP_SESSION_IDLE_RENEWAL", "true")
    monkeypatch.setenv("AMELI_APP_SESSION_EXPIRE_AT_BROWSER_CLOSE", "false")
    import ameli_web.settings as web_settings

    importlib.reload(web_settings)

    assert web_settings.SESSION_SAVE_EVERY_REQUEST is True
    assert web_settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
