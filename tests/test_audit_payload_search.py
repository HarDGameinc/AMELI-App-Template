from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    filtered_audit_queryset,
    paginate_audit_for_admin,
)
from ameli_web.audit.models import AuditEvent

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _seed_audit(action: str, payload: dict, *, actor: str = "admin") -> AuditEvent:
    event = AuditEvent.objects.create(
        action=action,
        actor_username=actor,
        target_username="tester",
        payload=payload,
    )
    return event


@pytest.mark.django_db
def test_paginate_audit_filters_by_payload_substring(admin_user):
    _seed_audit("login_mfa_failed", {"reason": "invalid-code"})
    _seed_audit("login_mfa_failed", {"reason": "expired-token"})
    _seed_audit("login_success", {"auth_mode": "totp"})

    page = paginate_audit_for_admin(payload="invalid", per_page=30)

    matched_actions = [item["action"] for item in page.items]
    assert "login_mfa_failed" in matched_actions
    # Only the row whose payload contained 'invalid' should be returned.
    assert page.total == 1


@pytest.mark.django_db
def test_paginate_audit_payload_filter_is_case_insensitive(admin_user):
    _seed_audit("custom_event", {"detail": "Something Important"})

    page = paginate_audit_for_admin(payload="important", per_page=30)

    assert page.total == 1


@pytest.mark.django_db
def test_paginate_audit_payload_filter_matches_key_or_value(admin_user):
    _seed_audit("event_one", {"reason": "rate-limit"})
    _seed_audit("event_two", {"other_key": "value"})

    page_by_key = paginate_audit_for_admin(payload="reason", per_page=30)
    page_by_value = paginate_audit_for_admin(payload="rate-limit", per_page=30)

    assert page_by_key.total == 1
    assert page_by_value.total == 1


@pytest.mark.django_db
def test_paginate_audit_payload_empty_string_ignored(admin_user):
    _seed_audit("seed_action", {"x": 1})

    page = paginate_audit_for_admin(payload="", per_page=30)

    # Filter ignored → all rows returned (>= seeded ones).
    assert page.total >= 1


@pytest.mark.django_db
def test_filtered_audit_queryset_payload_combines_with_other_filters(admin_user):
    _seed_audit("login_mfa_failed", {"reason": "invalid-code"}, actor="admin")
    _seed_audit("login_mfa_failed", {"reason": "invalid-code"}, actor="otheruser")

    queryset = filtered_audit_queryset(actor="admin", payload="invalid")

    rows = list(queryset)
    assert len(rows) == 1
    assert rows[0].actor_username == "admin"


@pytest.mark.django_db
def test_admin_panel_renders_payload_search_input(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = response.content.decode("utf-8")

    assert 'name="audit_payload"' in body
    assert "Payload contiene" in body


@pytest.mark.django_db
def test_admin_panel_audit_filter_payload_applies_server_side(client, admin_user):
    _seed_audit("event_a", {"key": "alpha-value"})
    _seed_audit("event_b", {"key": "beta-value"})
    client.force_login(admin_user)

    response = client.get("/admin/?audit_payload=alpha&partial=audit")
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "event a" in body
    assert "event b" not in body


@pytest.mark.django_db
def test_admin_panel_clear_filters_drops_payload_param(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/?audit_payload=invalid")
    body = response.content.decode("utf-8")

    import re
    matches = re.findall(r'data-clear-filters\s+href="([^"]+)"', body)
    audit_href = next((h for h in matches if "admin-audit-panel" in h), None)
    assert audit_href is not None
    assert "audit_payload" not in audit_href
