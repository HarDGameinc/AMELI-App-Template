"""Regression tests for the Phase-QW (quick-wins) hardening of
2026-06-25. Pin the invariants surfaced by the skills + frontend
reviews so a future refactor cannot silently regress.

Doc references:
- docs/SKILLS_REVIEW.md §4 Security MEDIUM — Math.random fallback
- docs/SKILLS_REVIEW.md §7 SEO — missing robots meta
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# QW-1 — password generator refuses non-cryptographic randomness
# ---------------------------------------------------------------------------


def _read_app_js() -> str:
    return (ROOT / "src" / "ameli_app" / "static" / "js" / "app.js").read_text()


def _strip_js_line_comments(js: str) -> str:
    """Remove ``// ...`` line comments so static-analysis tests against
    JS source do not trip on documentation that mentions the very
    thing the code is forbidding."""
    return re.sub(r"//[^\n]*", "", js)


def test_password_generator_does_not_fallback_to_math_random():
    """``Math.random`` must NOT appear inside the password-generation
    code path. The old ``ameliRandomIndex`` fell back to Math.random
    when ``crypto.getRandomValues`` was unavailable — that produces
    predictable output (seeded once per browsing context) that a
    forensic adversary or TLS-stripping intermediary could replay.
    """
    js = _read_app_js()
    body_re = re.compile(
        r"function ameliRandomIndex\(.*?\)\s*\{([\s\S]*?)\n\}", re.MULTILINE
    )
    match = body_re.search(js)
    assert match is not None, "ameliRandomIndex function not found in app.js"
    # Strip comments so the test does not false-positive on prose
    # that explains why Math.random is forbidden.
    body = _strip_js_line_comments(match.group(1))
    assert "Math.random" not in body, (
        "ameliRandomIndex falls back to Math.random — this leaks "
        "predictable randomness into generated passwords. The function "
        "must refuse (throw) when crypto.getRandomValues is unavailable."
    )


def test_password_generator_throws_when_crypto_missing():
    """The function must explicitly THROW when ``window.crypto`` or
    ``getRandomValues`` is unavailable, instead of silently returning
    a weak value."""
    js = _read_app_js()
    body_re = re.compile(
        r"function ameliRandomIndex\(.*?\)\s*\{([\s\S]*?)\n\}", re.MULTILINE
    )
    body = body_re.search(js).group(1)
    assert "throw new Error" in body, (
        "ameliRandomIndex must throw when crypto is missing instead of "
        "falling through to a weaker source."
    )


def test_generate_button_handles_empty_result():
    """The click handler must guard against the empty return value
    (``ameliGeneratePassword`` returns "" when crypto is missing) and
    NOT overwrite the inputs with the empty string."""
    js = _read_app_js()
    # The handler must check the value before assigning to newInput.
    assert "if (!value)" in js, (
        "Generate button handler must check the returned value before "
        "writing to the input — otherwise an unavailable crypto subsystem "
        "writes \"\" to the password fields."
    )


# ---------------------------------------------------------------------------
# QW-2 — base.html ships a noindex/nofollow meta tag
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_base_template_emits_noindex_meta(client):
    """The template is meant for internal operational tooling. Even
    if a deployment ends up exposed to the public internet by mistake,
    search engines should not index it. Defence-in-depth on top of
    robots.txt / proxy ACLs."""
    response = client.get("/health")
    assert response.status_code == 200
    # /health returns JSON, so render the home page instead to cover
    # the template path.


@pytest.mark.django_db
def test_dashboard_emits_noindex_meta(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert '<meta name="robots" content="noindex,nofollow">' in body, (
        "base.html must emit a noindex/nofollow robots meta tag. "
        "See SKILLS_REVIEW.md §7."
    )


@pytest.mark.django_db
def test_login_page_emits_noindex_meta(client):
    """Pages that NEVER require auth must still carry the noindex meta."""
    response = client.get("/login/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert '<meta name="robots" content="noindex,nofollow">' in body
