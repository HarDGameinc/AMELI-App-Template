"""Avatar transform pipeline knobs (D-5, 2026-07-02).

The pipeline itself lives in ``ameli_web.accounts.services.images`` and is
called from ``services.user.replace_avatar`` after the AV scan and before
persisting. These settings only tune it; the sane defaults mean the
operator never has to touch them:

- ``AMELI_APP_AVATAR_FORMAT``    default ``webp`` (or ``keep`` to store the
  upload verbatim, disabling the transform entirely).
- ``AMELI_APP_AVATAR_MAX_DIMENSION`` default ``512`` — longest side in px;
  the pipeline only ever shrinks, never upscales.
- ``AMELI_APP_AVATAR_WEBP_QUALITY``  default ``82`` — WebP encoder quality
  (1-100). Ignored when the format is ``keep``.

Rationale: today an avatar is served verbatim — a 3 MB / 4000 px phone
photo sits on disk and re-downloads uncached on every request, and its
EXIF block leaks GPS coordinates (PII). Re-encoding to a small WebP drops
~95% of the bytes AND strips EXIF for free.
"""
from __future__ import annotations

import os

# ``keep`` short-circuits the whole pipeline (store the upload as-is);
# any other value is treated as a re-encode target. Only ``webp`` is a
# supported target today — an unknown value falls back to ``webp`` rather
# than crashing an upload, since this is display-only cosmetic output.
AVATAR_FORMAT = (os.environ.get("AMELI_APP_AVATAR_FORMAT", "webp").strip().lower() or "webp")


def _bounded_int(env_name: str, default: int, *, minimum: int, maximum: int) -> int:
    """Read an int env var, clamping to a sane range.

    A garbage value (non-numeric, negative, absurdly large) must not brick
    avatar uploads, so we fall back to ``default`` on parse failure and
    clamp the parsed value into ``[minimum, maximum]``.
    """
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


# 64 px floor keeps initials-sized avatars legible; 2048 ceiling stops an
# operator from accidentally defeating the whole point (a 4096 px "thumbnail"
# is not a thumbnail).
AVATAR_MAX_DIMENSION = _bounded_int(
    "AMELI_APP_AVATAR_MAX_DIMENSION", 512, minimum=64, maximum=2048,
)

# WebP quality band. 82 is a good size/quality knee for photographic
# avatars; below ~40 artefacts get ugly, above ~95 the size gain vanishes.
AVATAR_WEBP_QUALITY = _bounded_int(
    "AMELI_APP_AVATAR_WEBP_QUALITY", 82, minimum=1, maximum=100,
)
