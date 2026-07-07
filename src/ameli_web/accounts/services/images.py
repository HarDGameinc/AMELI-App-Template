"""Avatar image transform pipeline — resize + WebP re-encode + EXIF strip.

D-5 (2026-07-02). ``services.user.replace_avatar`` calls
``transform_avatar`` after the AV scan and before persisting, so every
stored avatar is normalised:

1. ``ImageOps.exif_transpose`` — bake the phone's EXIF orientation into
   the pixels (and drop the tag), so the image displays upright.
2. ``img.thumbnail((MAX, MAX))`` — shrink to fit within the configured
   square, preserving aspect ratio. ``thumbnail`` never upscales, so a
   small avatar is left at its native size.
3. Re-encode to WebP — the re-encode drops the entire EXIF block
   (GPS coordinates = PII) as a side-effect, and WebP is dramatically
   smaller than the source PNG/JPEG for the same visual quality.

Settings (all with sane defaults, see ``settings/media.py``):
``AVATAR_FORMAT`` (``webp`` | ``keep``), ``AVATAR_MAX_DIMENSION``,
``AVATAR_WEBP_QUALITY``.

Public symbols are re-exported via ``services/__init__.py``; import from
there, not directly from this module.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from django.conf import settings as django_settings
from django.core.files.base import ContentFile

logger = logging.getLogger("ameli_web.accounts.services.images")


def _avatar_config() -> tuple[str, int, int]:
    """Resolve (format, max_dimension, webp_quality) from settings.

    ``getattr`` with defaults means the pipeline still works if
    ``settings/media.py`` was not loaded (e.g. a downstream fork that
    trimmed the settings package) — it just uses the built-in defaults.
    """
    fmt = str(getattr(django_settings, "AVATAR_FORMAT", "webp") or "webp").strip().lower()
    max_dim = int(getattr(django_settings, "AVATAR_MAX_DIMENSION", 512) or 512)
    quality = int(getattr(django_settings, "AVATAR_WEBP_QUALITY", 82) or 82)
    return fmt, max_dim, quality


def _prepare_mode(img):
    """Return an image in a mode WebP can encode.

    WebP only accepts ``RGB`` / ``RGBA``. Palette (``P``, common in PNG
    and GIF), grayscale (``L``/``LA``) and other modes need converting.
    Preserve transparency when the source has it, else flatten to RGB.
    """
    if img.mode in ("RGB", "RGBA"):
        return img
    has_alpha = "A" in img.getbands() or (img.mode == "P" and "transparency" in img.info)
    return img.convert("RGBA" if has_alpha else "RGB")


def transform_avatar(uploaded_file, *, filename: str | None = None):
    """Normalise an avatar upload for storage.

    Returns a ``(ContentFile, name)`` tuple whose ``name`` ends in the
    target extension (``.webp``), ready to hand to ``ImageField.save``.
    Returns ``None`` to signal "store the upload verbatim" — either
    because the operator set ``AVATAR_FORMAT=keep``, or because the
    transform hit an unexpected error and we fall back rather than
    regress the upload (the form layer has already validated the bytes
    decode as an allowed image, so this is belt-and-suspenders).

    The caller is expected to have already validated the file via
    ``AvatarUploadForm`` and run the AV scan; this function only touches
    pixels.
    """
    fmt, max_dim, quality = _avatar_config()
    if fmt == "keep":
        return None

    # Imported lazily so importing the services package does not pull in
    # Pillow unless an avatar is actually being processed.
    from PIL import Image, ImageOps

    try:
        try:
            uploaded_file.file.seek(0)
        except Exception:  # noqa: BLE001, S110 — some upload streams aren't seekable; best-effort
            pass
        with Image.open(uploaded_file.file) as source:
            # ``exif_transpose`` returns a new image with the orientation
            # baked into the pixels (and the tag removed).
            image = ImageOps.exif_transpose(source) or source
            image.thumbnail((max_dim, max_dim))   # shrink-only, keeps aspect ratio
            image = _prepare_mode(image)
            # ``exif_transpose`` re-attaches the (now orientation-less) EXIF
            # to ``image.info['exif']``, and Pillow's WebP encoder copies
            # ``info['exif']`` / ``info['xmp']`` into the output unless we
            # clear them. Popping both is what actually strips the GPS/PII
            # block — the whole point of D-5. ICC profile goes too (avatars
            # are display-only; assume sRGB).
            for meta_key in ("exif", "xmp", "icc_profile"):
                image.info.pop(meta_key, None)
            buffer = io.BytesIO()
            # ``method=6`` is the slowest/best WebP encoder setting; avatars
            # are encoded once and served forever, so trade CPU for size.
            image.save(buffer, format="WEBP", quality=quality, method=6)
    except Exception:  # noqa: BLE001 — never let a transform failure break the upload
        logger.exception("avatar transform failed; storing upload verbatim")
        try:
            uploaded_file.file.seek(0)
        except Exception:  # noqa: BLE001, S110
            pass
        return None

    stem = Path(filename or getattr(uploaded_file, "name", "") or "avatar").stem or "avatar"
    return ContentFile(buffer.getvalue()), f"{stem}.webp"
