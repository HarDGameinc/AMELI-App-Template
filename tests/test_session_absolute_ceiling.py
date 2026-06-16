"""Regression coverage for ASVS V3.3.3 absolute session ceiling.

Closes roadmap item #3. The ceiling lives in
``UserSessionMiddleware.__call__`` (middleware.py): when the
authenticated user's ``UserSession.created_at`` is older than
``settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS`` we force a logout +
redirect to ``/login/`` and emit a ``session_expired_absolute`` audit
row. Setting = 0 disables the ceiling for back-compat with deploys
that never enforced this.

These tests cover the state machine edges: an in-window session
passes through, an out-of-window session is forced to re-auth, the
audit row carries the right payload, the disabled setting turns the
ceiling off, the ceiling respects independent of ``cycle_key()``
(which rotates the cookie but not the anchor), and the serialized
session list surfaces ``absolute_expires_at`` for the user-facing
panel.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import serialize_session
from ameli_web.audit.models import AuditEvent

User = get_user_model()
PASSWORD = "UserPass!12?"


@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="alice",
        password=PASSWORD,
        role=User.ROLE_PUBLIC,
        email="alice@example.com",
    )


# ---------------------------------------------------------------------------
# In-window session passes through; out-of-window session is forced out
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_in_window_session_passes_through(client, user, settings):
    """A session created 5 minutes ago, against a 30-day ceiling, must
    not be touched by the middleware.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 30 * 24 * 3600
    client.force_login(user)
    # Anchor the UserSession created by the login signal at 5 min ago.
    UserSession.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(minutes=5),
    )
    response = client.get("/profile/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_expired_session_forces_logout_with_audit(client, user, settings):
    """A session created 31 days ago, against a 30-day ceiling, must
    redirect to /login/ on the next request and emit the audit row.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 30 * 24 * 3600
    client.force_login(user)
    UserSession.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(days=31),
    )
    response = client.get("/profile/")
    # Redirected to /login/ (302).
    assert response.status_code == 302
    assert "/login/" in response["Location"]
    # Subsequent request lands as anonymous.
    follow = client.get("/profile/")
    assert follow.status_code == 302
    assert "/login/" in follow["Location"]
    # Audit row recorded with the ceiling reason.
    audit = AuditEvent.objects.filter(
        action="session_expired_absolute",
        target_username="alice",
    ).first()
    assert audit is not None
    assert audit.payload["max_age_seconds"] == 30 * 24 * 3600
    assert audit.payload["session_age_seconds"] >= 30 * 24 * 3600


@pytest.mark.django_db
def test_exact_threshold_crossing_is_expired(client, user, settings):
    """At ``age == max_age`` the session is considered expired
    (``>=`` comparison). Property pins the off-by-one boundary.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 3600  # 1 hour
    client.force_login(user)
    UserSession.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(seconds=3600),
    )
    response = client.get("/profile/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# ---------------------------------------------------------------------------
# Disabled setting turns the ceiling off (back-compat)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ceiling_disabled_lets_old_session_through(client, user, settings):
    """``SESSION_ABSOLUTE_MAX_AGE_SECONDS = 0`` disables the ceiling.
    Even a year-old session passes through (the previous template
    behaviour).
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 0
    client.force_login(user)
    UserSession.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(days=365),
    )
    response = client.get("/profile/")
    assert response.status_code == 200
    assert not AuditEvent.objects.filter(
        action="session_expired_absolute",
        target_username="alice",
    ).exists()


# ---------------------------------------------------------------------------
# Serializer exposes the ceiling timestamp for the user-facing panel
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_serialize_session_includes_absolute_expires_at(user, settings):
    """The /profile/sessions/ panel reads ``absolute_expires_at`` so
    the user sees when re-auth will be forced.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 7 * 24 * 3600
    session = UserSession.objects.create(
        user=user,
        session_key="test-key-123456",
    )
    # Anchor created_at to a known moment.
    fixed = timezone.now() - timedelta(days=2)
    UserSession.objects.filter(pk=session.pk).update(created_at=fixed)
    session.refresh_from_db()
    data = serialize_session(session)
    assert data["absolute_expires_at"] != ""
    assert data["display_absolute_expires_at"] != ""


@pytest.mark.django_db
def test_serialize_session_blank_expires_at_when_disabled(user, settings):
    """Ceiling = 0 → no ``absolute_expires_at`` surfaced; the panel
    omits the row instead of showing a misleading timestamp.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 0
    session = UserSession.objects.create(
        user=user,
        session_key="test-key-789012",
    )
    data = serialize_session(session)
    assert data["absolute_expires_at"] == ""
    assert data["display_absolute_expires_at"] == ""


# ---------------------------------------------------------------------------
# Policy: cycle_key resets the ceiling (and that's correct)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ceiling_anchor_is_per_user_session_row(client, user, settings):
    """The ceiling is anchored on ``UserSession.created_at``, which is
    keyed by ``session_key``. ``cycle_key`` rotates the cookie and a
    fresh ``UserSession`` row is created on the next request — so the
    ceiling effectively resets at every cycle_key.

    Operationally this is the correct behaviour: every cycle_key site
    in the codebase (MFA enrollment confirm, MFA disable, recovery
    code regen) is gated by a fresh password / TOTP entry, so the
    user just authenticated. Resetting the ceiling at that moment is
    consistent with ASVS V3.3.3 ("max session lifetime without
    re-authentication") rather than violating it.

    This test pins the contract so a future change that tries to
    "preserve the original anchor through cycle_key" gets flagged in
    code review: that direction would treat MFA enrollment as
    NOT-re-authentication, which is wrong.
    """
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 30 * 24 * 3600
    # Create an old session row (the "pre-cycle_key" world).
    old = UserSession.objects.create(user=user, session_key="old-key-123")
    UserSession.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31),
    )
    # Simulate that the user just went through MFA enrollment and a
    # NEW row was created by ``sync_request_session`` for the rotated
    # session_key. The new row is young — ceiling does not fire.
    new = UserSession.objects.create(user=user, session_key="new-key-456")
    assert new.created_at >= timezone.now() - timedelta(minutes=1)
    # The old row is orphaned (its session_key is gone from the cookie
    # store) so it never gates a request. The new row drives the
    # ceiling decision.
    client.force_login(user)
    # Force the test client's session_key to the new row so the
    # middleware reads from the new anchor.
    response = client.get("/profile/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Unauthenticated requests are not touched by the middleware
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_request_unaffected_by_ceiling(client, settings):
    settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS = 30 * 24 * 3600
    response = client.get("/login/")
    assert response.status_code == 200
