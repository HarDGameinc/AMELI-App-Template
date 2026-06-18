"""Regression coverage for ASVS V5.5.1 — safe serialization for the
Django messages framework.

Closes roadmap item #11. The guard lives in ``settings.py`` next to
the ``MESSAGE_STORAGE`` assignment: only the three first-party
Django storages (session / cookie / fallback, all signed-JSON-backed)
are accepted. Anything else — including a custom storage that uses
``pickle`` for serialization — refuses to boot with an
operator-actionable error.
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reload_settings(monkeypatch, *, env: str = "dev", **env_vars: str | None):
    """Rebuild the Django settings module with the given env overrides.
    Mirrors the helper from ``tests/test_settings_boot_guards.py``.
    """
    for key in list(env_vars):
        value = env_vars[key]
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", env)
    if env != "dev" and "AMELI_APP_MFA_ENCRYPTION_KEY" not in env_vars:
        monkeypatch.setenv(
            "AMELI_APP_MFA_ENCRYPTION_KEY",
            "kj9_Vh-rExdXrPm7TZWQ8a9oU8gPpYHN-mDz2LfqHy0=",
        )
    if "ameli_web.settings" in sys.modules:
        del sys.modules["ameli_web.settings"]
    return importlib.import_module("ameli_web.settings")


# ---------------------------------------------------------------------------
# Default + allow-list pass
# ---------------------------------------------------------------------------

def test_default_message_storage_is_session(monkeypatch):
    monkeypatch.delenv("AMELI_APP_MESSAGE_STORAGE", raising=False)
    settings = _reload_settings(monkeypatch, env="dev")
    assert settings.MESSAGE_STORAGE == "django.contrib.messages.storage.session.SessionStorage"


def test_cookie_storage_is_allowed(monkeypatch):
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_MESSAGE_STORAGE="django.contrib.messages.storage.cookie.CookieStorage",
    )
    assert settings.MESSAGE_STORAGE == "django.contrib.messages.storage.cookie.CookieStorage"


def test_fallback_storage_is_allowed(monkeypatch):
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_MESSAGE_STORAGE="django.contrib.messages.storage.fallback.FallbackStorage",
    )
    assert settings.MESSAGE_STORAGE == "django.contrib.messages.storage.fallback.FallbackStorage"


# ---------------------------------------------------------------------------
# Boot guard refuses unsafe storages
# ---------------------------------------------------------------------------

def test_boot_guard_refuses_arbitrary_storage(monkeypatch):
    """An operator-supplied class path that is NOT one of the three
    first-party signed-JSON storages refuses to boot. The error names
    the allow-list and the operator's value so the fix is single-screen.
    """
    with pytest.raises(RuntimeError, match="AMELI_APP_MESSAGE_STORAGE"):
        _reload_settings(
            monkeypatch, env="dev",
            AMELI_APP_MESSAGE_STORAGE="myapp.legacy.PickleMessageStorage",
        )


def test_boot_guard_error_names_allow_list(monkeypatch):
    """The error message must enumerate the safe options so the
    operator does not have to read the source to fix it.
    """
    with pytest.raises(RuntimeError, match="session.SessionStorage"):
        _reload_settings(
            monkeypatch, env="dev",
            AMELI_APP_MESSAGE_STORAGE="something.completely.different",
        )


def test_boot_guard_mentions_pickle_threat_model(monkeypatch):
    """ASVS V5.5.1 reason — the error should mention ``pickle`` /
    deserialisation so the operator understands WHY the guard exists,
    not just THAT it does.
    """
    with pytest.raises(RuntimeError, match="pickle"):
        _reload_settings(
            monkeypatch, env="dev",
            AMELI_APP_MESSAGE_STORAGE="myapp.legacy.PickleMessageStorage",
        )
