from __future__ import annotations

import csv
import io
import json

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, record_audit
from ameli_web.audit.models import AuditEvent

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _seed(n: int, *, action: str = "login_success", target: str = "tester") -> None:
    for _ in range(n):
        record_audit(action, target_username=target, payload={"k": "v"})
    AuditEvent.objects.filter(actor_username="").update(actor_username="admin")


def _read_streaming(response) -> str:
    chunks = b"".join(response.streaming_content) if response.streaming else response.content
    return chunks.decode("utf-8")


@pytest.mark.django_db
def test_audit_export_requires_login(client):
    response = client.get("/admin/audit/export/")

    assert response.status_code in {302, 401}


@pytest.mark.django_db
def test_audit_export_rejects_non_admin(client, admin_user):
    public = User.objects.create_user(username="viewer", password="UserPass!12?")
    client.force_login(public)

    response = client.get("/admin/audit/export/")

    assert response.status_code in {302, 403}


@pytest.mark.django_db
def test_audit_export_csv_default_format(client, admin_user):
    _seed(3, action="seed_csv_action")
    client.force_login(admin_user)

    response = client.get("/admin/audit/export/?audit_action=seed_csv")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "filename=\"audit.csv\"" in response["Content-Disposition"]
    body = _read_streaming(response)
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    assert rows[0] == [
        "id", "created_at", "actor_username", "target_username",
        "action", "display_result_label", "payload",
    ]
    assert len(rows) - 1 == 3  # only seeded rows


@pytest.mark.django_db
def test_audit_export_json_format(client, admin_user):
    _seed(3, action="seed_json_action")
    client.force_login(admin_user)

    response = client.get("/admin/audit/export/?format=json&audit_action=seed_json")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    body = _read_streaming(response)
    items = json.loads(body)
    assert isinstance(items, list)
    assert len(items) == 3
    assert {"id", "created_at", "actor_username", "action"}.issubset(items[0].keys())


@pytest.mark.django_db
def test_audit_export_respects_actor_filter(client, admin_user):
    _seed(3)
    _seed(2, target="other")
    AuditEvent.objects.filter(actor_username="admin").update(actor_username="admin")
    other = AuditEvent.objects.filter(target_username="other").first()
    other.actor_username = "otheruser"
    other.save(update_fields=["actor_username"])
    client.force_login(admin_user)

    response = client.get("/admin/audit/export/?audit_actor=admin")
    body = _read_streaming(response)
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    # All data rows should be actor=admin
    for row in rows[1:]:
        assert row[2] == "admin"


@pytest.mark.django_db
def test_audit_export_respects_outcome_filter(client, admin_user):
    _seed(2, action="login_success")
    _seed(3, action="login_failed")
    client.force_login(admin_user)

    response = client.get("/admin/audit/export/?audit_outcome=error&format=json")
    body = _read_streaming(response)
    items = json.loads(body)
    assert len(items) == 3
    assert all(item["action"].endswith("_failed") for item in items)


@pytest.mark.django_db
def test_audit_export_empty_result_returns_valid_payload(client, admin_user):
    client.force_login(admin_user)

    response_csv = client.get("/admin/audit/export/?format=csv&audit_action=nonexistent_seed_action")
    body_csv = _read_streaming(response_csv)
    assert response_csv.status_code == 200
    assert body_csv.startswith("id,created_at,")

    response_json = client.get("/admin/audit/export/?format=json&audit_action=nonexistent_seed_action")
    body_json = _read_streaming(response_json)
    assert json.loads(body_json) == []


@pytest.mark.django_db
def test_admin_panel_renders_export_buttons(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = response.content.decode("utf-8")

    assert "Exportar CSV" in body
    assert "Exportar JSON" in body
    assert "/admin/audit/export/" in body
