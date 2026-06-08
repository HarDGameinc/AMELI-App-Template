from __future__ import annotations

import csv
import io
import json

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _seed(n: int, *, prefix: str = "user", role: str = "public") -> None:
    for i in range(n):
        create_user_account(
            actor_username="admin",
            username=f"{prefix}-{i:02d}",
            password="UserPass!12?",
            role=role,
        )


def _read_streaming(response) -> str:
    chunks = b"".join(response.streaming_content) if response.streaming else response.content
    return chunks.decode("utf-8")


@pytest.mark.django_db
def test_users_export_requires_login(client):
    response = client.get("/admin/users/export/")
    assert response.status_code in {302, 401}


@pytest.mark.django_db
def test_users_export_rejects_non_admin(client, admin_user):
    viewer = User.objects.create_user(username="viewer", password="UserPass!12?")
    client.force_login(viewer)

    response = client.get("/admin/users/export/")
    assert response.status_code in {302, 403}


@pytest.mark.django_db
def test_users_export_csv_default_format(client, admin_user):
    _seed(3, prefix="csvuser")
    client.force_login(admin_user)

    response = client.get("/admin/users/export/?users_search=csvuser")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "filename=\"users.csv\"" in response["Content-Disposition"]
    body = _read_streaming(response)
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    assert rows[0] == [
        "username", "display_name", "role", "is_active",
        "must_change_password", "last_login", "date_joined",
    ]
    assert len(rows) - 1 == 3


@pytest.mark.django_db
def test_users_export_json_format(client, admin_user):
    _seed(3, prefix="jsonuser")
    client.force_login(admin_user)

    response = client.get("/admin/users/export/?format=json&users_search=jsonuser")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    body = _read_streaming(response)
    items = json.loads(body)
    assert isinstance(items, list)
    assert len(items) == 3
    assert {"username", "role", "is_active"}.issubset(items[0].keys())


@pytest.mark.django_db
def test_users_export_respects_role_filter(client, admin_user):
    _seed(2, prefix="rolepublic", role="public")
    client.force_login(admin_user)

    response = client.get("/admin/users/export/?users_role=superadmin")
    body = _read_streaming(response)
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)[1:]
    # Only admin (the bootstrap superadmin) should appear.
    assert all(row[2] == "superadmin" for row in rows)


@pytest.mark.django_db
def test_users_export_respects_status_filter(client, admin_user):
    _seed(2, prefix="statususer", role="public")
    # Disable one
    target = User.objects.get(username="statususer-00")
    target.is_active = False
    target.save(update_fields=["is_active"])
    client.force_login(admin_user)

    response = client.get("/admin/users/export/?users_status=disabled&format=json")
    body = _read_streaming(response)
    items = json.loads(body)
    assert len(items) == 1
    assert items[0]["username"] == "statususer-00"


@pytest.mark.django_db
def test_users_export_empty_result(client, admin_user):
    client.force_login(admin_user)

    response_csv = client.get("/admin/users/export/?users_search=nonexistent_xxx")
    body_csv = _read_streaming(response_csv)
    assert response_csv.status_code == 200
    assert body_csv.startswith("username,display_name,")

    response_json = client.get("/admin/users/export/?users_search=nonexistent_xxx&format=json")
    body_json = _read_streaming(response_json)
    assert json.loads(body_json) == []


@pytest.mark.django_db
def test_admin_panel_renders_users_export_buttons(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = response.content.decode("utf-8")

    assert "data-users-export-csv" in body
    assert "data-users-export-json" in body
    assert "/admin/users/export/" in body
