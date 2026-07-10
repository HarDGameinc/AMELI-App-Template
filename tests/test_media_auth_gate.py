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


# ---------------------------------------------------------------------------
# ASVS V4.2.1 — avatar ownership gate (roadmap #4)
# ---------------------------------------------------------------------------
#
# The previous behaviour was auth-only: any logged-in user could fetch
# any avatar by guessing the 64-bit token. The current behaviour
# (urls.py `_authenticated_media`) is owner-or-superadmin for
# avatars/* and unchanged auth-only for everything else.


def _seed_avatar(slug: str, token: str = "a1b2c3d4e5f60718", ext: str = "png",
                 content: bytes = b"fake-png-bytes", owner=None) -> str:
    """Plant a fake avatar file under ``MEDIA_ROOT/avatars/`` and return its
    URL-path tail. Mirrors ``avatar_upload_to`` (owner slug + 16-hex token +
    ext). When ``owner`` is given, also point that user's ``avatar`` field
    at the file — as a real upload would — so the ownership gate (which now
    matches the exact stored ``avatar.name``, not a lossy slug) recognises
    them. Tests do NOT need a real PNG; ``serve`` only round-trips bytes.
    """
    media_root = Path(settings.MEDIA_ROOT) / "avatars"
    media_root.mkdir(parents=True, exist_ok=True)
    name = f"{slug}-{token}.{ext}"
    (media_root / name).write_bytes(content)
    rel = f"avatars/{name}"
    if owner is not None:
        owner.avatar.name = rel
        owner.save(update_fields=["avatar"])
    return rel


@pytest.fixture()
def alice(db):
    return User.objects.create_user(
        username="alice",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="alice@example.com",
    )


@pytest.fixture()
def bob(db):
    return User.objects.create_user(
        username="bob",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="bob@example.com",
    )


@pytest.mark.django_db
def test_owner_can_fetch_their_own_avatar(client, alice):
    rel = _seed_avatar("alice", owner=alice)
    client.force_login(alice)
    response = client.get(f"/media/{rel}")
    assert response.status_code == 200
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert body == b"fake-png-bytes"


@pytest.mark.django_db
def test_slug_twin_cannot_fetch_avatar(client):
    """L1 regression: usernames that collapse to the SAME slug (the old gate
    compared lossy slugs, so ``al.ice`` and ``al-ice`` both slug to
    ``al-ice`` and passed each other's ownership check). Ownership now keys
    on the exact stored avatar name, so the twin is refused.
    """
    owner = User.objects.create_user(username="al.ice", password="UserPass!12?",
                                      role=User.ROLE_PUBLIC, email="a@example.com")
    twin = User.objects.create_user(username="al-ice", password="UserPass!12?",
                                    role=User.ROLE_PUBLIC, email="b@example.com")
    rel = _seed_avatar("al-ice", owner=owner)  # avatar_upload_to slug for both
    client.force_login(twin)
    assert client.get(f"/media/{rel}").status_code == 403


@pytest.mark.django_db
def test_other_user_cannot_fetch_owner_avatar(client, alice, bob):
    """Regression test for the IDOR gap (ASVS V4.2.1). Bob is
    authenticated and knows alice's avatar URL (from a JSON leak in
    the admin endpoint or any other source); the gate must refuse and
    audit the attempt.
    """
    from ameli_web.audit.models import AuditEvent

    rel = _seed_avatar("alice", owner=alice)
    client.force_login(bob)
    response = client.get(f"/media/{rel}")
    assert response.status_code == 403
    # Audit chain keyed to the OWNER, not the requester, so an
    # operator grep can answer "who was probed?".
    audit = AuditEvent.objects.filter(
        action="media_access_denied",
        target_username="alice",
    ).first()
    assert audit is not None
    assert audit.actor_username == "bob"
    assert audit.payload.get("reason") == "not_owner"
    assert audit.payload.get("path") == rel


@pytest.mark.django_db
def test_superadmin_can_fetch_any_avatar(client, alice, admin_user):
    """Operator path — superadmin must be able to fetch any user's
    avatar (e.g. the future admin user-list UI may render them).
    """
    rel = _seed_avatar("alice")
    client.force_login(admin_user)
    response = client.get(f"/media/{rel}")
    assert response.status_code == 200


@pytest.mark.django_db
def test_malformed_avatar_path_returns_404(client, alice):
    """A request shaped like ``/media/avatars/foo`` (no token-ext) is
    indistinguishable from a typo. Returning 404 rather than 403
    avoids leaking owner existence for an attacker fishing for
    accounts.
    """
    client.force_login(alice)
    response = client.get("/media/avatars/no-token-here")
    assert response.status_code == 404


@pytest.mark.django_db
def test_non_avatar_media_still_auth_only(client, alice):
    """Back-compat: paths outside ``avatars/`` keep the previous
    auth-only behaviour. The existing ``test_media_served_to_authenticated_user``
    above asserts this for admins; this one pins the same for a
    non-admin public user.
    """
    _seed_media_file("public-blob.txt", b"public-bytes")
    client.force_login(alice)
    response = client.get("/media/public-blob.txt")
    assert response.status_code == 200


@pytest.mark.django_db
def test_anonymous_request_unchanged_for_avatars(client, alice):
    """The auth-gate branch fires first for anonymous: 403 + no
    leak about whether the avatar exists or who owns it.
    """
    rel = _seed_avatar("alice")
    response = client.get(f"/media/{rel}")
    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_with_special_chars_in_username(client, db):
    """User ``Carlos Urbina`` is stored with the safe-username slug
    ``carlos-urbina`` in the avatar filename. Ownership now keys on the
    exact stored ``avatar.name`` (not a re-derived slug), so the owner
    reaches their own avatar regardless of username punctuation.
    """
    user = User.objects.create_user(
        username="Carlos Urbina",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
    )
    rel = _seed_avatar("carlos-urbina", owner=user)
    client.force_login(user)
    response = client.get(f"/media/{rel}")
    assert response.status_code == 200

