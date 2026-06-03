from __future__ import annotations

import pytest

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    delete_user_account,
    reset_user_password,
    update_user_account,
)

ADMIN_PASSWORD = "AdminPass!12?"
TESTER_PASSWORD = "TesterPass!12?"


@pytest.fixture()
def admin_user(db):
    return bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)


@pytest.fixture()
def public_tester(db, admin_user):
    return create_user_account(
        actor_username="admin",
        username="tester",
        password=TESTER_PASSWORD,
        role="public",
    )


# ---- update_user_account: self-disable ----


@pytest.mark.django_db
def test_update_user_account_blocks_self_disable():
    with pytest.raises(ValueError, match="disable your own account"):
        update_user_account("admin", "admin", enabled=False)


@pytest.mark.django_db
def test_update_user_account_self_disable_is_case_insensitive():
    with pytest.raises(ValueError, match="disable your own account"):
        update_user_account("ADMIN", "admin", enabled=False)


@pytest.mark.django_db
def test_update_user_account_allows_non_self_disable(admin_user, public_tester):
    result = update_user_account("admin", "tester", enabled=False)
    assert result["ok"] is True
    assert result["user"]["enabled"] is False


# ---- update_user_account: self-role-change ----


@pytest.mark.django_db
def test_update_user_account_blocks_self_role_change():
    with pytest.raises(ValueError, match="change your own role"):
        update_user_account("admin", "admin", role="public")


@pytest.mark.django_db
def test_update_user_account_blocks_self_role_change_even_when_same_value():
    # Stricter than the previous implementation: passing role for self is
    # always rejected, even if the value equals the current role. Callers
    # that pass role=current_role have a bug and should learn about it.
    with pytest.raises(ValueError, match="change your own role"):
        update_user_account("admin", "admin", role="superadmin")


@pytest.mark.django_db
def test_update_user_account_allows_non_self_role_change(admin_user, public_tester):
    result = update_user_account("admin", "tester", role="superadmin")
    assert result["ok"] is True
    assert result["user"]["role"] == "superadmin"


# ---- update_user_account: allowed self fields ----


@pytest.mark.django_db
def test_update_user_account_allows_self_must_change_password(admin_user):
    # An admin may force itself to rotate its password on next login.
    result = update_user_account("admin", "admin", must_change_password=True)
    assert result["ok"] is True
    assert result["user"]["must_change_password"] is True


# ---- reset_user_password ----


@pytest.mark.django_db
def test_reset_user_password_blocks_self():
    with pytest.raises(ValueError, match="change password from your profile"):
        reset_user_password("admin", "admin")


@pytest.mark.django_db
def test_reset_user_password_self_is_case_insensitive():
    with pytest.raises(ValueError, match="change password from your profile"):
        reset_user_password("admin", "ADMIN")


@pytest.mark.django_db
def test_reset_user_password_allows_non_self(admin_user, public_tester):
    result = reset_user_password("admin", "tester", password=TESTER_PASSWORD)
    assert result["ok"] is True
    assert result["username"] == "tester"


# ---- delete_user_account ----


@pytest.mark.django_db
def test_delete_user_account_blocks_any_superadmin(admin_user):
    # The guard protects every superadmin (not only self) to avoid the
    # "no admin left" lockout scenario.
    with pytest.raises(ValueError, match="superadmin cannot be deleted"):
        delete_user_account("admin", "admin")


@pytest.mark.django_db
def test_delete_user_account_allows_public_user(admin_user, public_tester):
    result = delete_user_account("admin", "tester")
    assert result["ok"] is True
    assert result["username"] == "tester"
