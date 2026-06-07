from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_audit_panel_renders_date_preset_buttons(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert 'data-audit-date-presets' in body
    for preset in ("today", "yesterday", "7d", "30d"):
        assert f'data-audit-preset="{preset}"' in body


@pytest.mark.django_db
def test_audit_panel_date_inputs_carry_data_hooks(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert 'data-audit-date-from' in body
    assert 'data-audit-date-to' in body
