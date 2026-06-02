from ameli_app.config import load_settings, settings_summary


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
    assert summary["session_cookie_name"] == "ameli_app_session"
