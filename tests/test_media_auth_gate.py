from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin

User = get_user_model()


def _seed_media_file(name="probe.txt", content=b"hello-media"):
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    path = media_root / name
    path.write_bytes(content)
    return path


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


@pytest.mark.django_db
def test_media_requires_login(client):
    _seed_media_file()

    response = client.get("/media/probe.txt")

    assert response.status_code == 403


@pytest.mark.django_db
def test_media_served_to_authenticated_user(client, admin_user):
    _seed_media_file()
    client.force_login(admin_user)

    response = client.get("/media/probe.txt")

    assert response.status_code == 200
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert body == b"hello-media"


@pytest.mark.django_db
def test_media_404_for_missing_file(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/media/does-not-exist.png")

    assert response.status_code == 404
