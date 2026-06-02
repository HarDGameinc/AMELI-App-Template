from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_dashboard_home(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "AMELI App Template" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "status" in payload


@pytest.mark.django_db
def test_api_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "AMELI App Template"


@pytest.mark.django_db
def test_docs_endpoint(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "SwaggerUIBundle" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_redoc_endpoint(client):
    response = client.get("/redoc")

    assert response.status_code == 200
    assert "redoc" in response.content.decode("utf-8").lower()


@pytest.mark.django_db
def test_profile_requires_login(client):
    response = client.get("/profile/")

    assert response.status_code == 302
    assert "/login/" in response["Location"]
