"""Tests for the data retention sweep run by the maintenance worker."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import (
    EmailChangeRequest,
    MFAEmailChallenge,
    OutboundEmail,
    ThrottleCounter,
    UserSession,
)
from ameli_web.accounts.services import run_retention_sweep
from ameli_web.audit.models import AuditEvent

User = get_user_model()


@pytest.fixture()
def user(db):
    return User.objects.create_user(username="r", password="RetenPass!12?")


def _push_back(model, pk, **fields):
    """Datetime fields like ``created_at`` are auto_now_add and ignored
    on save. To simulate old rows we have to ``update()`` explicitly."""
    model.objects.filter(pk=pk).update(**fields)


@pytest.mark.django_db
def test_retention_sweep_purges_old_revoked_sessions(user, settings):
    settings.AUDIT_HMAC_KEY = "k"
    old = UserSession.objects.create(
        user=user, session_key="old", revoked_at=timezone.now() - timedelta(days=60),
    )
    UserSession.objects.create(
        user=user, session_key="recent", revoked_at=timezone.now() - timedelta(days=5),
    )
    UserSession.objects.create(
        user=user, session_key="alive", revoked_at=None,
    )

    result = run_retention_sweep(sessions_revoked_max_age_days=30)
    assert result["ok"] is True
    assert result["counts"]["user_sessions"] == 1
    assert not UserSession.objects.filter(pk=old.pk).exists()
    # Recent and alive sessions survive.
    assert UserSession.objects.filter(session_key="recent").exists()
    assert UserSession.objects.filter(session_key="alive").exists()


@pytest.mark.django_db
def test_retention_sweep_purges_old_outbound_email_rows(settings):
    settings.AUDIT_HMAC_KEY = "k"
    old_sent = OutboundEmail.objects.create(
        subject="s", body="", to_emails=[],
        status=OutboundEmail.STATUS_SENT,
        next_retry_at=timezone.now(),
    )
    _push_back(OutboundEmail, old_sent.pk, updated_at=timezone.now() - timedelta(days=45))

    fresh_sent = OutboundEmail.objects.create(
        subject="s2", body="", to_emails=[],
        status=OutboundEmail.STATUS_SENT,
        next_retry_at=timezone.now(),
    )
    pending = OutboundEmail.objects.create(
        subject="s3", body="b", to_emails=["x@x"],
        status=OutboundEmail.STATUS_PENDING,
        next_retry_at=timezone.now(),
    )

    run_retention_sweep(outbound_email_sent_max_age_days=30)
    assert not OutboundEmail.objects.filter(pk=old_sent.pk).exists()
    assert OutboundEmail.objects.filter(pk=fresh_sent.pk).exists()
    # Pending row is never touched.
    assert OutboundEmail.objects.filter(pk=pending.pk).exists()


@pytest.mark.django_db
def test_retention_sweep_purges_throttle_counters(settings):
    settings.AUDIT_HMAC_KEY = "k"
    ThrottleCounter.objects.create(
        scope="login", key="x", window_start=timezone.now() - timedelta(days=3),
    )
    ThrottleCounter.objects.create(
        scope="login", key="y", window_start=timezone.now() - timedelta(minutes=5),
    )

    run_retention_sweep(throttle_counter_max_age_days=1)
    assert ThrottleCounter.objects.filter(key="x").exists() is False
    assert ThrottleCounter.objects.filter(key="y").exists() is True


@pytest.mark.django_db
def test_retention_sweep_keeps_pending_email_change_request(user, settings):
    settings.AUDIT_HMAC_KEY = "k"
    pending = EmailChangeRequest.objects.create(
        user=user, new_email="new@x", token_hash="t1",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    _push_back(EmailChangeRequest, pending.pk, created_at=timezone.now() - timedelta(days=90))

    resolved = EmailChangeRequest.objects.create(
        user=user, new_email="n2@x", token_hash="t2",
        expires_at=timezone.now() + timedelta(hours=1),
        confirmed_at=timezone.now() - timedelta(days=90),
    )
    _push_back(EmailChangeRequest, resolved.pk, created_at=timezone.now() - timedelta(days=90))

    run_retention_sweep(email_change_resolved_max_age_days=30)
    # The pending one stays — only resolved (confirmed/cancelled) gets
    # purged once aged enough.
    assert EmailChangeRequest.objects.filter(pk=pending.pk).exists()
    assert not EmailChangeRequest.objects.filter(pk=resolved.pk).exists()


@pytest.mark.django_db
def test_retention_sweep_purges_used_mfa_email_challenges(user, settings):
    settings.AUDIT_HMAC_KEY = "k"
    used = MFAEmailChallenge.objects.create(
        user=user, code_hash="h1",
        expires_at=timezone.now() - timedelta(minutes=1),
        used_at=timezone.now() - timedelta(minutes=1),
    )
    _push_back(MFAEmailChallenge, used.pk, created_at=timezone.now() - timedelta(days=14))

    unused = MFAEmailChallenge.objects.create(
        user=user, code_hash="h2",
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    run_retention_sweep(mfa_email_challenge_consumed_max_age_days=7)
    assert not MFAEmailChallenge.objects.filter(pk=used.pk).exists()
    assert MFAEmailChallenge.objects.filter(pk=unused.pk).exists()


@pytest.mark.django_db
def test_retention_sweep_prunes_audit_with_anchor_when_configured(settings):
    """audit_max_age_days = N deletes rows older than N days and writes
    a fresh anchor so ``verify-audit`` still walks the surviving tail
    from a known prev_hmac."""
    from ameli_web.accounts.services import record_audit, verify_audit_chain

    settings.AUDIT_HMAC_KEY = "k"
    old1 = record_audit("ancient_1")
    old2 = record_audit("ancient_2")
    _push_back(AuditEvent, old1.pk, created_at=timezone.now() - timedelta(days=400))
    _push_back(AuditEvent, old2.pk, created_at=timezone.now() - timedelta(days=400))

    # Fresh rows that must survive.
    record_audit("recent_1")
    record_audit("recent_2")

    result = run_retention_sweep(audit_max_age_days=365)
    assert result["counts"]["audit_events"] >= 2
    # Anchor row exists.
    assert AuditEvent.objects.filter(action="retention_audit_anchor").exists()
    # Chain still verifies clean post-prune.
    chain = verify_audit_chain()
    assert chain.get("ok") is True


@pytest.mark.django_db
def test_retention_sweep_records_audit_event_summarizing_counts(settings):
    settings.AUDIT_HMAC_KEY = "k"
    run_retention_sweep()
    audit = AuditEvent.objects.filter(action="retention_sweep").last()
    assert audit is not None
    assert "counts" in audit.payload
    assert "user_sessions" in audit.payload["counts"]


@pytest.mark.django_db
def test_maintenance_worker_invokes_retention(config_path):
    """The CLI ``maintenance`` command now runs the retention sweep."""
    from ameli_app.cli import main

    rc = main(["--config", str(config_path), "maintenance"])
    assert rc == 0
