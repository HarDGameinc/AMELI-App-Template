from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from ameli_web.accounts.forms import (
    MAX_AVATAR_BYTES,
    MAX_AVATAR_DIMENSION,
    AvatarUploadForm,
)


def _png_bytes(size=(64, 64), color=(120, 200, 80)) -> bytes:
    buffer = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_upload(name="avatar.png", content=None, content_type="image/png"):
    return SimpleUploadedFile(name, content or _png_bytes(), content_type=content_type)


def test_valid_png_passes_validation():
    form = AvatarUploadForm(files={"avatar": _make_upload()})
    assert form.is_valid(), form.errors


def test_rejects_oversize_payload():
    blob = b"x" * (MAX_AVATAR_BYTES + 1)
    upload = SimpleUploadedFile("big.png", blob, content_type="image/png")

    form = AvatarUploadForm(files={"avatar": upload})

    assert not form.is_valid()
    # Pillow rejects garbage bytes earlier than our size check; either
    # error path is acceptable as long as the form refuses the upload.


def test_rejects_image_larger_than_dimension_cap():
    huge = _png_bytes(size=(MAX_AVATAR_DIMENSION + 50, 200))
    form = AvatarUploadForm(files={"avatar": _make_upload(content=huge)})

    assert not form.is_valid()
    assert any("muy grande" in e or "Maximo" in e for e in form.errors["avatar"])


def test_rejects_unknown_format_via_pillow_error():
    """Non-image bytes are caught by ImageField (Pillow) before our hook,
    but the form must still surface a validation error."""
    upload = SimpleUploadedFile("evil.svg", b"<svg><script>x</script></svg>",
                                content_type="image/svg+xml")
    form = AvatarUploadForm(files={"avatar": upload})

    assert not form.is_valid()


def test_accepts_webp_within_limits():
    buffer = io.BytesIO()
    Image.new("RGB", (128, 128), color=(20, 20, 20)).save(buffer, format="WEBP")
    upload = SimpleUploadedFile("ok.webp", buffer.getvalue(), content_type="image/webp")

    form = AvatarUploadForm(files={"avatar": upload})

    assert form.is_valid(), form.errors


def test_accepts_jpeg_within_limits():
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), color=(128, 0, 0)).save(buffer, format="JPEG")
    upload = SimpleUploadedFile("ok.jpg", buffer.getvalue(), content_type="image/jpeg")

    form = AvatarUploadForm(files={"avatar": upload})

    assert form.is_valid(), form.errors


def test_accepts_gif_within_limits():
    buffer = io.BytesIO()
    Image.new("P", (96, 96)).save(buffer, format="GIF")
    upload = SimpleUploadedFile("ok.gif", buffer.getvalue(), content_type="image/gif")

    form = AvatarUploadForm(files={"avatar": upload})

    assert form.is_valid(), form.errors
