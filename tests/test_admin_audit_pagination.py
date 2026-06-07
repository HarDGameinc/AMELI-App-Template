from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from datetime import timedelta

from django.utils import timezone

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    filtered_audit_queryset,
    paginate_audit_for_admin,
    record_audit,
)
from ameli_web.audit.models import AuditEvent

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _seed_audit(n: int, *, actor: str = "admin", target: str = "tester", action: str = "login_success") -> None:
    for _ in range(n):
        record_audit(action, target_username=target, payload={})
    # Override actor_username because record_audit reads it from a User instance.
    AuditEvent.objects.filter(actor_username="").update(actor_username=actor)


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- paginate_audit_for_admin service ----


@pytest.mark.django_db
def test_paginate_audit_first_page_orders_by_created_at_desc(admin_user):
    _seed_audit(15)

    page = paginate_audit_for_admin(page=1, per_page=10)

    assert len(page.items) == 10
    timestamps = [item["created_at"] for item in page.items]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.django_db
def test_paginate_audit_total_count_includes_all_events(admin_user):
    _seed_audit(45)

    page = paginate_audit_for_admin(per_page=20)

    assert page.total >= 45


@pytest.mark.django_db
def test_paginate_audit_filters_by_actor(admin_user):
    _seed_audit(5, actor="admin")
    _seed_audit(3, actor="otheruser")

    page = paginate_audit_for_admin(actor="admin", per_page=30)

    actor_names = {item["actor_username"] for item in page.items}
    assert "admin" in actor_names
    assert "otheruser" not in actor_names


@pytest.mark.django_db
def test_paginate_audit_filters_by_target(admin_user):
    _seed_audit(3, target="alice")
    _seed_audit(3, target="bob")

    page = paginate_audit_for_admin(target="alice", per_page=30)

    targets = {item["target_username"] for item in page.items}
    assert targets == {"alice"}


@pytest.mark.django_db
def test_paginate_audit_filters_by_action_substring(admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(3, action="login_failed")
    _seed_audit(2, action="profile_update")

    page = paginate_audit_for_admin(action="login", per_page=30)

    actions = {item["action"] for item in page.items}
    assert actions == {"login_success", "login_failed"}


@pytest.mark.django_db
def test_paginate_audit_outcome_ok_excludes_failed_actions(admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(2, action="login_failed")

    page = paginate_audit_for_admin(outcome="ok", per_page=30)

    actions = {item["action"] for item in page.items}
    assert "login_success" in actions
    assert "login_failed" not in actions


@pytest.mark.django_db
def test_paginate_audit_outcome_error_keeps_failed_only(admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(2, action="login_failed")

    page = paginate_audit_for_admin(outcome="error", per_page=30)

    actions = {item["action"] for item in page.items}
    assert actions == {"login_failed"}


# ---- view rendering ----


@pytest.mark.django_db
def test_admin_panel_renders_audit_pagination_footer(client, admin_user):
    _seed_audit(45)
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert "Mostrando" in body
    assert "audit_page=2" in body
    assert "admin-audit-panel" in body


@pytest.mark.django_db
def test_admin_panel_audit_partial_returns_only_audit(client, admin_user):
    _seed_audit(5)
    client.force_login(admin_user)

    response = client.get("/admin/?partial=audit", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "Auditoria" in body
    # Other panels should NOT be rendered
    assert "Usuarios configurados" not in body


@pytest.mark.django_db
def test_admin_panel_audit_filter_action_substring(client, admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(3, action="profile_update")
    client.force_login(admin_user)

    response = client.get("/admin/?audit_action=login&partial=audit", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "login success" in body
    assert "profile update" not in body


@pytest.mark.django_db
def test_admin_panel_audit_filter_outcome_error(client, admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(2, action="login_failed")
    client.force_login(admin_user)

    response = client.get("/admin/?audit_outcome=error&partial=audit", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "login failed" in body


@pytest.mark.django_db
def test_admin_panel_audit_pagination_preserves_filters(client, admin_user):
    _seed_audit(45, action="login_success")
    client.force_login(admin_user)

    response = client.get("/admin/?audit_action=login")
    body = _body(response)

    assert "audit_action=login" in body
    assert "audit_page=2" in body


@pytest.mark.django_db
def test_admin_panel_audit_empty_filter_renders_no_results_message(client, admin_user):
    _seed_audit(3)
    client.force_login(admin_user)

    response = client.get("/admin/?audit_action=nonexistentaction&partial=audit", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "No hay eventos que coincidan" in body


# ---- date range filters ----


@pytest.mark.django_db
def test_paginate_audit_filters_by_date_from(admin_user):
    _seed_audit(3)
    # Move one event into the past, keep others recent
    old = AuditEvent.objects.first()
    old.created_at = timezone.now() - timedelta(days=10)
    old.save(update_fields=["created_at"])

    today = timezone.now().date().isoformat()
    page = paginate_audit_for_admin(date_from=today, per_page=30)

    ids = {item["id"] for item in page.items}
    assert old.id not in ids


@pytest.mark.django_db
def test_paginate_audit_filters_by_date_to(admin_user):
    _seed_audit(3)
    old = AuditEvent.objects.first()
    old.created_at = timezone.now() - timedelta(days=10)
    old.save(update_fields=["created_at"])

    yesterday = (timezone.now() - timedelta(days=1)).date().isoformat()
    page = paginate_audit_for_admin(date_to=yesterday, per_page=30)

    ids = {item["id"] for item in page.items}
    assert old.id in ids


@pytest.mark.django_db
def test_paginate_audit_invalid_date_is_ignored(admin_user):
    _seed_audit(3)

    page = paginate_audit_for_admin(date_from="not-a-date", per_page=30)

    # Filter silently ignored: full set returned
    assert page.total >= 3


@pytest.mark.django_db
def test_filtered_audit_queryset_respects_combined_filters(admin_user):
    _seed_audit(3, action="login_success")
    _seed_audit(2, action="login_failed")
    older = AuditEvent.objects.filter(action="login_failed").first()
    older.created_at = timezone.now() - timedelta(days=30)
    older.save(update_fields=["created_at"])

    yesterday = (timezone.now() - timedelta(days=1)).date().isoformat()
    queryset = filtered_audit_queryset(action="login", date_to=yesterday)

    rows = list(queryset)
    assert len(rows) == 1
    assert rows[0].id == older.id


@pytest.mark.django_db
def test_admin_panel_renders_date_inputs(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert 'name="audit_date_from"' in body
    assert 'name="audit_date_to"' in body
