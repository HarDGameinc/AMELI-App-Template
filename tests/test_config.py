from dataclasses import replace

from ameli_app.config import load_settings, settings_summary
from ameli_web import settings as django_settings


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
    assert config["NAME"] == "ameli_app"
    assert config["USER"] == "user"
    assert config["PASSWORD"] == "pass"
    assert config["HOST"] == "127.0.0.1"
    assert config["PORT"] == "5432"
