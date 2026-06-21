"""Regression coverage for the avatar upload UI on the profile page.

Closes the gap surfaced 2026-06-20: backend (update_avatar /
delete_avatar_view, AvatarUploadForm, AV scan, IDOR gate) had
been in place since the 06-15..06-19 security sprint, but the
profile page only rendered ``current_user.initials`` — no
``<form>`` to actually upload an avatar. End users had no way
to exercise the feature.

These tests pin the new UI: the profile page now carries an
upload form pointing at the avatar endpoint, AND a delete form
when the user already has an avatar.
"""
from __future__ import annotations

import pytest
from django.urls import reverse

from ameli_web.accounts.models import User


@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="probe",
        password="ProbePass!12?Secure",
        role=User.ROLE_PUBLIC,
        must_change_password=False,
    )


@pytest.mark.django_db
def test_profile_page_renders_avatar_upload_form(client, user):
    client.login(username="probe", password="ProbePass!12?Secure")
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")

    # Form must POST to the canonical avatar endpoint.
    assert 'action="/profile/avatar/"' in body or 'action="/profile/avatar"' in body
    # Multipart encoding required for file upload.
    assert 'enctype="multipart/form-data"' in body
    # The file input itself.
    assert 'type="file"' in body
    assert 'name="avatar"' in body
    # ImageField accept hints — the form whitelist is JPEG/PNG/WebP/GIF.
    assert "image/jpeg" in body
    assert "image/png" in body
    assert "image/webp" in body
    assert "image/gif" in body


@pytest.mark.django_db
def test_profile_page_hides_delete_form_when_no_avatar(client, user):
    """Operator without an avatar should not see a "delete" button
    that does nothing (the backend would 200 anyway, but the UX
    is confusing).
    """
    client.login(username="probe", password="ProbePass!12?Secure")
    response = client.get(reverse("accounts:profile"))
    body = response.content.decode("utf-8")

    # The user JUST got created so has no avatar.
    assert not user.avatar
    # The delete form should NOT render.
    assert 'action="/profile/avatar/delete/"' not in body
    assert "Borrar imagen actual" not in body


@pytest.mark.django_db
def test_profile_page_includes_csrf_token_in_avatar_form(client, user):
    """The upload form must carry a CSRF token or POST is rejected
    by the middleware. The {% csrf_token %} tag must be present
    inside the avatar form, not just the preferences form above.
    """
    client.login(username="probe", password="ProbePass!12?Secure")
    response = client.get(reverse("accounts:profile"))
    body = response.content.decode("utf-8")

    # Find the avatar form section
    avatar_form_idx = body.find('id="avatar-form"')
    assert avatar_form_idx >= 0
    # The form closes with </form>; the CSRF token must be inside.
    avatar_form_close = body.find("</form>", avatar_form_idx)
    avatar_form_html = body[avatar_form_idx:avatar_form_close]
    assert "csrfmiddlewaretoken" in avatar_form_html


@pytest.mark.django_db
def test_profile_page_hero_shows_image_when_user_has_avatar(client, user, tmp_path, monkeypatch):
    """When ``current_user.has_avatar`` is true, the .profile-avatar
    section should render an <img> instead of the initials.
    """
    # Plant a tiny PNG into the avatar field directly (skip the
    # form/AV path; this test is about the hero render, not upload).
    from django.core.files.base import ContentFile
    # 1x1 transparent PNG.
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63600100000005000175b96b08000000004945"
        "4e44ae426082"
    )
    user.avatar.save("probe.png", ContentFile(png_bytes), save=True)
    user.refresh_from_db()
    assert user.avatar

    client.login(username="probe", password="ProbePass!12?Secure")
    response = client.get(reverse("accounts:profile"))
    body = response.content.decode("utf-8")

    # Hero shows the image, not initials, when avatar is set.
    assert 'class="profile-avatar-image"' in body
    # And the delete form NOW renders (we have an avatar to delete).
    assert "Borrar imagen actual" in body
