from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import ApiToken
from ameli_web.accounts.services import (
    VALID_API_TOKEN_SCOPES,
    bootstrap_superadmin,
    create_api_token,
)

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


# ---- service-level scope handling ----


@pytest.mark.django_db
def test_default_scopes_is_read_only(admin_user):
    result = create_api_token(admin_user, name="defaults")

    record = ApiToken.objects.get(id=result["record"]["id"])
    assert record.scopes == ["read"]
    assert record.has_scope("read") is True
    assert record.has_scope("admin") is False


@pytest.mark.django_db
def test_explicit_scopes_are_persisted(admin_user):
    result = create_api_token(admin_user, name="x", scopes=["read", "admin"])

    record = ApiToken.objects.get(id=result["record"]["id"])
    assert record.scopes == ["read", "admin"]
    assert record.has_scope("admin") is True


@pytest.mark.django_db
def test_unknown_scope_is_rejected(admin_user):
    with pytest.raises(ValueError, match="unknown scope"):
        create_api_token(admin_user, name="x", scopes=["read", "delete-everything"])


@pytest.mark.django_db
def test_scopes_are_deduplicated_and_lowercased(admin_user):
    result = create_api_token(admin_user, name="x", scopes=["READ", "Read", "write"])

    record = ApiToken.objects.get(id=result["record"]["id"])
    assert record.scopes == ["read", "write"]


def test_known_scope_set_includes_admin_read_write():
    assert set(VALID_API_TOKEN_SCOPES) == {"read", "write", "admin"}


# ---- admin endpoint enforces ``admin`` scope ----


@pytest.mark.django_db
def test_admin_endpoint_rejects_token_without_admin_scope(client, admin_user):
    """A token belonging to a superadmin still cannot reach admin endpoints
    unless its scopes include ``admin``."""
    result = create_api_token(admin_user, name="read-only")
    token = result["token"]

    # /admin/ is a superadmin-only view
    response = client.get("/admin/users", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_endpoint_accepts_token_with_admin_scope(client, admin_user):
    result = create_api_token(admin_user, name="full-admin", scopes=["read", "admin"])
    token = result["token"]

    response = client.get("/admin/users", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200


@pytest.mark.django_db
def test_session_auth_does_not_require_token_scope(client, admin_user):
    """Browser sessions are not tokens, so the scope check must not apply
    to them — superadmin via cookie still works as before."""
    client.force_login(admin_user)

    response = client.get("/admin/users", HTTP_ACCEPT="application/json")

    assert response.status_code == 200
