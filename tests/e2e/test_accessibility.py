"""E2E accessibility smoke — axe-core (WCAG 2.1 A/AA) on the key pages.

Closes the "no accessibility tests" gap listed in `AGENTS.md`. Approach
that fits the stack (no new pip dep, no lockfile change): the axe-core
engine is vendored as a test asset (`tests/e2e/vendor/axe.min.js`,
MPL-2.0) and injected into the live page via Playwright's `page.evaluate`
— which runs over the CDP channel and so bypasses the app's strict CSP
without relaxing it.

Bar: fail on the two actionable impact tiers (**critical**, **serious**).
`moderate` / `minor` findings are surfaced in the assertion message when a
test fails but do not, on their own, break the build — that keeps the
gate meaningful without chasing every cosmetic nit on day one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

_AXE_SOURCE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text(encoding="utf-8")

# WCAG 2.1 Level A + AA — the standard conformance target.
_WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

# Impact tiers that break the build. axe ranks findings
# minor < moderate < serious < critical; we gate on the top two.
_BLOCKING_IMPACTS = {"critical", "serious"}


def _login_no_mfa(page, live_url, user) -> None:
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "E2eAdminPass!12?Stable")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_url}/profile/**")


def _run_axe(page) -> list[dict]:
    """Inject axe-core and analyse the current document. Returns the raw
    violations list (each: id, impact, help, nodes[])."""
    page.evaluate(_AXE_SOURCE)
    results = page.evaluate(
        """async () => await axe.run(document, {
            runOnly: { type: 'tag', values: %s },
            resultTypes: ['violations']
        })"""
        % str(_WCAG_TAGS).replace("'", '"')
    )
    return results["violations"]


def _format(violations: list[dict]) -> str:
    lines = []
    for v in violations:
        first_targets = []
        for node in v.get("nodes", [])[:3]:
            target = node.get("target", [])
            first_targets.append(target[0] if target else "?")
        lines.append(
            f"  [{v.get('impact')}] {v['id']}: {v.get('help')}"
            f"  ({v.get('nodes', []).__len__()} node(s): {', '.join(first_targets)})"
        )
    return "\n".join(lines)


def _assert_no_blocking_a11y(page, where: str) -> None:
    violations = _run_axe(page)
    blocking = [v for v in violations if v.get("impact") in _BLOCKING_IMPACTS]
    if blocking:
        other = [v for v in violations if v not in blocking]
        msg = f"axe found critical/serious a11y violations on {where}:\n" + _format(blocking)
        if other:
            msg += "\n(also, non-blocking moderate/minor:\n" + _format(other) + ")"
        raise AssertionError(msg)


def test_login_page_accessibility(page, live_url):
    page.goto(f"{live_url}/login/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, "/login/")


def test_dashboard_accessibility(page, live_url, e2e_admin):
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, "/ (dashboard)")


def test_profile_page_accessibility(page, live_url, e2e_admin):
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/profile/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, "/profile/")


def test_admin_panel_accessibility(page, live_url, e2e_admin):
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/admin/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, "/admin/")
