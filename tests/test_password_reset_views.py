from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"
NEW_PASSWORD = "BrandNewPass!12?"


@pytest.fixture(autouse=True)
def use_locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="viewer",
        password=USER_PASSWORD,
        role="public",
    )
    user = User.objects.get(username="viewer")
    user.email = "viewer@example.com"
    user.save(update_fields=["email"])
    return user


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- Login page link ----


@pytest.mark.django_db
def test_login_page_advertises_forgot_password_link(client):
    response = client.get("/login/")
    body = _body(response)

    assert response.status_code == 200
    assert "/login/forgot/" in body
    assert "Olvidaste tu contrasena" in body


# ---- Forgot password ----


@pytest.mark.django_db
def test_forgot_password_get_renders_form(client):
    response = client.get("/login/forgot/")
    body = _body(response)

    assert response.status_code == 200
    assert "Usuario o email" in body
    assert "Enviar enlace por email" in body


@pytest.mark.django_db
def test_forgot_password_post_with_valid_username_sends_email(client, public_user):
    mail.outbox.clear()

    response = client.post("/login/forgot/", {"identifier": "viewer"})
    body = _body(response)

    assert response.status_code == 200
    # Confirmation panel shown
    assert "te enviamos un enlace" in body
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["viewer@example.com"]


@pytest.mark.django_db
def test_forgot_password_post_with_unknown_user_returns_same_panel(client, public_user):
    mail.outbox.clear()

    response = client.post("/login/forgot/", {"identifier": "nobody"})
    body = _body(response)

    assert response.status_code == 200
    # Same confirmation message; no email actually sent
    assert "te enviamos un enlace" in body
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_forgot_password_post_with_empty_identifier_returns_error(client):
    response = client.post("/login/forgot/", {"identifier": "   "})
    body = _body(response)

    assert response.status_code == 400
    assert "Tipea tu usuario" in body


@pytest.mark.django_db
def test_forgot_password_bounces_authenticated_user_to_profile(client, public_user):
    client.force_login(public_user)

    response = client.get("/login/forgot/")

    assert response.status_code == 302
    assert response["Location"] == "/profile/"


# ---- Reset password ----


def _reset_url(user) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"/login/reset/{uidb64}/{token}/"


@pytest.mark.django_db
def test_reset_password_get_with_valid_token_renders_form(client, public_user):
    response = client.get(_reset_url(public_user))
    body = _body(response)

    assert response.status_code == 200
    assert "Define tu nueva contrasena" in body
    assert "@viewer" in body
    assert "Guardar nueva contrasena" in body


@pytest.mark.django_db
def test_reset_password_get_with_invalid_token_renders_error_state(client, public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    response = client.get(f"/login/reset/{uidb64}/bogus-token/")
    body = _body(response)

    assert response.status_code == 400
    assert "Enlace invalido o vencido" in body
    assert "Pedir un enlace nuevo" in body


@pytest.mark.django_db
def test_reset_password_post_with_valid_token_updates_password_and_redirects(client, public_user):
    response = client.post(
        _reset_url(public_user),
        {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
        follow=False,
    )

    assert response.status_code == 302
    assert response["Location"].endswith("/login/")
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.check_password(NEW_PASSWORD) is True
    assert refreshed.check_password(USER_PASSWORD) is False


@pytest.mark.django_db
def test_reset_password_post_with_mismatched_confirmation_returns_error(client, public_user):
    response = client.post(
        _reset_url(public_user),
        {"new_password": NEW_PASSWORD, "confirm_password": "Different!12?"},
    )
    body = _body(response)

    assert response.status_code == 400
    assert "no coincide" in body
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.check_password(USER_PASSWORD) is True


@pytest.mark.django_db
def test_reset_password_post_with_weak_password_returns_error(client, public_user):
    response = client.post(
        _reset_url(public_user),
        {"new_password": "short", "confirm_password": "short"},
    )

    assert response.status_code == 400
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.check_password(USER_PASSWORD) is True


@pytest.mark.django_db
def test_reset_password_token_cannot_be_reused(client, public_user):
    url = _reset_url(public_user)
    first = client.post(
        url, {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}, follow=False
    )
    assert first.status_code == 302

    # Same token, same URL, second attempt: 400 with the expired state
    second = client.get(url)
    body = _body(second)

    assert second.status_code == 400
    assert "Enlace invalido o vencido" in body


@pytest.mark.django_db
def test_reset_password_bounces_authenticated_user_to_profile(client, public_user):
    client.force_login(public_user)

    response = client.get(_reset_url(public_user))

    assert response.status_code == 302
    assert response["Location"] == "/profile/"
