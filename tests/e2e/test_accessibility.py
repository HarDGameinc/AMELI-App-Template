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


def _node_detail(node: dict) -> str:
    """One node's target + (for color-contrast) the fg/bg/ratio axe
    measured, so a failure message points straight at the fix."""
    target = node.get("target", [])
    sel = target[0] if target else "?"
    for check in node.get("any", []):
        data = check.get("data") or {}
        if "contrastRatio" in data:
            return (
                f"{sel}  (fg {data.get('fgColor')} on bg {data.get('bgColor')}"
                f" = {data.get('contrastRatio')}:1, need {data.get('expectedContrastRatio')})"
            )
    return sel


def _format(violations: list[dict]) -> str:
    lines = []
    for v in violations:
        details = [_node_detail(n) for n in v.get("nodes", [])[:4]]
        lines.append(
            f"  [{v.get('impact')}] {v['id']}: {v.get('help')}"
            f"  ({len(v.get('nodes', []))} node(s))"
        )
        lines.extend(f"      - {d}" for d in details)
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


# Both themes are checked: the palette has a light and a dark variant
# (auto-switched by ``prefers-color-scheme`` when the user leaves theme on
# "auto", which the e2e_admin fixture does). ``emulate_media`` drives that
# media feature so axe evaluates the actually-rendered colors.
_SCHEMES = ["light", "dark"]


@pytest.mark.parametrize("color_scheme", _SCHEMES)
def test_login_page_accessibility(page, live_url, color_scheme):
    page.emulate_media(color_scheme=color_scheme)
    page.goto(f"{live_url}/login/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, f"/login/ [{color_scheme}]")


@pytest.mark.parametrize("color_scheme", _SCHEMES)
def test_forgot_password_accessibility(page, live_url, color_scheme):
    page.emulate_media(color_scheme=color_scheme)
    page.goto(f"{live_url}/login/forgot/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, f"/login/forgot/ [{color_scheme}]")


@pytest.mark.parametrize("color_scheme", _SCHEMES)
def test_dashboard_accessibility(page, live_url, e2e_admin, color_scheme):
    page.emulate_media(color_scheme=color_scheme)
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, f"/ (dashboard) [{color_scheme}]")


@pytest.mark.parametrize("color_scheme", _SCHEMES)
def test_profile_page_accessibility(page, live_url, e2e_admin, color_scheme):
    page.emulate_media(color_scheme=color_scheme)
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/profile/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, f"/profile/ [{color_scheme}]")


@pytest.mark.parametrize("color_scheme", _SCHEMES)
def test_admin_panel_accessibility(page, live_url, e2e_admin, color_scheme):
    page.emulate_media(color_scheme=color_scheme)
    _login_no_mfa(page, live_url, e2e_admin)
    page.goto(f"{live_url}/admin/")
    page.wait_for_load_state("networkidle")
    _assert_no_blocking_a11y(page, f"/admin/ [{color_scheme}]")


# ---------------------------------------------------------------------------
# Keyboard navigation — axe can't test this; drive the keyboard directly.
# ---------------------------------------------------------------------------

def test_skip_link_is_first_tab_stop(page, live_url):
    """A keyboard user's first Tab must land on the skip link, which
    jumps to <main> — the standard bypass-block (WCAG 2.4.1)."""
    page.goto(f"{live_url}/login/")
    page.wait_for_load_state("networkidle")

    page.keyboard.press("Tab")
    first = page.evaluate(
        """() => {
            const el = document.activeElement;
            return { cls: el.className, href: el.getAttribute('href') };
        }"""
    )
    assert first["cls"] == "skip-link", f"first Tab stop was not the skip link: {first}"
    assert first["href"] == "#main-content", first

    # <main> must be focusable (tabindex=-1) so activating the link lands there.
    main_tabindex = page.get_attribute("#main-content", "tabindex")
    assert main_tabindex == "-1", f"#main-content tabindex is {main_tabindex!r}, expected -1"


def test_login_form_reachable_by_keyboard(page, live_url):
    """Tabbing through the login page must reach the username, password
    and submit control — no keyboard trap before the form."""
    page.goto(f"{live_url}/login/")
    page.wait_for_load_state("networkidle")

    reached = set()
    for _ in range(15):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => {
                const el = document.activeElement;
                return { name: el.getAttribute('name'), type: el.getAttribute('type'), tag: el.tagName };
            }"""
        )
        if info.get("name") == "username":
            reached.add("username")
        elif info.get("name") == "password":
            reached.add("password")
        elif info.get("type") == "submit" or info.get("tag") == "BUTTON":
            reached.add("submit")
        if {"username", "password", "submit"} <= reached:
            break
    assert {"username", "password", "submit"} <= reached, f"keyboard did not reach the form: {reached}"
