"""Regression coverage for ASVS V3.4.4 — ``__Host-`` cookie prefix.

Closes roadmap item #12. The cookie name policy lives in
``src/ameli_web/settings.py``: when ``SESSION_COOKIE_SECURE`` is True
AND the operator has not overridden the name via env / YAML, the
default name becomes ``__Host-ameli_app_session`` (and
``__Host-ameli_csrf`` for the CSRF cookie). In dev the names stay
unprefixed so a plain-HTTP localhost session keeps working.

These tests pin every state-machine edge:

* Dev with default config → no prefix (so localhost HTTP works).
* Outside dev with default config → ``__Host-`` prefix on both
  session and CSRF cookie names.
* Operator override via ``AMELI_APP_SESSION_COOKIE_NAME`` wins
  (escape hatch for legacy bookmarks / reverse-proxy stripping).
* Boot guard refuses a ``__Host-`` name with Secure=False.
* Boot guard refuses a ``__Host-`` name combined with a Domain env
  override.
"""
from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, *, env: str = "dev", **env_vars: str | None):
    """Rebuild the Django settings module with the given env overrides.
    Mirrors the pattern from ``tests/test_settings_boot_guards.py``.
    """
    import sys

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
    if env != "dev" and "AMELI_APP_AUDIT_HMAC_KEY" not in env_vars:
        monkeypatch.setenv(
            "AMELI_APP_AUDIT_HMAC_KEY",
            "test-audit-hmac-key-for-prod-boot-guard-fixtures-only",
        )
    if env != "dev" and "AMELI_APP_PROFILE_UPLOADS_DIR" not in env_vars:
        # 2026-06-21 boot guard refuses MEDIA_ROOT inside the checkout.
        monkeypatch.setenv("AMELI_APP_PROFILE_UPLOADS_DIR", "/tmp/test-uploads")  # noqa: S108
    if env != "dev" and "AMELI_APP_DATA_DIR" not in env_vars:
        monkeypatch.setenv("AMELI_APP_DATA_DIR", "/tmp/test-data")  # noqa: S108
    if "ameli_web.settings" in sys.modules:
        del sys.modules["ameli_web.settings"]
    return importlib.import_module("ameli_web.settings")


# ---------------------------------------------------------------------------
# Dev path — no prefix
# ---------------------------------------------------------------------------

def test_dev_default_session_cookie_name_has_no_host_prefix(monkeypatch):
    """In dev the operator typically runs over plain HTTP. A
    ``__Host-``-prefixed cookie would be rejected by the browser for
    lack of the Secure flag, so the default stays unprefixed.
    """
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_NAME", raising=False)
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_DOMAIN", raising=False)
    settings = _reload_settings(monkeypatch, env="dev")
    assert settings.SESSION_COOKIE_NAME == "ameli_app_session"
    # In dev we keep Django's historic ``csrftoken`` default so any
    # existing client / test that hardcodes the name keeps working.
    assert settings.CSRF_COOKIE_NAME == "csrftoken"


# ---------------------------------------------------------------------------
# Prod path — __Host- prefix applied by default
# ---------------------------------------------------------------------------

def test_prod_default_session_cookie_name_carries_host_prefix(monkeypatch):
    """Outside dev the boot guards already force Secure=True and the
    Django default leaves Domain empty + Path=/. So ``__Host-`` is
    safe to apply by default — and the prefix turns the browser into
    a third party enforcing the three constraints.
    """
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_NAME", raising=False)
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_DOMAIN", raising=False)
    settings = _reload_settings(
        monkeypatch,
        env="prod",
        AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
        AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
        AMELI_APP_DJANGO_DEBUG="false",
        AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
        AMELI_APP_EMAIL_BACKEND="smtp",
        AMELI_APP_EMAIL_HOST="smtp.example.com",
    )
    assert settings.SESSION_COOKIE_NAME == "__Host-ameli_app_session"
    assert settings.CSRF_COOKIE_NAME == "__Host-ameli_csrf"
    assert settings.SESSION_COOKIE_SECURE is True


# ---------------------------------------------------------------------------
# Operator override wins (escape hatch)
# ---------------------------------------------------------------------------

def test_operator_session_cookie_name_override_wins(monkeypatch):
    """An operator behind a reverse proxy that strips ``__Host-`` (or
    that has legacy bookmarks pinned to a specific cookie name) needs
    to opt out. The existing ``AMELI_APP_SESSION_COOKIE_NAME`` env
    var is the escape hatch.
    """
    settings = _reload_settings(
        monkeypatch,
        env="prod",
        AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
        AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
        AMELI_APP_DJANGO_DEBUG="false",
        AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
        AMELI_APP_EMAIL_BACKEND="smtp",
        AMELI_APP_EMAIL_HOST="smtp.example.com",
        AMELI_APP_SESSION_COOKIE_NAME="legacy_session_cookie",
    )
    assert settings.SESSION_COOKIE_NAME == "legacy_session_cookie"


# ---------------------------------------------------------------------------
# Boot guards — refuse misconfigured __Host- combinations
# ---------------------------------------------------------------------------

def test_boot_guard_refuses_host_prefix_with_secure_false(monkeypatch):
    """If the operator overrides the cookie name with a ``__Host-``
    prefix but Secure is False, the browser will reject the cookie.
    Refuse to boot rather than ship a mysteriously-logged-out deploy.
    """
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_NAME starts with '__Host-'"):
        _reload_settings(
            monkeypatch,
            env="dev",  # dev defaults to Secure=False unless overridden
            AMELI_APP_SESSION_COOKIE_NAME="__Host-my_session",
            AMELI_APP_SESSION_COOKIE_SECURE="false",
        )


def test_boot_guard_refuses_host_prefix_with_domain(monkeypatch):
    """``__Host-`` requires Domain to be ABSENT. If the operator
    pinned a domain via env, refuse to boot.
    """
    with pytest.raises(RuntimeError, match="Domain"):
        _reload_settings(
            monkeypatch,
            env="prod",
            AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
            AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
            AMELI_APP_DJANGO_DEBUG="false",
            AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
            AMELI_APP_EMAIL_BACKEND="smtp",
            AMELI_APP_EMAIL_HOST="smtp.example.com",
            AMELI_APP_SESSION_COOKIE_NAME="__Host-ameli_app_session",
            AMELI_APP_SESSION_COOKIE_DOMAIN="example.com",
        )


# ---------------------------------------------------------------------------
# CSRF cookie mirror policy
# ---------------------------------------------------------------------------

def test_csrf_cookie_name_mirrors_secure_flag(monkeypatch):
    """The CSRF cookie carries the same browser-enforced contract
    (Secure + no Domain + Path=/), so the prefix policy is the same.
    """
    monkeypatch.delenv("AMELI_APP_SESSION_COOKIE_NAME", raising=False)
    settings_dev = _reload_settings(monkeypatch, env="dev")
    assert settings_dev.CSRF_COOKIE_NAME == "csrftoken"

    settings_prod = _reload_settings(
        monkeypatch,
        env="prod",
        AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
        AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
        AMELI_APP_DJANGO_DEBUG="false",
        AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
        AMELI_APP_EMAIL_BACKEND="smtp",
        AMELI_APP_EMAIL_HOST="smtp.example.com",
    )
    assert settings_prod.CSRF_COOKIE_NAME == "__Host-ameli_csrf"
