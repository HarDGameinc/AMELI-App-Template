"""Regression coverage for Phase 1 #3 (a11y + dark mode wiring)
of the 2026-06-20 roadmap.

Before: ``base.html`` ignored ``active_theme`` (passed by
``account_navigation`` context processor) so the user's saved
``theme_preference`` had no visual effect. There were also no
skip-link, no aria-live on the messages region, no main-content
landmark, and no reduced-motion handling.

After: ``data-theme=...`` set on ``<html>`` when the user has a
preference, skip-link before the header, ``id=main-content`` on
``<main>``, ``aria-live=polite`` on the messages region, CSS
``@media (prefers-reduced-motion: reduce)`` block.

Tests render base.html through the Django template engine with
representative contexts and assert the markup carries the
expected a11y / theme attributes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.template.loader import get_template
from django.test import RequestFactory

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "src" / "ameli_app" / "static" / "css" / "app.css"


def _make_request():
    rf = RequestFactory()
    request = rf.get("/")
    # ``account_navigation`` context processor needs ``request.user``;
    # AnonymousUser keeps the test scope at the unauthenticated case
    # which is enough for testing base.html scaffolding.
    request.user = AnonymousUser()
    request.maintenance_state = type("MS", (), {"active": False, "message": ""})()
    return request


def _render(active_theme: str = "") -> str:
    """Render base.html with the minimum context needed."""
    request = _make_request()
    context = {
        "request": request,
        "active_theme": active_theme,
        "current_user": None,
        "can_access_admin": False,
        "app_name": "AMELI App Template",
        "docs_enabled": False,
        "redoc_enabled": False,
        "csp_nonce": "test-nonce",
        "messages": [],
    }
    template = get_template("base.html")
    return template.render(context, request)


# ---------------------------------------------------------------------------
# Dark mode wiring
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_html_carries_no_data_theme_when_user_has_no_preference():
    body = _render(active_theme="")
    # When the user has no preference, ``data-theme`` MUST be absent
    # so the @media (prefers-color-scheme: dark) fallback kicks in.
    assert 'data-theme="' not in body, \
        "data-theme must NOT be set when active_theme is empty — let prefers-color-scheme decide"


@pytest.mark.django_db
def test_html_carries_data_theme_light_when_user_picked_light():
    body = _render(active_theme="light")
    assert '<html lang="es" data-theme="light"' in body


@pytest.mark.django_db
def test_html_carries_data_theme_dark_when_user_picked_dark():
    body = _render(active_theme="dark")
    assert '<html lang="es" data-theme="dark"' in body


@pytest.mark.django_db
def test_color_scheme_meta_mirrors_active_theme():
    """The ``<meta name="color-scheme">`` hint tells native widgets
    (scrollbar, native form controls) which palette to use. Without
    it a dark page gets a white scrollbar on Chrome.
    """
    for theme in ("light", "dark"):
        body = _render(active_theme=theme)
        assert f'<meta name="color-scheme" content="{theme}">' in body


# ---------------------------------------------------------------------------
# a11y essentials
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_skip_link_renders_before_header():
    body = _render()
    skip_idx = body.find('class="skip-link"')
    header_idx = body.find("<header>")
    assert 0 < skip_idx < header_idx, \
        "skip-link must be the first focusable element, before <header>"
    assert 'href="#main-content"' in body, \
        "skip-link must target #main-content"


@pytest.mark.django_db
def test_main_content_landmark_carries_id_and_tabindex():
    """The skip-link target must be reachable (id) AND
    programmatically focusable (tabindex=-1) so screen reader users
    land on the right region.
    """
    body = _render()
    assert 'id="main-content"' in body
    assert 'tabindex="-1"' in body


@pytest.mark.django_db
def test_messages_region_has_aria_live():
    """Flash messages must announce themselves to screen readers
    without interrupting the user (polite, not assertive).
    """
    request = _make_request()
    template = Template(
        '{% extends "base.html" %}'
        '{% block content %}body{% endblock %}'
    )
    rendered = template.render(Context({
        "request": request,
        "active_theme": "",
        "current_user": None,
        "can_access_admin": False,
        "app_name": "AMELI App Template",
        "docs_enabled": False,
        "redoc_enabled": False,
        "csp_nonce": "",
        "messages": ["test message"],
    }))
    assert 'role="status"' in rendered
    assert 'aria-live="polite"' in rendered


# ---------------------------------------------------------------------------
# CSS supports
# ---------------------------------------------------------------------------

def test_css_has_skip_link_styles():
    css = CSS.read_text()
    assert ".skip-link" in css
    assert ".skip-link:focus" in css


def test_css_has_focus_visible_rule():
    """Without an explicit :focus-visible rule, a custom outline:none
    deeper in the cascade can defeat keyboard navigation.
    """
    css = CSS.read_text()
    assert ":focus-visible" in css
    assert "outline:2px solid" in css or "outline: 2px solid" in css


def test_css_honors_prefers_reduced_motion():
    css = CSS.read_text()
    assert "@media (prefers-reduced-motion: reduce)" in css
