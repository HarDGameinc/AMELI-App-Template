"""E2E: avatar upload → dashboard + profile hero shows the image.

Mirrors the wire test the operator ran manually on 2026-06-22.
Locks in the regression the 21-jun handoff §7 listed as a
follow-up: "tests de regresion visual del avatar". This is the
e2e portion of that — no pixel diffs (those would need baseline
management), just the structural assertion that the rendered
HTML carries ``<img class="profile-avatar-image">`` instead of
the initials placeholder.
"""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest


pytestmark = pytest.mark.django_db


def _login_no_mfa(page, live_url, user):
    """Tests in this file don't care about MFA; jump straight to
    the authenticated state by logging in as a user without MFA
    enrolled."""
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "E2eAdminPass!12?Stable")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_url}/")


def _make_test_png(tmp_path: Path) -> Path:
    """Build a minimal 8x8 RGB PNG via Pillow so the avatar upload
    form accepts it (whitelist enforces image MIME + Pillow open
    succeeds)."""
    from PIL import Image

    path = tmp_path / "e2e-avatar.png"
    img = Image.new("RGB", (8, 8), color=(150, 50, 100))
    img.save(path, format="PNG")
    return path


def test_avatar_upload_renders_image_in_hero(
    page, live_url, e2e_admin, tmp_path,
):
    _login_no_mfa(page, live_url, e2e_admin)

    # Pre-upload: dashboard hero shows initials (no <img>)
    body_pre = page.locator("body").inner_text()
    assert "E" in body_pre, "initials should show pre-upload"
    assert page.locator("img.profile-avatar-image").count() == 0

    # Navigate to profile
    page.goto(f"{live_url}/profile/")
    page.wait_for_load_state("networkidle")

    # Find the avatar form + upload
    png_path = _make_test_png(tmp_path)
    page.set_input_files('input[name="avatar"]', str(png_path))
    page.locator('form#avatar-form button[type="submit"]').click()

    # After submit we 302-redirect back to /profile/ with a flash
    page.wait_for_url(re.compile(r".*/profile/.*"))
    page.wait_for_load_state("networkidle")

    # Now hero should show <img>, not initials
    assert page.locator("img.profile-avatar-image").count() >= 1, \
        "hero should render <img class=profile-avatar-image> post-upload"

    # And navigating to dashboard, same thing
    page.goto(f"{live_url}/")
    page.wait_for_load_state("networkidle")
    assert page.locator("img.profile-avatar-image").count() >= 1, \
        "dashboard hero should also render <img> post-upload"

    # And the top-right menu chip
    chip_imgs = page.locator("img.menu-avatar-image").count()
    assert chip_imgs >= 1, "top-right menu chip should render <img> too"
