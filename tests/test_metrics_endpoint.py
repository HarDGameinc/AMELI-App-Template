from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    record_audit,
)
from django.utils import timezone

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_metrics_endpoint_is_public_and_returns_text(client, admin_user):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")


@pytest.mark.django_db
def test_metrics_endpoint_exposes_core_gauges(client, admin_user):
    body = _body(client.get("/metrics"))

    assert "ameli_app_users_total" in body
    assert "ameli_app_users_active" in body
    assert "ameli_app_users_pending_password" in body
    assert "ameli_app_sessions_total" in body
    assert "ameli_app_sessions_active" in body
    assert "ameli_app_sessions_revoked" in body
    assert "ameli_app_audit_events_total" in body
    assert "ameli_app_audit_events_failed" in body
    assert "ameli_app_info" in body


@pytest.mark.django_db
def test_metrics_includes_help_and_type_lines(client, admin_user):
    body = _body(client.get("/metrics"))

    assert "# HELP ameli_app_users_total" in body
    assert "# TYPE ameli_app_users_total gauge" in body
    assert "# TYPE ameli_app_audit_events_total counter" in body


@pytest.mark.django_db
def test_metrics_reflects_user_creation(client, admin_user):
    create_user_account(
        actor_username="admin",
        username="metricsuser",
        password="UserPass!12?",
        role="public",
    )

    body = _body(client.get("/metrics"))
    # admin + metricsuser = 2 users; bootstrap user count must be >= 2
    import re
    match = re.search(r"^ameli_app_users_total (\d+)$", body, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) >= 2


@pytest.mark.django_db
def test_metrics_reflects_session_state(client, admin_user):
    UserSession.objects.create(user=admin_user, session_key="active-s", last_seen_at=timezone.now())
    session2 = UserSession.objects.create(user=admin_user, session_key="revoked-s", last_seen_at=timezone.now())
    session2.revoked_at = timezone.now()
    session2.save(update_fields=["revoked_at"])

    body = _body(client.get("/metrics"))
    import re
    active_match = re.search(r"^ameli_app_sessions_active (\d+)$", body, re.MULTILINE)
    revoked_match = re.search(r"^ameli_app_sessions_revoked (\d+)$", body, re.MULTILINE)
    assert active_match is not None
    assert revoked_match is not None
    assert int(active_match.group(1)) >= 1
    assert int(revoked_match.group(1)) >= 1


@pytest.mark.django_db
def test_metrics_reflects_failed_audit_events(client, admin_user):
    record_audit("login_failed", target_username="x", payload={})
    record_audit("login_success", target_username="x", payload={})

    body = _body(client.get("/metrics"))
    import re
    failed = re.search(r"^ameli_app_audit_events_failed (\d+)$", body, re.MULTILINE)
    total = re.search(r"^ameli_app_audit_events_total (\d+)$", body, re.MULTILINE)
    assert failed is not None and total is not None
    assert int(failed.group(1)) >= 1
    assert int(total.group(1)) >= 2


@pytest.mark.django_db
def test_metrics_info_label_includes_environment_and_version(client, admin_user):
    body = _body(client.get("/metrics"))
    assert 'environment="' in body
    assert 'version="' in body
