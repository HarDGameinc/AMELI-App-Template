from __future__ import annotations

import json

import pytest


@pytest.mark.django_db
def test_health_returns_extended_payload(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = json.loads(response.content)

    assert body["ok"] is True
    assert body["status"] in {"OPERATIVO", "DEGRADADO"}
    assert "service" in body
    assert "environment" in body
    assert "version" in body
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


@pytest.mark.django_db
def test_health_includes_checks_dict(client):
    body = json.loads(client.get("/health").content)

    assert "checks" in body
    assert "database" in body["checks"]
    assert "ok" in body["checks"]["database"]
    assert "detail" in body["checks"]["database"]


@pytest.mark.django_db
def test_health_keeps_legacy_db_field(client):
    """The previous health probe exposed ``db`` at the top level; keep it
    so existing dashboards do not break on upgrade."""
    body = json.loads(client.get("/health").content)

    assert "db" in body


@pytest.mark.django_db
def test_health_overall_status_derives_from_checks(client):
    body = json.loads(client.get("/health").content)

    expected_overall = all(check["ok"] for check in body["checks"].values())
    assert body["ok"] is expected_overall
    assert (body["status"] == "OPERATIVO") is expected_overall
