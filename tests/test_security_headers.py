from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_csp_header_is_attached(client):
    response = client.get("/health")

    assert "Content-Security-Policy" in response.headers
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.django_db
def test_x_content_type_options_is_nosniff(client):
    response = client.get("/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.django_db
def test_referrer_policy_is_same_origin(client):
    response = client.get("/health")
    assert response.headers.get("Referrer-Policy") == "same-origin"


@pytest.mark.django_db
def test_x_frame_options_is_deny(client):
    response = client.get("/health")
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_session_cookie_is_httponly():
    from django.conf import settings
    assert settings.SESSION_COOKIE_HTTPONLY is True


def test_csrf_cookie_is_httponly():
    from django.conf import settings
    assert settings.CSRF_COOKIE_HTTPONLY is True


def test_samesite_lax_on_session_and_csrf():
    from django.conf import settings
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
