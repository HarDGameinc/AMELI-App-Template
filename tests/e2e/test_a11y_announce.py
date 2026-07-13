"""E2E: a client-side pagination/filter swap announces to the live region.

Part of the aria-live announcement audit (AGENTS.md → Testing gaps). The
admin panels swap their content in place via ``app.js`` (``swapPanelTo``)
instead of a full reload; ``aria-busy`` alone does not tell a screen reader
the new content arrived. This test proves the swap writes a concise summary
into the global ``#a11y-live`` region so assistive tech announces it.

Trigger: changing a page-size ``<select>`` always reissues the swap,
independent of how much data exists, so the test needs no seeded volume.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _login_no_mfa(page, live_url, user) -> None:
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "E2eAdminPass!12?Stable")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_url}/profile/**")


def test_pagination_swap_announces_to_live_region(page, live_url, e2e_admin):
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/admin/")

    live = page.locator("#a11y-live")
    live.wait_for(state="attached")
    assert live.inner_text() == "", "live region should start empty"

    # Pick a page-size option different from the current one so the change
    # event fires and a swap is issued regardless of the data volume.
    select = page.locator("select[data-page-size]").first
    select.wait_for(state="attached")
    values = select.evaluate("el => Array.from(el.options).map(o => o.value)")
    current = select.input_value()
    other = next((v for v in values if v != current), None)
    assert other is not None, "page-size select needs at least two options"
    select.select_option(other)

    # After the swap the region carries the panel's result summary
    # ("Mostrando …" / "Sin resultados"), proving announce() ran.
    page.wait_for_function(
        "document.getElementById('a11y-live').textContent.trim().length > 0",
        timeout=5000,
    )
    announced = page.locator("#a11y-live").inner_text().strip()
    assert announced, "swap did not announce anything to the live region"
    assert ("Mostrando" in announced) or ("resultados" in announced), (
        f"unexpected announcement text: {announced!r}"
    )
