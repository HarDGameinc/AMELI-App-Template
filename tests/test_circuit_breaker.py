"""Circuit breakers for external integrations — mini-roadmap #9
(2026-06-22).

Pins the breaker state machine and its three wiring points:
- AV (clamd): opens after N transport failures, fast-fails subsequent
  scans with ``("check_failed", "breaker_open")``.
- HIBP: opens after N failures, fast-allows passwords without
  network round-trip.
- SMTP queue: opens after N delivery failures, skips the entire
  batch without burning ``max_attempts`` budget on the rows.
"""
from __future__ import annotations

import time
from unittest.mock import patch
from urllib.error import URLError

import pytest

from ameli_web.accounts import av, validators
from ameli_web.accounts.circuit_breaker import CircuitBreaker

# ---------------------------------------------------------------------------
# Core state machine
# ---------------------------------------------------------------------------


def test_breaker_starts_closed():
    cb = CircuitBreaker(name="t", failure_threshold=3, cooldown_seconds=1.0)
    assert cb.allow() is True


def test_breaker_opens_after_threshold_failures():
    cb = CircuitBreaker(name="t", failure_threshold=3, cooldown_seconds=1.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.allow() is True, "still under threshold"
    cb.record_failure()
    assert cb.allow() is False, "opened at threshold"


def test_breaker_does_not_open_when_successes_interleave():
    """A single success resets the counter — breaker only opens on
    *consecutive* failures."""
    cb = CircuitBreaker(name="t", failure_threshold=3, cooldown_seconds=1.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert cb.allow() is True, "counter was reset on success"


def test_breaker_transitions_to_half_open_after_cooldown():
    cb = CircuitBreaker(name="t", failure_threshold=2, cooldown_seconds=0.05)
    cb.record_failure()
    cb.record_failure()
    assert cb.allow() is False
    time.sleep(0.06)
    assert cb.allow() is True, "cooldown elapsed → probe allowed"


def test_breaker_closes_on_successful_probe():
    cb = CircuitBreaker(name="t", failure_threshold=2, cooldown_seconds=0.05)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.06)
    cb.record_success()
    assert cb.allow() is True
    # And subsequent failures need the full threshold again
    cb.record_failure()
    assert cb.allow() is True


def test_breaker_reopens_on_failed_probe():
    cb = CircuitBreaker(name="t", failure_threshold=2, cooldown_seconds=0.05)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.06)
    # Probe call fails
    cb.record_failure()
    assert cb.allow() is False, "failed probe re-opens with full cooldown"
    # And cooldown timer is restarted
    time.sleep(0.06)
    assert cb.allow() is True


# ---------------------------------------------------------------------------
# AV integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_av_breaker(monkeypatch):
    cb = CircuitBreaker(name="av-test", failure_threshold=3, cooldown_seconds=10.0)
    monkeypatch.setattr(av, "_breaker", cb)
    return cb


def test_av_scan_records_failure_on_timeout(fresh_av_breaker):
    def _raise_timeout(*args, **kwargs):
        raise TimeoutError
    with patch.object(av, "_scan_clamd_tcp", side_effect=_raise_timeout):
        status, reason = av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
    assert status == "check_failed"
    assert reason == "timeout"
    # Counter incremented, but not yet at threshold
    assert fresh_av_breaker.allow() is True


def test_av_scan_short_circuits_when_breaker_open(fresh_av_breaker):
    """After N consecutive failures the next scan returns
    ``breaker_open`` WITHOUT hitting the transport. The transport
    mock is configured to raise, so a transport call would surface
    as ``timeout`` — finding ``breaker_open`` instead proves the
    fast-fail path fired."""
    def _raise_timeout(*args, **kwargs):
        raise TimeoutError
    with patch.object(av, "_scan_clamd_tcp", side_effect=_raise_timeout) as mocked:
        # Burn the threshold
        for _ in range(3):
            av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
        assert mocked.call_count == 3
        # Next call must short-circuit
        status, reason = av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
        assert status == "check_failed"
        assert reason == "breaker_open"
        assert mocked.call_count == 3, "transport NOT called when breaker open"


def test_av_scan_records_success_on_ok_verdict(fresh_av_breaker):
    """A clean scan resets the failure counter."""
    fresh_av_breaker.record_failure()
    fresh_av_breaker.record_failure()
    with patch.object(av, "_scan_clamd_tcp", return_value=("ok", "")):
        status, _ = av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
    assert status == "ok"
    # Even a third failure should not open the breaker now
    with patch.object(av, "_scan_clamd_tcp", side_effect=TimeoutError):
        av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
    assert fresh_av_breaker.allow() is True


def test_av_scan_records_success_on_infected_verdict(fresh_av_breaker):
    """An infected verdict still proves the AV daemon is reachable
    and answering — it MUST be treated as a healthy interaction
    for breaker purposes."""
    fresh_av_breaker.record_failure()
    fresh_av_breaker.record_failure()
    with patch.object(av, "_scan_clamd_tcp", return_value=("infected", "Eicar")):
        status, sig = av.scan_bytes(b"X", "tcp://127.0.0.1:3310")
    assert status == "infected"
    assert sig == "Eicar"
    assert fresh_av_breaker.allow() is True


# ---------------------------------------------------------------------------
# HIBP integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_hibp_breaker(monkeypatch, settings):
    settings.HIBP_PASSWORD_CHECK = True
    cb = CircuitBreaker(name="hibp-test", failure_threshold=3, cooldown_seconds=10.0)
    monkeypatch.setattr(validators, "_breaker", cb)
    return cb


def test_hibp_short_circuits_when_breaker_open(fresh_hibp_breaker):
    """Once the breaker is open, the validator allows the password
    without calling the HIBP endpoint at all."""
    call_count = {"n": 0}

    def _boom(_prefix, **_):
        call_count["n"] += 1
        raise URLError("network down")

    with patch.object(validators, "_query_hibp", side_effect=_boom):
        v = validators.HIBPPasswordValidator()
        # Burn threshold
        for _ in range(3):
            v.validate("CorrectHorseBatteryStaple!1")
        assert call_count["n"] == 3
        # Next validate must NOT call the endpoint
        v.validate("CorrectHorseBatteryStaple!1")
        assert call_count["n"] == 3


def test_hibp_records_success_on_clean_response(fresh_hibp_breaker):
    """A successful API call resets the counter."""
    fresh_hibp_breaker.record_failure()
    fresh_hibp_breaker.record_failure()
    # Response with no matching suffix → password allowed, breaker healthy
    with patch.object(validators, "_query_hibp", return_value="AAAAA:1\nBBBBB:2"):
        validators.HIBPPasswordValidator().validate("UniquePass!9zZ")
    # One more failure would have hit threshold; with reset, breaker stays closed
    assert fresh_hibp_breaker.allow() is True


# ---------------------------------------------------------------------------
# SMTP queue integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_queue_skips_batch_when_breaker_open(monkeypatch):
    """When the SMTP breaker is open at tick time, process_email_queue
    must NOT touch any pending row — burning max_attempts during a
    known outage would silently fail legitimate emails."""
    from django.utils import timezone

    from ameli_web.accounts import services
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import email_queue as eq_module

    cb = CircuitBreaker(name="smtp-test", failure_threshold=1, cooldown_seconds=60.0)
    cb.record_failure()  # opens immediately (threshold=1)
    monkeypatch.setattr(eq_module, "_smtp_breaker", cb)

    row = OutboundEmail.objects.create(
        target_username="probe",
        subject="hi",
        body="...",
        from_email="noreply@example.com",
        to_emails=["probe@example.com"],
        next_retry_at=timezone.now(),
        max_attempts=3,
    )

    sends = {"n": 0}

    def _track_send(self, *args, **kwargs):
        sends["n"] += 1
        return 1

    monkeypatch.setattr("django.core.mail.message.EmailMessage.send", _track_send)

    summary = services.process_email_queue()

    assert sends["n"] == 0, "no row should have been sent through SMTP"
    row.refresh_from_db()
    assert row.attempts == 0, "row's attempts MUST NOT be bumped on a skipped tick"
    assert row.status == OutboundEmail.STATUS_PENDING
    assert summary["sent"] == 0
    assert summary["skipped_breaker"] == 1
