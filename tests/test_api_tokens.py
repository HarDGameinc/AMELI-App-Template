from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import ApiToken
from ameli_web.accounts.services import (
    API_TOKEN_PREFIX,
    authenticate_api_token,
    bootstrap_superadmin,
    create_api_token,
    list_api_tokens,
    revoke_api_token,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


# ---- service layer ----


@pytest.mark.django_db
def test_create_api_token_returns_plaintext_once(user):
    result = create_api_token(user, name="deploy bot")

    assert result["ok"] is True
    assert result["token"].startswith(API_TOKEN_PREFIX)
    assert len(result["token"]) > len(API_TOKEN_PREFIX) + 20
    assert result["record"]["name"] == "deploy bot"
    assert result["record"]["token_prefix"].startswith(API_TOKEN_PREFIX)


@pytest.mark.django_db
def test_create_api_token_does_not_persist_plaintext(user):
    plaintext = create_api_token(user, name="t1")["token"]
    row = ApiToken.objects.get(user=user)

    assert row.token_hash != plaintext
    assert plaintext not in row.token_hash


@pytest.mark.django_db
def test_create_api_token_requires_name(user):
    with pytest.raises(ValueError):
        create_api_token(user, name="")
    with pytest.raises(ValueError):
        create_api_token(user, name="   ")


@pytest.mark.django_db
def test_create_api_token_rejects_overlong_name(user):
    with pytest.raises(ValueError):
        create_api_token(user, name="x" * 121)


@pytest.mark.django_db
def test_list_api_tokens_returns_serialised(user):
    create_api_token(user, name="t1")
    create_api_token(user, name="t2")

    rows = list_api_tokens(user)
    names = {row["name"] for row in rows}

    assert names == {"t1", "t2"}
    for row in rows:
        assert "token" not in row  # plaintext never appears


@pytest.mark.django_db
def test_revoke_api_token_marks_revoked(user):
    created = create_api_token(user, name="t1")
    token_id = created["record"]["id"]

    result = revoke_api_token(user, token_id=token_id)

    assert result["status"] == "revoked"
    row = ApiToken.objects.get(id=token_id)
    assert row.revoked_at is not None


@pytest.mark.django_db
def test_revoke_api_token_idempotent(user):
    created = create_api_token(user, name="t1")
    token_id = created["record"]["id"]
    revoke_api_token(user, token_id=token_id)
    second = revoke_api_token(user, token_id=token_id)
    assert second["status"] == "already-revoked"


@pytest.mark.django_db
def test_revoke_api_token_unknown_id_raises(user):
    with pytest.raises(ValueError):
        revoke_api_token(user, token_id=99999)


@pytest.mark.django_db
def test_revoke_api_token_scoped_to_owner(user):
    other = User.objects.create_user(username="other", password="OtherPass!12?")
    created = create_api_token(other, name="other token")
    token_id = created["record"]["id"]

    with pytest.raises(ValueError):
        # ``user`` cannot revoke a token belonging to ``other``
        revoke_api_token(user, token_id=token_id)


# ---- authentication ----


@pytest.mark.django_db
def test_authenticate_api_token_returns_user_when_valid(user):
    plaintext = create_api_token(user, name="t")["token"]

    found = authenticate_api_token(plaintext)

    assert found is not None
    assert found.username == user.username


@pytest.mark.django_db
def test_authenticate_api_token_rejects_invalid(user):
    create_api_token(user, name="t")

    assert authenticate_api_token("ameli_garbage_value_xyz") is None
    assert authenticate_api_token("not-prefixed") is None
    assert authenticate_api_token("") is None


@pytest.mark.django_db
def test_authenticate_api_token_rejects_revoked(user):
    created = create_api_token(user, name="t")
    plaintext = created["token"]
    revoke_api_token(user, token_id=created["record"]["id"])

    assert authenticate_api_token(plaintext) is None


@pytest.mark.django_db
def test_authenticate_api_token_rejects_expired(user):
    plaintext = create_api_token(user, name="t")["token"]
    token = ApiToken.objects.get(user=user)
    token.expires_at = timezone.now() - timezone.timedelta(seconds=10) if hasattr(timezone, "timedelta") else None
    from datetime import timedelta
    token.expires_at = timezone.now() - timedelta(seconds=10)
    token.save(update_fields=["expires_at"])

    assert authenticate_api_token(plaintext) is None


@pytest.mark.django_db
def test_authenticate_api_token_rejects_disabled_user(user):
    plaintext = create_api_token(user, name="t")["token"]
    user.is_active = False
    user.save(update_fields=["is_active"])

    assert authenticate_api_token(plaintext) is None


@pytest.mark.django_db
def test_authenticate_api_token_bumps_last_used(user):
    plaintext = create_api_token(user, name="t")["token"]
    assert ApiToken.objects.get(user=user).last_used_at is None

    authenticate_api_token(plaintext)

    assert ApiToken.objects.get(user=user).last_used_at is not None


# ---- HTTP endpoints ----


@pytest.mark.django_db
def test_profile_tokens_endpoint_lists_tokens_for_logged_in_user(client, user):
    create_api_token(user, name="seed")
    client.force_login(user)

    response = client.get("/profile/tokens/")
    body = json.loads(response.content)

    assert response.status_code == 200
    assert body["ok"] is True
    assert len(body["tokens"]) == 1
    assert body["tokens"][0]["name"] == "seed"


@pytest.mark.django_db
def test_profile_tokens_endpoint_creates_token(client, user):
    client.force_login(user)

    response = client.post(
        "/profile/tokens/",
        data=json.dumps({"name": "ci runner"}),
        content_type="application/json",
    )
    body = json.loads(response.content)

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["token"].startswith("ameli_")
    assert body["record"]["name"] == "ci runner"


@pytest.mark.django_db
def test_profile_tokens_endpoint_requires_login(client):
    response = client.get("/profile/tokens/")
    assert response.status_code in {302, 401}


@pytest.mark.django_db
def test_profile_token_revoke_endpoint(client, user):
    created = create_api_token(user, name="t")
    token_id = created["record"]["id"]
    client.force_login(user)

    response = client.post(f"/profile/tokens/{token_id}/revoke/")

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["status"] in {"revoked", "already-revoked"}


# ---- middleware ----


@pytest.mark.django_db
def test_api_me_works_with_session_auth(client, user):
    client.force_login(user)

    response = client.get("/api/me/")
    body = json.loads(response.content)

    assert response.status_code == 200
    assert body["auth_mode"] == "session"
    assert body["user"]["username"] == user.username


@pytest.mark.django_db
def test_api_me_works_with_bearer_token(client, user):
    plaintext = create_api_token(user, name="bearer test")["token"]

    response = client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    body = json.loads(response.content)

    assert response.status_code == 200
    assert body["auth_mode"] == "token"
    assert body["user"]["username"] == user.username


@pytest.mark.django_db
def test_api_me_rejects_no_auth(client):
    response = client.get("/api/me/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_api_me_rejects_invalid_token(client, user):
    response = client.get("/api/me/", HTTP_AUTHORIZATION="Bearer ameli_invalid_xxx")
    assert response.status_code == 401


@pytest.mark.django_db
def test_api_me_rejects_revoked_token(client, user):
    created = create_api_token(user, name="will revoke")
    revoke_api_token(user, token_id=created["record"]["id"])

    response = client.get(
        "/api/me/", HTTP_AUTHORIZATION=f"Bearer {created['token']}"
    )
    assert response.status_code == 401
