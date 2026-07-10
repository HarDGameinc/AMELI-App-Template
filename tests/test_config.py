from dataclasses import replace

import pytest

from ameli_app.config import load_settings, settings_summary
from ameli_web import settings as django_settings


def test_load_settings_requires_explicit_environment(tmp_path, monkeypatch):
    """M1 fail-closed: a config that omits ``app.environment`` with ``APP_ENV``
    unset must REFUSE to boot rather than silently defaulting to 'dev' — the
    old default disabled every production hardening guard on a forgotten env."""
    monkeypatch.delenv("APP_ENV", raising=False)
    cfg = tmp_path / "app.yaml"
    cfg.write_text("app:\n  name: Test\n  slug: test\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No environment declared"):
        load_settings(config_path=str(cfg))


def test_load_settings_honors_explicit_environment(tmp_path, monkeypatch):
    """The same config with an explicit ``app.environment`` boots normally."""
    monkeypatch.delenv("APP_ENV", raising=False)
    cfg = tmp_path / "app.yaml"
    cfg.write_text("app:\n  name: Test\n  slug: test\n  environment: dev\n", encoding="utf-8")
    assert load_settings(config_path=str(cfg)).environment == "dev"


def test_load_settings_environment_from_app_env_var(tmp_path, monkeypatch):
    """APP_ENV alone (config omits it) is a valid explicit declaration."""
    monkeypatch.setenv("APP_ENV", "prod")
    cfg = tmp_path / "app.yaml"
    cfg.write_text("app:\n  name: Test\n  slug: test\n", encoding="utf-8")
    assert load_settings(config_path=str(cfg)).environment == "prod"


def test_load_settings_from_example(config_path):
    settings = load_settings(config_path=config_path)

    assert settings.app_name == "AMELI App Template"
    assert settings.app_slug == "ameli-app"
    assert settings.environment == "dev"
    assert settings.api_port == 18080
    assert settings.auth_enabled is True
    assert settings.docs_enabled is True
    assert settings.admin_enabled is True


def test_settings_summary_does_not_expose_token(app_settings):
    summary = settings_summary(app_settings)

    assert summary["app_slug"] == "ameli-app"
    assert "api_token" not in summary
    # ``session_cookie_name`` defaults to empty so ``settings.py`` can
    # apply the ASVS V3.4.4 ``__Host-`` prefix policy outside dev.
    # See ``src/ameli_app/config.py:206``.
    assert summary["session_cookie_name"] == ""


def test_django_database_settings_accepts_sqlalchemy_postgres_scheme(monkeypatch):
    monkeypatch.setattr(
        django_settings,
        "CFG",
        replace(django_settings.CFG, database_url="postgresql+psycopg://user:pass@127.0.0.1:5432/ameli_app"),
    )

    config = django_settings._database_settings()

    assert config["ENGINE"] == "django.db.backends.postgresql"


# ---------------------------------------------------------------------------
# Mini-roadmap #11 — Postgres connection pool tuning (2026-06-22)
# ---------------------------------------------------------------------------


def _set_pg_dsn(monkeypatch):
    monkeypatch.setattr(
        django_settings,
        "CFG",
        replace(
            django_settings.CFG,
            database_url="postgresql://user:pass@127.0.0.1:5432/ameli_app",
        ),
    )


def test_postgres_defaults_set_persistent_connections(monkeypatch):
    """Default Django behaviour opens a fresh connection per request,
    which at any concurrency starts to dominate latency on a busy
    deploy. Persistent connections (``CONN_MAX_AGE``) + health
    probes (``CONN_HEALTH_CHECKS``) are the cheap wins this commit
    delivers without any operator action."""
    _set_pg_dsn(monkeypatch)
    monkeypatch.delenv("AMELI_APP_DB_CONN_MAX_AGE_SECONDS", raising=False)
    config = django_settings._database_settings()
    assert config["CONN_MAX_AGE"] == 60
    assert config["CONN_HEALTH_CHECKS"] is True


def test_postgres_conn_max_age_honors_env_override(monkeypatch):
    _set_pg_dsn(monkeypatch)
    monkeypatch.setenv("AMELI_APP_DB_CONN_MAX_AGE_SECONDS", "300")
    config = django_settings._database_settings()
    assert config["CONN_MAX_AGE"] == 300


def test_postgres_conn_max_age_invalid_value_falls_back_to_default(monkeypatch):
    """A typo or empty value MUST NOT crash the boot — we degrade to
    the documented default (60 s) instead."""
    _set_pg_dsn(monkeypatch)
    monkeypatch.setenv("AMELI_APP_DB_CONN_MAX_AGE_SECONDS", "abc")
    config = django_settings._database_settings()
    assert config["CONN_MAX_AGE"] == 60


def test_sqlite_does_not_carry_pool_settings(monkeypatch):
    """SQLite uses a single-process file lock — connection pooling
    is meaningless and applying ``CONN_MAX_AGE`` would be a no-op
    that just confuses the operator reading settings.py."""
    monkeypatch.setattr(
        django_settings, "CFG",
        replace(django_settings.CFG, database_url=""),
    )
    config = django_settings._database_settings()
    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert "CONN_MAX_AGE" not in config
    assert "CONN_HEALTH_CHECKS" not in config


def test_postgres_pool_not_wired_when_env_unset(monkeypatch):
    """Pool sizing is OPT-IN: without the env vars, no ``OPTIONS["pool"]``
    is emitted and Django stays on its per-connection model."""
    _set_pg_dsn(monkeypatch)
    monkeypatch.delenv("AMELI_APP_DB_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("AMELI_APP_DB_POOL_MAX_SIZE", raising=False)
    config = django_settings._database_settings()
    assert "OPTIONS" not in config


def test_postgres_pool_wires_options_when_env_set(monkeypatch):
    """When the operator sets pool sizing env vars, the resulting
    DATABASES entry MUST carry ``OPTIONS["pool"]`` so Django hands
    the dict to psycopg3 at connection time."""
    _set_pg_dsn(monkeypatch)
    monkeypatch.setenv("AMELI_APP_DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("AMELI_APP_DB_POOL_MAX_SIZE", "10")
    config = django_settings._database_settings()
    assert config["OPTIONS"]["pool"] == {"min_size": 2, "max_size": 10}


def test_postgres_pool_only_min_size(monkeypatch):
    """Operator may pin only min_size (let psycopg pick max). The
    resulting dict must still be valid for psycopg_pool."""
    _set_pg_dsn(monkeypatch)
    monkeypatch.setenv("AMELI_APP_DB_POOL_MIN_SIZE", "4")
    monkeypatch.delenv("AMELI_APP_DB_POOL_MAX_SIZE", raising=False)
    config = django_settings._database_settings()
    assert config["OPTIONS"]["pool"] == {"min_size": 4}
    assert config["NAME"] == "ameli_app"
    assert config["USER"] == "user"
    assert config["PASSWORD"] == "pass"
    assert config["HOST"] == "127.0.0.1"
    assert config["PORT"] == "5432"
