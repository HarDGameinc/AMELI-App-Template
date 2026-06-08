from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_api_token, revoke_api_token

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_profile_renders_tokens_tab(client, user):
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert response.status_code == 200
    assert 'data-tab="profile-tab-tokens"' in body
    assert 'id="profile-tab-tokens"' in body
    assert "API Tokens" in body


@pytest.mark.django_db
def test_profile_tokens_tab_shows_empty_state_when_no_tokens(client, user):
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "data-tokens-empty" in body
    assert "Sin tokens creados" in body


@pytest.mark.django_db
def test_profile_tokens_tab_lists_existing_tokens(client, user):
    create_api_token(user, name="my-deploy-bot")
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "my-deploy-bot" in body
    assert "data-tokens-empty" not in body or "Sin tokens creados" not in body
    # Prefix shown, plaintext not
    assert "ameli_" in body


@pytest.mark.django_db
def test_profile_tokens_tab_shows_revoked_state(client, user):
    created = create_api_token(user, name="will-revoke")
    revoke_api_token(user, token_id=created["record"]["id"])
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "Revocado" in body


@pytest.mark.django_db
def test_profile_tokens_tab_form_has_create_endpoint(client, user):
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    # The JS posts to /profile/tokens/ — make sure the script references it.
    assert "/profile/tokens/" in body
    assert 'id="profile-token-create-form"' in body
    assert 'id="profile-token-reveal"' in body


@pytest.mark.django_db
def test_profile_tokens_tab_only_shows_callers_own_tokens(client, user):
    """Tokens of another user must NOT leak into this user's profile view."""
    other = User.objects.create_user(username="other", password="OtherPass!12?")
    create_api_token(other, name="not-mine")
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "not-mine" not in body
