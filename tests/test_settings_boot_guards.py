from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, *, env: str = "dev", **env_vars: str | None):
    """Rebuild the Django settings module with the given env overrides.

    The boot-time guards in ``ameli_web.settings`` raise during ``import``,
    so we need to wipe the cache and re-import every time a test wants to
    flip an env var.
    """
    import sys

    # Stage env exactly as the test expects.
    for key in list(env_vars):
        value = env_vars[key]
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", env)
    # ASVS V2.8 boot guard requires AMELI_APP_MFA_ENCRYPTION_KEY outside
    # dev. Tests that don't explicitly probe that guard get a default
    # so they exercise the OTHER guard they care about (email backend,
    # SECRET_KEY, ALLOWED_HOSTS, etc.) without colliding.
    if env != "dev" and "AMELI_APP_MFA_ENCRYPTION_KEY" not in env_vars:
        # Static value so the cached helper inside ``mfa.py`` does not
        # need re-instantiating between tests; a real Fernet key works
        # under cryptography.fernet without side effects on the test DB.
        monkeypatch.setenv(
            "AMELI_APP_MFA_ENCRYPTION_KEY",
            "kj9_Vh-rExdXrPm7TZWQ8a9oU8gPpYHN-mDz2LfqHy0=",
        )

    # Drop any cached settings module so the module-level guards re-run.
    for cached in ("ameli_web.settings",):
        sys.modules.pop(cached, None)
    return importlib.import_module("ameli_web.settings")


def test_dev_environment_boots_with_bundled_defaults(monkeypatch):
    settings = _reload_settings(monkeypatch, env="dev",
                                AMELI_APP_DJANGO_SECRET_KEY=None,
                                AMELI_APP_DJANGO_DEBUG=None,
                                AMELI_APP_DJANGO_ALLOWED_HOSTS=None)
    # Dev is allowed to fall back to the bundled defaults.
    assert settings.DEBUG is False  # default no longer follows env
    assert "*" in settings.ALLOWED_HOSTS


def test_non_dev_refuses_bundled_secret_key(monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY=None,
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="ameli.example.com")


def test_non_dev_refuses_wildcard_allowed_hosts(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="*")


def test_non_dev_refuses_empty_allowed_hosts(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS=None)


def test_non_dev_refuses_debug_true(monkeypatch):
    with pytest.raises(RuntimeError, match="DEBUG"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="ameli.example.com",
                         AMELI_APP_DJANGO_DEBUG="true",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1")


def test_non_dev_refuses_empty_trusted_proxies(monkeypatch):
    with pytest.raises(RuntimeError, match="TRUSTED_PROXIES"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES=None)


def test_non_dev_refuses_console_email_backend(monkeypatch):
    """Console backend keeps mail in stdout — password reset and
    MFA-by-email would silently fail in a real deploy. Refuse to boot."""
    with pytest.raises(RuntimeError, match="email.backend"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                         AMELI_APP_EMAIL_BACKEND="console")


def test_non_dev_refuses_smtp_backend_without_host(monkeypatch):
    """SMTP backend without a host silently no-ops too."""
    with pytest.raises(RuntimeError, match="email.host"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                         AMELI_APP_EMAIL_BACKEND="smtp")


def test_non_dev_boots_with_explicit_safe_config(monkeypatch):
    settings = _reload_settings(monkeypatch, env="prod",
                                AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                                AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan,10.0.0.5",
                                AMELI_APP_DJANGO_DEBUG="false",
                                AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                                AMELI_APP_EMAIL_BACKEND="smtp",
                                AMELI_APP_EMAIL_HOST="smtp.example.com")
    assert settings.SECRET_KEY != "ameli-app-dev-secret-key"
    assert settings.DEBUG is False
    assert "metro.lan" in settings.ALLOWED_HOSTS
    assert "10.0.0.5" in settings.ALLOWED_HOSTS
    assert settings.TRUSTED_PROXIES == {"127.0.0.1", "::1"}


def test_non_dev_refuses_empty_mfa_encryption_key(monkeypatch):
    """ASVS V2.8 boot guard — outside dev, the MFA encryption key
    must be set so TOTP secrets do not land in the DB as plaintext.
    """
    with pytest.raises(RuntimeError, match="AMELI_APP_MFA_ENCRYPTION_KEY"):
        _reload_settings(
            monkeypatch,
            env="prod",
            AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
            AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
            AMELI_APP_DJANGO_DEBUG="false",
            AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
            AMELI_APP_EMAIL_BACKEND="smtp",
            AMELI_APP_EMAIL_HOST="smtp.example.com",
            # Explicitly empty — must trip the guard.
            AMELI_APP_MFA_ENCRYPTION_KEY="",
        )


def test_dev_boots_without_mfa_encryption_key(monkeypatch):
    """Mirror property: in dev, the key is optional (pass-through mode)."""
    settings = _reload_settings(monkeypatch, env="dev")
    assert getattr(settings, "MFA_ENCRYPTION_KEY", "") == ""
