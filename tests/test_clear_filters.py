from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account, record_audit

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- Users panel ----


@pytest.mark.django_db
def test_clear_filters_link_hidden_when_no_users_filter_active(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert "Limpiar filtros" not in body


@pytest.mark.django_db
def test_clear_filters_link_visible_when_users_search_active(client, admin_user):
    create_user_account(actor_username="admin", username="viewer",
                        password="UserPass!12?", role="public")
    client.force_login(admin_user)

    response = client.get("/admin/?users_search=view")
    body = _body(response)

    assert "Limpiar filtros" in body
    assert "data-clear-filters" in body


@pytest.mark.django_db
def test_clear_filters_link_drops_users_filter_params(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/?users_search=view&users_role=public&users_status=enabled")
    body = _body(response)

    # The link should NOT carry the filter params it is meant to clear.
    # Extract the href of the clear-filters link from the rendered HTML.
    import re
    match = re.search(r'data-clear-filters\s+href="([^"]+)"', body)
    assert match is not None
    href = match.group(1)
    assert "users_search" not in href
    assert "users_role" not in href
    assert "users_status" not in href


@pytest.mark.django_db
def test_clear_filters_link_preserves_audit_state(client, admin_user):
    """Clearing users filters must not lose audit pagination/filter state."""
    client.force_login(admin_user)

    response = client.get(
        "/admin/?users_search=view&audit_actor=admin&audit_page=2"
    )
    body = _body(response)

    import re
    match = re.search(r'data-clear-filters\s+href="([^"]+)"', body)
    assert match is not None
    href = match.group(1)
    assert "audit_actor=admin" in href
    assert "audit_page=2" in href


# ---- Audit panel ----


@pytest.mark.django_db
def test_clear_filters_link_visible_for_audit_when_filter_active(client, admin_user):
    record_audit("login_success", target_username="tester", payload={})
    client.force_login(admin_user)

    response = client.get("/admin/?audit_action=login")
    body = _body(response)

    # Both panels may render the link; just confirm it exists once when audit filter is set.
    assert body.count("Limpiar filtros") >= 1


@pytest.mark.django_db
def test_clear_filters_for_audit_drops_audit_filter_params(client, admin_user):
    record_audit("login_success", target_username="tester", payload={})
    client.force_login(admin_user)

    response = client.get(
        "/admin/?audit_actor=admin&audit_outcome=ok&audit_date_from=2026-01-01"
    )
    body = _body(response)

    import re
    # Find the link that lives in the audit toolbar (anchor #admin-audit-panel)
    matches = re.findall(r'data-clear-filters\s+href="([^"]+)"', body)
    assert matches, "Expected at least one clear-filters link"
    audit_href = next((h for h in matches if "admin-audit-panel" in h), None)
    assert audit_href is not None
    assert "audit_actor" not in audit_href
    assert "audit_outcome" not in audit_href
    assert "audit_date_from" not in audit_href


@pytest.mark.django_db
def test_clear_filters_link_hidden_when_no_audit_filter_active(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    # No filter in either panel → no link at all.
    assert "data-clear-filters" not in body
