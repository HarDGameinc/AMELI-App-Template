"""Circuit breakers for the project's external integrations (mini-roadmap #9).

When clamd is wedged, HIBP is rate-limited, or the SMTP relay refuses
connections, every call still pays the full transport timeout (5 s AV,
3 s HIBP, ~30 s SMTP) before falling through to the existing
fail-open / retry logic. With 50 concurrent avatar uploads, a wedged
AV daemon stalls the api worker for 250 s of cumulative wait. This
module short-circuits that: after ``failure_threshold`` consecutive
failures, the breaker opens and subsequent ``allow()`` calls return
``False`` immediately. The caller then takes the same fail-open
branch it would have taken on a real timeout, but without spending
the timeout.

State machine:

    CLOSED      ──5 fail──▶  OPEN
    OPEN        ──cooldown──▶ HALF_OPEN (the next call is a probe)
    HALF_OPEN   ──ok──▶  CLOSED
    HALF_OPEN   ──fail──▶ OPEN (cooldown restarts)

State is process-local. Each worker discovers an outage independently;
the worst case scales linearly with worker count, not with request
count. Storing breaker state in a shared cache (Redis) would tighten
that but adds a dependency the template intentionally avoids.

Thread-safe via a per-breaker lock so concurrent requests within the
same worker do not race on the counter.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """Process-local circuit breaker around a single external dependency.

    ``name`` is used only for logging — choose something the operator
    will recognise in journal output (``av``, ``hibp``, ``smtp``).
    """

    name: str
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    _failure_count: int = field(default=0, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def allow(self) -> bool:
        """Return ``True`` when a call MAY proceed.

        - CLOSED → True
        - OPEN with cooldown not yet elapsed → False (fast-fail)
        - OPEN with cooldown elapsed → True (this call becomes the
          half-open probe; the breaker stays nominally OPEN until
          ``record_success`` lands)
        """
        with self._lock:
            if self._opened_at == 0.0:
                return True
            if (time.monotonic() - self._opened_at) >= self.cooldown_seconds:
                return True
            return False

    def record_success(self) -> None:
        """Reset state to CLOSED. Call this after every successful
        call to the protected dependency, including calls that
        returned a domain-level "negative" answer (e.g. an AV scan
        that found a virus is still a successful AV interaction)."""
        with self._lock:
            was_open = self._opened_at != 0.0
            self._failure_count = 0
            self._opened_at = 0.0
        if was_open:
            logger.info("circuit_breaker.closed name=%s", self.name)

    def record_failure(self) -> None:
        """Increment the failure counter; open / re-open as needed."""
        with self._lock:
            now = time.monotonic()
            half_open_failed = (
                self._opened_at != 0.0
                and (now - self._opened_at) >= self.cooldown_seconds
            )
            if half_open_failed:
                self._opened_at = now
                transition = "reopened"
            else:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold and self._opened_at == 0.0:
                    self._opened_at = now
                    transition = "opened"
                else:
                    transition = ""
        if transition:
            logger.warning(
                "circuit_breaker.%s name=%s failures=%d cooldown_s=%.1f",
                transition, self.name, self._failure_count, self.cooldown_seconds,
            )

    def reset(self) -> None:
        """Force back to CLOSED. Used by tests; do not call from
        production code — let the half-open probe close it
        organically after the dependency recovers."""
        with self._lock:
            self._failure_count = 0
            self._opened_at = 0.0


def _from_settings(name: str, threshold_attr: str, cooldown_attr: str,
                   default_threshold: int, default_cooldown: float) -> CircuitBreaker:
    """Build a breaker whose thresholds come from Django settings.

    Looking the value up at import time keeps the hot path lock-free.
    Operators that need to retune live can ``circuit_breaker.reset()``
    and re-import; for a real-world tune just set the env var and
    restart the worker.
    """
    from django.conf import settings

    threshold = int(getattr(settings, threshold_attr, default_threshold))
    cooldown = float(getattr(settings, cooldown_attr, default_cooldown))
    return CircuitBreaker(name=name, failure_threshold=threshold, cooldown_seconds=cooldown)


# Singletons used by av.py, validators.py, services.py. Built lazily
# inside the modules that need them so importing this file in a test
# does not require a Django settings setup.

def get_av_breaker() -> CircuitBreaker:
    return _from_settings(
        "av",
        "AV_CIRCUIT_BREAKER_THRESHOLD",
        "AV_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        default_threshold=5,
        default_cooldown=30.0,
    )


def get_hibp_breaker() -> CircuitBreaker:
    return _from_settings(
        "hibp",
        "HIBP_CIRCUIT_BREAKER_THRESHOLD",
        "HIBP_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        default_threshold=5,
        default_cooldown=60.0,
    )


def get_smtp_breaker() -> CircuitBreaker:
    return _from_settings(
        "smtp",
        "SMTP_CIRCUIT_BREAKER_THRESHOLD",
        "SMTP_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        default_threshold=5,
        default_cooldown=60.0,
    )
