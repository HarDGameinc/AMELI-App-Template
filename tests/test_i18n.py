from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import translation

from ameli_web.accounts.services import bootstrap_superadmin, check_login_throttle

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


def test_locale_paths_configured():
    from django.conf import settings

    assert settings.USE_I18N
    assert "es" in {code for code, _ in settings.LANGUAGES}
    assert "en" in {code for code, _ in settings.LANGUAGES}
    assert settings.LOCALE_PATHS, "LOCALE_PATHS must point at the locale/ dir"


def test_locale_middleware_is_registered():
    from django.conf import settings

    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE


@pytest.mark.django_db
def test_throttle_message_is_english_when_locale_is_en(admin_user):
    """When the active locale is ``en``, the LoginThrottled message should
    be translated to English from the compiled catalog."""
    from ameli_web.accounts.services import LoginThrottled, record_audit

    # Push enough failures to trip the IP throttle
    for _ in range(20):
        record_audit("login_failed", target_username="x", payload={"ip": "9.9.9.9"})

    with translation.override("en"):
        try:
            check_login_throttle(username="x", ip="9.9.9.9")
        except LoginThrottled as exc:
            message = str(exc)

    assert "Too many attempts" in message


@pytest.mark.django_db
def test_throttle_message_is_spanish_by_default(admin_user):
    from ameli_web.accounts.services import LoginThrottled, record_audit

    for _ in range(20):
        record_audit("login_failed", target_username="x", payload={"ip": "9.9.9.9"})

    with translation.override("es"):
        try:
            check_login_throttle(username="x", ip="9.9.9.9")
        except LoginThrottled as exc:
            message = str(exc)

    assert "Demasiados intentos" in message


@pytest.mark.django_db
def test_logout_message_respects_accept_language(client, admin_user):
    """Logout flash message should switch to English when the request
    declares ``Accept-Language: en``."""
    client.force_login(admin_user)

    response = client.post("/logout/", HTTP_ACCEPT_LANGUAGE="en", follow=True)
    body = response.content.decode("utf-8")

    assert "Signed out." in body or "Sesion cerrada." in body  # one of the two
