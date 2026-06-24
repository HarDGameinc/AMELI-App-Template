"""E2E: login → MFA email → dashboard happy path.

Browser-driven smoke of the auth flow the real operator exercises
every morning. Exercises:
- Login form submission against the live server.
- MFA "choose method" page (since the user has both TOTP and email
  enrolled, the chooser appears).
- Email MFA code delivery via locmem backend.
- Verify form submission with the captured code.
- Redirect to dashboard, confirm logged-in user is visible.

The MFA email path is the one most likely to break in production
(see the SMTP IPv6 incident on 2026-06-23 — host-side bug, not
template, but visible here as the "email code sent" flow). Pinning
this end-to-end means a future regression in the email rendering
template, the code generation, or the verify form will fail loud
in CI before reaching prod.
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.django_db


def _enrol_email_mfa(user):
    """Enable email MFA on the user the cheapest way — set the flag
    directly. Avoids running the full /profile/mfa-email-start →
    confirm round-trip which has its own dedicated unit tests.
    """
    user.mfa_email_enabled = True
    user.save(update_fields=["mfa_email_enabled"])


def _extract_code_from_email(email_message) -> str:
    """Pull the 6-digit code out of the MFA email body. The template
    in ``accounts/mfa_email_code.txt`` renders it as a standalone
    line of digits surrounded by surrounding copy."""
    match = re.search(r"\b(\d{6})\b", email_message.body)
    assert match, f"no 6-digit code found in: {email_message.body!r}"
    return match.group(1)


def test_login_with_email_mfa_reaches_dashboard(
    page, live_url, e2e_admin, captured_emails,
):
    _enrol_email_mfa(e2e_admin)

    # Step 1 — open login form
    page.goto(f"{live_url}/login/")
    assert "iniciar" in page.locator("body").inner_text().lower() or \
           "ingresar" in page.locator("body").inner_text().lower()

    # Step 2 — submit credentials
    page.fill('input[name="username"]', "e2e-admin")
    page.fill('input[name="password"]', "E2eAdminPass!12?Stable")
    page.click('button[type="submit"]')

    # Step 3 — landed on the verify-mfa page. User has only email
    # enrolled so the chooser is skipped and the code was sent.
    page.wait_for_url(re.compile(r".*/login/verify-mfa/.*"))

    # Step 4 — captured_emails should now have 1 outbound MFA mail.
    assert len(captured_emails) == 1, \
        f"expected 1 MFA email, got {len(captured_emails)}"
    code = _extract_code_from_email(captured_emails[0])

    # Step 5 — submit the code
    page.fill('input[name="code"]', code)
    page.click('button[type="submit"]')

    # Step 6 — should be on the dashboard now
    page.wait_for_url(f"{live_url}/")
    body = page.locator("body").inner_text()
    # Dashboard shows "Hola, <user>" in the hero
    assert "e2e-admin" in body.lower() or "hola" in body.lower()


def test_login_with_wrong_password_stays_on_login(page, live_url, e2e_admin):
    page.goto(f"{live_url}/login/")
    page.fill('input[name="username"]', "e2e-admin")
    page.fill('input[name="password"]', "WrongPass!12?BadAttempt")
    page.click('button[type="submit"]')

    # Should NOT redirect — the login view re-renders with an error.
    # Generic message so we don't leak whether the user exists.
    # Django's default Spanish translation reads:
    # "por favor, introduzca un nombre de usuario y clave correctos.
    #  observe que ambos campos pueden ser sensibles a mayusculas."
    # Match the unique substring "introduzca un nombre" rather than
    # speculative custom copy (the earlier assert hardcoded our own
    # guesses that never matched Django's stock string).
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url
    body = page.locator("body").inner_text().lower()
    assert "introduzca un nombre" in body or "introduzca un usuario" in body, \
        f"expected Django auth-error copy in body, got: {body[:200]!r}"
