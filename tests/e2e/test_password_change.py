"""E2E: change password from profile + re-login with the new one.

Pins the full password rotation flow end-to-end:
- Profile page → security tab → change password form.
- Submit current + new password (twice).
- Logout (forced by Django on password change to invalidate other
  sessions).
- Login with new password.

This catches a class of regressions where the password hasher
config drifts (e.g. argon2 params bumped without backwards-compat
fallback) or where the change-password form skips a validation
step. Unit tests cover the form / view pieces in isolation; this
e2e wires them together.
"""
from __future__ import annotations

import re

import pytest


pytestmark = pytest.mark.django_db


def _login_no_mfa(page, live_url, username, password):
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_url}/")


def test_change_password_then_login_with_new_password(
    page, live_url, e2e_admin,
):
    old_password = "E2eAdminPass!12?Stable"
    new_password = "NewE2ePass!34?DifferentStrong"

    _login_no_mfa(page, live_url, e2e_admin.username, old_password)

    # Profile + security tab
    page.goto(f"{live_url}/profile/#profile-tab-security")
    page.wait_for_load_state("networkidle")

    # Change-password form is inside the security tab
    page.fill('input[name="current_password"]', old_password)
    page.fill('input[name="new_password1"]', new_password)
    page.fill('input[name="new_password2"]', new_password)
    page.locator(
        'form[action*="password"] button[type="submit"]'
    ).first.click()
    page.wait_for_load_state("networkidle")

    # Django auth flow may force a re-login after password change;
    # either way the OLD password should no longer work.
    # Navigate to logout to ensure a clean slate.
    page.goto(f"{live_url}/logout/")
    page.wait_for_load_state("networkidle")

    # Attempt login with the OLD password — should fail
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', e2e_admin.username)
    page.fill('input[name="password"]', old_password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url, "old password must NOT work after change"

    # Now the NEW password works
    page.fill('input[name="username"]', e2e_admin.username)
    page.fill('input[name="password"]', new_password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    # Lands either on dashboard (no MFA enrolled) or on verify-mfa
    # (if the test setup gave the user MFA). e2e_admin has no MFA
    # so dashboard is expected.
    assert page.url.rstrip("/") in (live_url.rstrip("/"), f"{live_url}/"), \
        f"expected dashboard, landed at {page.url}"
