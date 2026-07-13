"""The global screen-reader live region ships on every page.

Part of the aria-live announcement audit (AGENTS.md → Testing gaps). The
client-side pagination/filter swaps in ``app.js`` announce their result into
``#a11y-live`` (see ``base.html``); this fast template-level test guards that
the region — with the right ARIA wiring — is actually present in the rendered
page, so the JS ``announce()`` has a target. The end-to-end proof that a swap
populates it lives in ``tests/e2e/test_a11y_live_region.py``.
"""
from __future__ import annotations

import re

import pytest


@pytest.mark.django_db
def test_base_template_ships_global_live_region(client):
    """An anonymous page (login) renders ``base.html`` and must carry the
    polite, atomic live region with a stable ``id`` the JS can target."""
    resp = client.get("/login/")
    assert resp.status_code == 200
    html = resp.content.decode()

    # Find the live-region element and assert its ARIA contract in one place.
    match = re.search(r"<div[^>]*\bid=\"a11y-live\"[^>]*>", html)
    assert match, "global #a11y-live region missing from base.html"
    tag = match.group(0)
    assert 'aria-live="polite"' in tag, "live region must be polite"
    assert 'role="status"' in tag, "live region should expose role=status"
    assert 'aria-atomic="true"' in tag, "whole message should be read, not a diff"
    assert 'class="visually-hidden"' in tag, "region is announced, not shown"
