"""SRI on own statics — mini-roadmap #8a (2026-06-22).

Pinning the helper that emits ``integrity="sha384-..."`` for project-
owned bundles. Third-party CDN bundles already had SRI gated by
``settings.CDN_SRI_HASHES`` (see dashboard.views._sri_attr); these
tests cover the new ``{% sri_for %}`` tag for ``css/app.css`` and
``js/app.js``, which a future MITM / compromised static host could
otherwise swap silently.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from django.template import Context, Template

from ameli_web.accounts.templatetags import sri as sri_tag


def _expected_digest(relative_path: str) -> str:
    path = finders.find(relative_path)
    assert isinstance(path, str), f"{relative_path} not findable in test env"
    digest = hashlib.sha384(Path(path).read_bytes()).digest()
    return f"sha384-{base64.b64encode(digest).decode('ascii')}"


@pytest.fixture(autouse=True)
def _clear_sri_cache():
    sri_tag._cache.clear()
    yield
    sri_tag._cache.clear()


def test_sri_for_returns_attribute_when_file_present():
    expected = _expected_digest("css/app.css")
    rendered = Template("{% load sri %}{% sri_for 'css/app.css' %}").render(Context())
    assert rendered == f' integrity="{expected}"'


def test_sri_for_returns_empty_string_for_missing_file():
    """Missing assets must not break the render — the page should
    still ship without an integrity hint instead of 500."""
    rendered = Template("{% load sri %}{% sri_for 'css/does-not-exist.css' %}").render(Context())
    assert rendered == ""


def test_sri_for_caches_until_mtime_changes(tmp_path):
    """Repeat calls for the same file are served from cache. When the
    file is rewritten (new mtime), the next call re-hashes — dev
    edits and post-deploy collectstatic both invalidate naturally."""
    fake = tmp_path / "fake.css"
    fake.write_bytes(b"body { color: red; }")
    first = sri_tag._compute_sri(str(fake))

    cached_mtime, cached_digest = sri_tag._cache[str(fake)]
    assert cached_digest == first

    second = sri_tag._compute_sri(str(fake))
    assert second == first
    assert sri_tag._cache[str(fake)] == (cached_mtime, cached_digest)

    import os
    # Rewrite FIRST, then force a distinctly-different mtime. Doing utime
    # before write_bytes was flaky: the write reset mtime back to "now",
    # which on a coarse-resolution filesystem could equal cached_mtime and
    # leave the cache un-invalidated. Setting mtime last makes it deterministic.
    fake.write_bytes(b"body { color: green; }")
    os.utime(fake, (cached_mtime + 5, cached_mtime + 5))
    refreshed = sri_tag._compute_sri(str(fake))
    assert refreshed != first
    assert sri_tag._cache[str(fake)][1] == refreshed


def test_sri_digest_matches_sha384_of_file_bytes():
    """The digest the tag emits MUST match an independently computed
    sha384 of the file bytes. If a refactor swaps the algorithm or
    encoding, browsers would silently fail SRI checks; this test
    catches that."""
    path = finders.find("js/app.js")
    assert isinstance(path, str)
    raw = Path(path).read_bytes()
    expected = base64.b64encode(hashlib.sha384(raw).digest()).decode("ascii")
    rendered = Template("{% load sri %}{% sri_for 'js/app.js' %}").render(Context())
    assert f"sha384-{expected}" in rendered


@pytest.mark.django_db
def test_base_template_emits_integrity_for_own_css_and_js(client):
    """End-to-end: a real page render carries integrity on both
    project-owned bundles loaded by base.html."""
    response = client.get("/")
    body = response.content.decode("utf-8")

    css_digest = _expected_digest("css/app.css")
    js_digest = _expected_digest("js/app.js")

    assert f'href="/static/css/app.css" integrity="{css_digest}"' in body
    assert f'src="/static/js/app.js" integrity="{js_digest}"' in body
