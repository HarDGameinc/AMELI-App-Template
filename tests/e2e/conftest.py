"""Pytest fixtures for the Playwright e2e suite (mini-roadmap #12).

Mini-roadmap #12 closes the loop on browser-driven smoke testing
the template's happy paths: login + MFA + avatar upload + password
change. Pure Python — ``pytest-playwright`` drives a headless
Chromium instance against ``pytest-django``'s ``live_server`` fixture
so the same Django process tests run against handles real HTTP
requests over a real socket.

The fixtures here keep the cost of each test bounded:
- ``e2e_admin`` creates a fresh User row per test with no MFA
  configured. Tests that need MFA enrol it explicitly via
  ``enrol_email_mfa()`` / TOTP helpers.
- ``page`` (from pytest-playwright) opens a clean browser context
  per test so cookies / localStorage do NOT leak between cases.
- ``base_url`` is the ``live_server`` URL so test code writes
  ``page.goto(f"{base_url}/login/")`` without hardcoding ports.

Tests in this directory are marked ``@pytest.mark.e2e`` so the
default ``pytest`` invocation can skip them (they need chromium +
~5x the runtime of a unit test). CI runs them in a dedicated job.
"""
from __future__ import annotations

import pytest
from django.core import mail


def pytest_collection_modifyitems(config, items):
    """Skip every test in this directory unless explicitly requested
    via ``pytest tests/e2e/`` or ``pytest --run-e2e``. Prevents the
    e2e runtime cost (~5-10x a unit test, requires chromium binary)
    from leaking into the default unit-test suite.

    Detection: an invocation that lists ``tests/e2e`` somewhere in
    its args (positional path or part of a longer expression) is
    treated as opt-in. The ``--run-e2e`` flag is the explicit
    alternative for CI / scripted runs.
    """
    if config.getoption("--run-e2e"):
        return
    invoked = " ".join(str(arg) for arg in config.invocation_params.args)
    if "tests/e2e" in invoked or "tests\\e2e" in invoked:
        return
    skip = pytest.mark.skip(
        reason="e2e suite (use --run-e2e or pytest tests/e2e/)",
    )
    for item in items:
        if "tests/e2e/" in str(item.path).replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture()
def live_url(live_server) -> str:
    """Live URL of the Django test server (e.g. http://localhost:43217).

    ``pytest-django``'s ``live_server`` boots a real WSGI server in a
    background thread for the duration of the test. Faster than
    docker-compose-ing the whole stack; gives us a real HTTP endpoint
    Playwright can navigate to.

    Named ``live_url`` (not ``base_url``) to avoid collision with the
    session-scoped ``base_url`` fixture from ``pytest-base-url`` that
    ``pytest-playwright`` pulls in transitively.
    """
    return live_server.url


@pytest.fixture()
def e2e_admin(transactional_db, django_user_model):
    """Fresh superadmin user with a known password and no MFA.

    Each test gets its own user row, isolated from siblings. The
    password is long enough to satisfy the ASVS policy and stable
    enough that the test can re-type it on a re-auth screen.

    Uses ``transactional_db`` (not ``db``) because ``live_server``
    runs the Django app in a SEPARATE THREAD with its own connection.
    The savepoint-mode ``db`` fixture wraps the test in an uncommitted
    transaction → the user row is invisible to that thread → the
    login form rejects every credential → tests time out waiting for
    a dashboard navigation that never happens. ``transactional_db``
    truncates instead of rolling back, so committed rows are visible
    cross-thread. Surfaced 2026-06-23 e2e wire test (run
    ``28056559098``).
    """
    user = django_user_model.objects.create_user(
        username="e2e-admin",
        email="e2e-admin@example.com",
        password="E2eAdminPass!12?Stable",
        role=django_user_model.ROLE_SUPERADMIN,
        must_change_password=False,
    )
    return user


@pytest.fixture()
def captured_emails(settings):
    """Switch the email backend to the in-memory ``locmem`` backend
    and yield ``mail.outbox`` so tests can read the MFA code that
    was 'sent' to the user without touching SMTP.

    Implemented as a fixture (not autouse) so tests that DO want to
    exercise the real backend can opt out by not requesting it.
    """
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox.clear()
    yield mail.outbox
    mail.outbox.clear()
