"""Template tags for Subresource Integrity (SRI) on our own static files.

Closes ASVS V14.4.5 / mini-roadmap #8a (2026-06-22) for assets we
ship ourselves. The third-party CDN bundles already had SRI via
``settings.CDN_SRI_HASHES`` (see ``dashboard.views._sri_attr``); this
helper extends the same defense to ``css/app.css`` and ``js/app.js``,
which a future MITM or compromised static host could otherwise swap
silently.

The hash is computed on-disk per absolute path + mtime, cached at
process level so repeat renders are O(1). Dev edits are picked up
automatically because the mtime changes. Production servers compute
once at first render after ``collectstatic`` and reuse forever.

If the static file cannot be located (misnamed, not yet collected),
the tag returns an empty string and Django's ``{% static %}`` will
still emit the resource — the browser simply loses the integrity
check. This is intentional: a missing hash must NOT take down the
page (the operator would lose visibility of the real bug). The
companion test ``test_sri_for_returns_attribute_when_file_present``
pins the happy path.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Final

from django import template
from django.contrib.staticfiles import finders
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

_SRI_ALGO: Final = "sha384"
_HashCache = dict[str, tuple[float, str]]
_cache: _HashCache = {}


def _compute_sri(absolute_path: str) -> str:
    """Compute ``sha384-<base64>`` for ``absolute_path``.

    Cached by ``(path, mtime)`` so a single hash survives across
    requests but a dev edit invalidates the cache as soon as the
    file is rewritten.
    """
    mtime = os.path.getmtime(absolute_path)
    cached = _cache.get(absolute_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with open(absolute_path, "rb") as fh:
        digest = hashlib.sha384(fh.read()).digest()
    encoded = base64.b64encode(digest).decode("ascii")
    value = f"{_SRI_ALGO}-{encoded}"
    _cache[absolute_path] = (mtime, value)
    return value


@register.simple_tag
def sri_for(relative_path: str) -> SafeString:
    """Render ``integrity="sha384-..."`` for a project-owned static file.

    ``relative_path`` is the same string passed to ``{% static %}``
    (e.g. ``"css/app.css"``). The leading space lets templates
    interpolate the result inline:

        <link rel="stylesheet" href="{% static 'css/app.css' %}"{% sri_for 'css/app.css' %}>

    Returns an empty string when the file is not on disk (test
    environments without collectstatic, mistyped path). Callers MUST
    still emit the resource through ``{% static %}`` either way.
    """
    absolute_path = finders.find(relative_path)
    if not absolute_path or not isinstance(absolute_path, str):
        return mark_safe("")  # noqa: S308  # nosec B308 B703 - empty literal, no user input
    try:
        digest = _compute_sri(absolute_path)
    except OSError:
        return mark_safe("")  # noqa: S308  # nosec B308 B703 - empty literal, no user input
    return mark_safe(f' integrity="{digest}"')  # noqa: S308  # nosec B308 B703 - SRI digest is base64 sha384 + leading attribute markup, no operator input
