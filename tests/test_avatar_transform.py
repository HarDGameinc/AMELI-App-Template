"""D-5 — avatar transform pipeline (resize + WebP re-encode + EXIF strip).

Covers ``ameli_web.accounts.services.images.transform_avatar`` and its
wiring through ``services.user.replace_avatar``:

- a large PNG is shrunk to <= MAX px on the long side and re-encoded WebP
- EXIF (incl. GPS) is dropped by the re-encode (PII leak fix)
- EXIF orientation is baked into the pixels (phone photos display upright)
- ``AVATAR_FORMAT=keep`` disables the transform (returns None)
- an already-small image is not upscaled
- ``replace_avatar`` stores the file with a ``.webp`` extension and
  ``avatar_url`` still resolves
"""
from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from ameli_web.accounts.services import replace_avatar, transform_avatar

User = get_user_model()


def _png_upload(size=(1000, 800), color=(120, 200, 80), name="photo.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _jpeg_with_exif(size=(120, 80), *, orientation=None, gps=False, name="phone.jpg"):
    img = Image.new("RGB", size, color=(200, 30, 30))
    exif = img.getexif()
    if orientation is not None:
        exif[0x0112] = orientation  # Orientation tag
    if gps:
        # Top-level tags that always serialize, so the "source has EXIF"
        # guard never passes vacuously regardless of how Pillow handles
        # the nested GPS IFD across versions.
        exif[0x010F] = "TestPhoneCo"           # Make
        exif[0x0132] = "2021:07:01 10:00:00"   # DateTime
        # GPSInfo IFD — minimal but valid lat/long refs + DMS values.
        # Pillow serializes plain floats into rationals; passing raw
        # ``(num, den)`` tuples breaks its writer on some versions.
        exif[0x8825] = {
            1: "N",
            2: (40.0, 30.0, 0.0),
            3: "W",
            4: (74.0, 0.0, 0.0),
        }
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", exif=exif)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def _open(content_file) -> Image.Image:
    return Image.open(io.BytesIO(content_file.read() if hasattr(content_file, "read") else content_file))


# ---------------------------------------------------------------------------
# transform_avatar — unit
# ---------------------------------------------------------------------------

def test_large_png_becomes_webp_within_max_dimension(settings):
    settings.AVATAR_FORMAT = "webp"
    settings.AVATAR_MAX_DIMENSION = 512
    upload = _png_upload(size=(1000, 800))
    original_bytes = upload.size

    result = transform_avatar(upload, filename=upload.name)

    assert result is not None
    content, name = result
    assert name.endswith(".webp")
    img = Image.open(io.BytesIO(content.read()))
    assert img.format == "WEBP"
    assert max(img.size) <= 512
    # aspect ratio preserved (1000x800 -> 512x410ish, wider than tall)
    assert img.width > img.height
    # re-encode + downscale should be dramatically smaller than the source
    content.seek(0)
    assert len(content.read()) < original_bytes


def test_strips_exif_including_gps(settings):
    settings.AVATAR_FORMAT = "webp"
    upload = _jpeg_with_exif(gps=True)

    # Guard: the source really carries EXIF, otherwise the test would pass
    # vacuously if Pillow silently dropped the metadata on write.
    src = Image.open(io.BytesIO(upload.read()))
    assert dict(src.getexif()), "fixture failed to embed EXIF"
    upload.seek(0)

    result = transform_avatar(upload, filename=upload.name)

    assert result is not None
    content, _name = result
    out = Image.open(io.BytesIO(content.read()))
    exif = out.getexif()
    assert 0x8825 not in exif  # no GPS tag survived
    assert dict(exif) == {}    # in fact no EXIF at all


def test_applies_exif_orientation(settings):
    settings.AVATAR_FORMAT = "webp"
    settings.AVATAR_MAX_DIMENSION = 512
    # Orientation 6 = rotate 90 CW to display upright; a 120x80 landscape
    # source must come out as 80x120 portrait after transpose.
    upload = _jpeg_with_exif(size=(120, 80), orientation=6)

    result = transform_avatar(upload, filename=upload.name)

    assert result is not None
    content, _name = result
    out = Image.open(io.BytesIO(content.read()))
    assert (out.width, out.height) == (80, 120)


def test_keep_format_returns_none(settings):
    settings.AVATAR_FORMAT = "keep"
    upload = _png_upload()

    assert transform_avatar(upload, filename=upload.name) is None


def test_small_image_is_not_upscaled(settings):
    settings.AVATAR_FORMAT = "webp"
    settings.AVATAR_MAX_DIMENSION = 512
    upload = _png_upload(size=(64, 64))

    result = transform_avatar(upload, filename=upload.name)

    assert result is not None
    content, _name = result
    out = Image.open(io.BytesIO(content.read()))
    assert out.size == (64, 64)


def test_transparent_png_keeps_alpha_channel(settings):
    settings.AVATAR_FORMAT = "webp"
    buffer = io.BytesIO()
    Image.new("RGBA", (200, 200), (10, 20, 30, 0)).save(buffer, format="PNG")
    upload = SimpleUploadedFile("t.png", buffer.getvalue(), content_type="image/png")

    result = transform_avatar(upload, filename=upload.name)

    assert result is not None
    content, _name = result
    out = Image.open(io.BytesIO(content.read()))
    assert out.mode == "RGBA"


# ---------------------------------------------------------------------------
# replace_avatar — integration (DB + storage)
# ---------------------------------------------------------------------------

@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="bob",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="bob@example.com",
    )


@pytest.mark.django_db
def test_replace_avatar_stores_webp_and_url_resolves(user, settings):
    settings.AVATAR_FORMAT = "webp"
    upload = _png_upload(size=(900, 900), name="me.png")

    replace_avatar(user, upload)

    user.refresh_from_db()
    assert user.avatar
    assert user.avatar.name.endswith(".webp")
    assert user.avatar_url and user.avatar_url.endswith(".webp")
    # stored bytes decode as a WebP within the cap
    with user.avatar.open("rb") as fh:
        stored = Image.open(io.BytesIO(fh.read()))
    assert stored.format == "WEBP"
    assert max(stored.size) <= int(settings.AVATAR_MAX_DIMENSION)
    # cleanup so the test does not leave a file in the uploads dir
    user.avatar.delete(save=False)


@pytest.mark.django_db
def test_replace_avatar_keep_preserves_original_extension(user, settings):
    settings.AVATAR_FORMAT = "keep"
    upload = _png_upload(size=(300, 300), name="raw.png")

    replace_avatar(user, upload)

    user.refresh_from_db()
    assert user.avatar
    assert user.avatar.name.endswith(".png")  # verbatim store, no re-encode
    user.avatar.delete(save=False)
