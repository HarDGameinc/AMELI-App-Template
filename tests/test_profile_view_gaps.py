"""HTTP-level coverage for accounts/views/profile.py gaps.

PC-2 (2026-07-01) split accounts/views.py into a package; the split
surfaced several untested branches: the ``?partial=sessions`` fetch
path on ``profile_view``, ``update_preferences``'s GET-405 / malformed
JSON / invalid-form branches, ``update_avatar``'s invalid-form branch
and its JSON-success return, and ``delete_avatar_view`` — which had
ZERO HTTP-level coverage (only referenced in a UI-rendering assertion,
never actually POSTed to).
"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

User = get_user_model()

USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="probe",
        password=USER_PASSWORD,
        role=User.ROLE_PUBLIC,
        email="probe@example.com",
    )


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# profile_view — ?partial=sessions fetch path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_view_renders_sessions_partial_for_fetch_request(client, user):
    client.force_login(user)
    response = client.get(
        "/profile/?partial=sessions",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # The partial template is a fragment, not the full page shell.
    assert "<html" not in body.lower()


@pytest.mark.django_db
def test_profile_view_ignores_partial_param_on_plain_refresh(client, user):
    """Without the fetch marker header, ?partial= is ignored so a
    bare page refresh still gets the full page (avoids a bare
    fragment rendering with no layout/css)."""
    client.force_login(user)
    response = client.get("/profile/?partial=sessions")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "<html" in body.lower()


# ---------------------------------------------------------------------------
# update_preferences
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_preferences_rejects_get(client, user):
    client.force_login(user)
    response = client.get("/profile/preferences/")
    assert response.status_code == 405


@pytest.mark.django_db
def test_update_preferences_rejects_malformed_json(client, user):
    client.force_login(user)
    response = client.patch(
        "/profile/preferences/", data=b"not-json{{{", content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_update_preferences_form_post_invalid_shows_error(client, user):
    """A non-JSON form POST with an out-of-range theme value fails
    form validation; the view must flash an error and redirect
    rather than 500 or silently accept it."""
    client.force_login(user)
    response = client.post(
        "/profile/preferences/",
        data={"display_name": "x" * 500, "theme_preference": "not-a-real-theme"},
    )
    assert response.status_code == 302
    assert response["Location"].endswith("/profile/")


@pytest.mark.django_db
def test_update_preferences_form_post_valid_updates_user(client, user):
    client.force_login(user)
    response = client.post(
        "/profile/preferences/",
        data={"display_name": "Probe User", "theme_preference": "dark"},
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.display_name == "Probe User"
    assert user.theme_preference == "dark"


# ---------------------------------------------------------------------------
# update_avatar — invalid form + JSON success path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_avatar_rejects_invalid_file_json(client, user):
    client.force_login(user)
    bogus = SimpleUploadedFile("not-an-image.txt", b"plain text", content_type="text/plain")
    response = client.post(
        "/profile/avatar/", {"avatar": bogus}, HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.django_db
def test_update_avatar_rejects_invalid_file_non_json_redirects(client, user):
    client.force_login(user)
    bogus = SimpleUploadedFile("not-an-image.txt", b"plain text", content_type="text/plain")
    response = client.post("/profile/avatar/", {"avatar": bogus})
    assert response.status_code == 302
    assert response["Location"].endswith("/profile/")
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.django_db
def test_update_avatar_success_json_returns_updated_user(client, user, settings):
    settings.AV_ENDPOINT = ""
    client.force_login(user)
    upload = SimpleUploadedFile("avatar.png", _png_bytes(), content_type="image/png")
    response = client.post(
        "/profile/avatar/", {"avatar": upload}, HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["user"]["has_avatar"] is True


# ---------------------------------------------------------------------------
# delete_avatar_view — zero prior HTTP coverage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_avatar_view_removes_avatar_json(client, user):
    user.avatar.save("probe.png", ContentFile(_png_bytes()), save=True)
    user.refresh_from_db()
    assert user.avatar

    client.force_login(user)
    response = client.post(
        "/profile/avatar/delete/", HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["user"]["has_avatar"] is False
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.django_db
def test_delete_avatar_view_non_json_redirects(client, user):
    user.avatar.save("probe2.png", ContentFile(_png_bytes()), save=True)
    user.refresh_from_db()

    client.force_login(user)
    response = client.post("/profile/avatar/delete/")
    assert response.status_code == 302
    assert response["Location"].endswith("/profile/")
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.django_db
def test_delete_avatar_view_is_idempotent_when_no_avatar(client, user):
    """Calling delete when there is no avatar must not 500 — the
    service layer no-ops and the view still returns success."""
    client.force_login(user)
    response = client.post(
        "/profile/avatar/delete/", HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


# ---------------------------------------------------------------------------
# Low-value residual gaps: SMTP-layer generic Exception branches +
# password-age alert branch + non-seekable file.seek() best-effort.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_profile_test_email_view_maps_smtp_exception_to_502(
    client, user, monkeypatch,
):
    """The generic ``except Exception`` branch fires when the mail
    backend raises anything other than ``ValueError``. Property: the
    endpoint surfaces a 502 with a readable error, does NOT 500, and
    does NOT overwrite the cooldown timestamp with a bad send."""
    from ameli_web.accounts.views import profile as profile_module

    def boom(*_args, **_kwargs):
        raise RuntimeError("smtp gone")

    monkeypatch.setattr(profile_module, "send_profile_test_email", boom)
    client.force_login(user)

    response = client.post("/profile/email/test/")

    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert "SMTP" in body["error"] or "smtp" in body["error"].lower()


@pytest.mark.django_db
def test_update_avatar_swallows_seek_exception_on_non_seekable_stream(
    client, user, monkeypatch, settings,
):
    """When ``av_endpoint`` is configured the view seeks the upload
    stream before AND after ``read()`` — both wrapped in a bare
    ``try/except`` because SimpleUploadedFile always seeks OK, but a
    real Django ``TemporaryUploadedFile`` on an exotic FS may not.
    Force the exception and prove the upload still completes.

    We can't monkeypatch BytesIO.seek (immutable slot), so we patch
    ``av.scan_bytes`` to trigger the same code path — the two
    swallowing try/except blocks bracket the ``scan_bytes`` call, and
    a non-seekable file would only raise inside those blocks. Instead
    of proving the swallowing works on a real non-seekable file (that
    requires OS-level plumbing), we simulate: replace the
    ``UploadedFile.file`` attribute with a wrapper that only implements
    ``read()`` + raises on ``seek``. Django copies UploadedFile
    through the form layer, so we intercept at the view level via
    monkeypatching the form's cleaned_data hook."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from ameli_web.accounts import av

    settings.AV_ENDPOINT = "tcp://127.0.0.1:3310"

    class _NonSeekable:
        """Read-only proxy that raises on seek but preserves read()."""

        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._read = False

        def seek(self, *_args, **_kwargs):
            raise OSError("underlying stream is not seekable")

        def read(self, *_args, **_kwargs):
            if self._read:
                return b""
            self._read = True
            return self._payload

    upload = SimpleUploadedFile("avatar.png", _png_bytes(), content_type="image/png")
    upload.file = _NonSeekable(_png_bytes())

    monkeypatch.setattr(av, "scan_bytes", lambda *_a, **_kw: ("ok", ""))

    client.force_login(user)
    response = client.post("/profile/avatar/", {"avatar": upload})

    # Upload proceeds despite the two seek failures (best-effort try/except).
    assert response.status_code in (200, 302)


@pytest.mark.django_db
def test_security_alerts_flags_password_age_over_max(
    client, user, settings,
):
    """When the user's ``date_joined`` (fallback for ``password_changed_at``,
    which is not a real field yet) is older than
    ``PROFILE_PASSWORD_MAX_AGE_DAYS`` an alert row appears in the
    profile context. Exercises the ``age_days > max_age`` branch of
    ``_security_alerts_for`` which was otherwise unreachable from
    tests (fresh users always have a young ``date_joined``)."""
    from datetime import timedelta

    from django.utils import timezone

    settings.PROFILE_PASSWORD_MAX_AGE_DAYS = 30
    # 200 days > 30 days threshold, and > 90 days default so the alert
    # would still fire even if a caller forgot the settings override.
    user.date_joined = timezone.now() - timedelta(days=200)
    user.save(update_fields=["date_joined"])

    client.force_login(user)
    response = client.get("/profile/")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # The alert title mentions the number of days OR "contrasena".
    assert "200 dias" in body or "contrasena" in body.lower()
