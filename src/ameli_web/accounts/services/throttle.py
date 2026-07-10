"""Throttle counters + login lockout + auxiliary rate limits.

Extracted from the monolithic services.py on 2026-06-27 (PC-1 step 3).
The public API is unchanged: callers continue to ``from
ameli_web.accounts.services import check_login_throttle,
record_login_failure, LoginThrottled, AccountLocked, ...`` because
``services/__init__.py`` re-exports the names.

Architecture:

- ``_bump_throttle_counter`` / ``_read_throttle_counter`` /
  ``_read_throttle_counter_sliding`` are the low-level primitives
  shared with every other throttle in the project (sudo, MFA,
  forgot-password, MFA-resend).
- ``record_login_failure`` + ``check_login_throttle`` are the
  login-specific entry points; they consult per-IP and per-user
  buckets independently so an attacker brute-forcing one user
  cannot lock unrelated users sharing the same IP.
- ``maybe_permanently_lock`` flips ``User.locked_at`` after N
  consecutive lockout windows (see
  ``LOCKOUT_PERMANENT_CONSECUTIVE`` setting).
- ``check_forgot_password_throttle`` and
  ``check_mfa_resend_throttle`` are per-IP gates that share the
  same primitive.

Circular-import note: ``record_login_failure`` calls
``_maybe_alert_for_auth_failures_burst`` (still in
``services/__init__.py``). We do that import lazily inside the
function body to avoid the import-time cycle.
"""
from __future__ import annotations

from datetime import UTC
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext as _

from ameli_web.audit.models import AuditEvent

from .audit import record_audit

User = get_user_model()


def _window_start_for(seconds: int, now=None):
    """Snap ``now`` to the start of its ``seconds``-wide window so all
    requests inside the same bucket hit the same counter row."""
    from datetime import datetime

    now = now or timezone.now()
    epoch = int(now.timestamp())
    bucket = (epoch // max(1, seconds)) * max(1, seconds)
    return datetime.fromtimestamp(bucket, tz=UTC)


def _bump_throttle_counter(*, scope: str, key: str, window_seconds: int) -> int:
    """Atomically increment the counter row for (scope, key, current
    window) and return the new count. Used by every gate that has to
    react to "this happened, now decide" — the increment and the read
    are inside one transaction so a concurrent caller cannot observe a
    stale value.
    """
    from django.db import transaction
    from django.db.models import F

    from ..models import ThrottleCounter

    window_start = _window_start_for(window_seconds)
    with transaction.atomic():
        row, _created = ThrottleCounter.objects.select_for_update().get_or_create(
            scope=scope, key=key, window_start=window_start, defaults={"count": 0}
        )
        ThrottleCounter.objects.filter(pk=row.pk).update(count=F("count") + 1)
        row.refresh_from_db(fields=["count"])
        return row.count


def _read_throttle_counter(*, scope: str, key: str, window_seconds: int) -> int:
    """Snapshot read of the current window's counter; returns 0 when no
    row exists yet."""
    from ..models import ThrottleCounter

    window_start = _window_start_for(window_seconds)
    row = ThrottleCounter.objects.filter(
        scope=scope, key=key, window_start=window_start
    ).first()
    return row.count if row else 0


def _read_throttle_counter_sliding(*, scope: str, key: str, window_seconds: int) -> int:
    """Sliding-window approximation of the counter.

    The fixed-bucket pattern that :func:`_read_throttle_counter` reads
    lets an attacker burst ~2x the configured cap by straddling a
    bucket boundary: 4 attempts at t=window_end-1 land in bucket A,
    then 5 more at t=window_end+1 land in bucket B — both under the
    cap, total ~9 in two seconds.

    This helper folds in a time-weighted portion of the previous
    bucket so the effective rate stays near the documented cap
    regardless of where in the window the attempts land. It is the
    classic "sliding window counter" approximation used by rate
    limiters that want stronger guarantees than a fixed bucket
    without paying the cost of a per-event log.
    """
    from datetime import datetime

    from ..models import ThrottleCounter

    now = timezone.now()
    epoch = int(now.timestamp())
    window_seconds = max(1, window_seconds)
    bucket = (epoch // window_seconds) * window_seconds
    cur_start = datetime.fromtimestamp(bucket, tz=UTC)
    prev_start = datetime.fromtimestamp(bucket - window_seconds, tz=UTC)

    rows = ThrottleCounter.objects.filter(
        scope=scope, key=key, window_start__in=[cur_start, prev_start]
    ).values_list("window_start", "count")
    counts = {ws: c for ws, c in rows}
    cur_count = counts.get(cur_start, 0)
    prev_count = counts.get(prev_start, 0)

    elapsed = epoch - bucket
    prev_weight = max(0.0, (window_seconds - elapsed) / window_seconds)
    # Round UP (math.ceil) instead of truncating: a rate limiter
    # MUST never under-count, otherwise a request that lands a
    # millisecond after a bucket boundary slips below the
    # threshold even when the burst across the past window
    # exceeds it. The cost is at most 1 over-count at the
    # boundary (acceptable defensive bias); the benefit is the
    # test_forgot_password_throttle_after_too_many_requests CI
    # flake (~0.5%/run when test crosses a window edge) goes to
    # zero.
    import math

    return cur_count + math.ceil(prev_count * prev_weight)


def record_login_failure(*, username: str = "", ip: str = "") -> None:
    """Increment the failure counters that :func:`check_login_throttle`
    reads. Both keys (IP and username) get their own row so a brute
    force against a single account does not consume the per-IP budget
    for unrelated users sharing a network, and vice versa.

    Side effect (ASVS V2.2.3): when the per-username counter crosses
    ``LOGIN_LOCKOUT_USER_MAX`` for the current window, an alert email
    is queued to the affected user via
    ``_maybe_alert_for_auth_failures_burst``. The alert is throttled
    by a 24 h cooldown anchored on the User row so an attacker cannot
    weaponise the alert pipeline as a spam channel.
    """
    cfg = _throttle_settings()
    if ip:
        _bump_throttle_counter(scope="login_fail_ip", key=ip, window_seconds=cfg["ip_window"])
    if username:
        new_count = _bump_throttle_counter(
            scope="login_fail_user",
            key=username.lower(),
            window_seconds=cfg["user_window"],
        )
        # Lazy import: the alert helper still lives in services/__init__.py
        # (will move when we extract services/alerts.py). Lazy avoids
        # the import-time cycle (__init__ → throttle → __init__).
        from ameli_web.accounts.services import _maybe_alert_for_auth_failures_burst

        _maybe_alert_for_auth_failures_burst(username=username, new_count=new_count, ip=ip)


# Defaults tuned so an attacker brute-forcing a single username gets
# stopped within a minute; a sloppy operator typing their own password
# wrong still has 4-5 attempts in the lockout window.

LOGIN_THROTTLE_IP_MAX_DEFAULT = 12
LOGIN_THROTTLE_IP_WINDOW_DEFAULT = 60  # seconds
LOGIN_LOCKOUT_USER_MAX_DEFAULT = 5
LOGIN_LOCKOUT_USER_WINDOW_DEFAULT = 300  # seconds = 5 minutes


def _throttle_settings():
    """Resolve throttle thresholds from Django settings, falling back to
    sane defaults. Letting deployments tune these via env vars lets ops
    raise them for high-trust internal networks or lower them for
    public-facing deploys without code changes.
    """
    from django.conf import settings as django_settings

    return {
        "ip_max": getattr(django_settings, "LOGIN_THROTTLE_IP_MAX", LOGIN_THROTTLE_IP_MAX_DEFAULT),
        "ip_window": getattr(
            django_settings, "LOGIN_THROTTLE_IP_WINDOW", LOGIN_THROTTLE_IP_WINDOW_DEFAULT
        ),
        "user_max": getattr(
            django_settings, "LOGIN_LOCKOUT_USER_MAX", LOGIN_LOCKOUT_USER_MAX_DEFAULT
        ),
        "user_window": getattr(
            django_settings, "LOGIN_LOCKOUT_USER_WINDOW", LOGIN_LOCKOUT_USER_WINDOW_DEFAULT
        ),
    }


def _count_recent_login_failures(*, username: str = "", ip: str = "", seconds: int) -> int:
    """Count audit ``login_failed`` events for the (username, ip) pair within
    the last ``seconds``. Either filter can be empty to ignore that axis.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=max(1, seconds))
    queryset = AuditEvent.objects.filter(action__endswith="_failed", created_at__gte=cutoff)
    if username:
        queryset = queryset.filter(target_username__iexact=username)
    if ip:
        from django.db.models import Q

        # The login_failed signal uses ``ip_address``; the login_throttled
        # event we record on our own uses ``ip``. Match either key with an
        # exact-value JSON lookup so an IP that is a prefix of another
        # (``192.168.1.1`` vs ``192.168.1.10``) does not produce false
        # positives the way a substring search would.
        queryset = queryset.filter(
            Q(payload__ip=ip) | Q(payload__ip_address=ip)
        )
    return queryset.count()


class LoginThrottled(Exception):
    """Raised when the request must be refused (IP-level rate limit)."""

    def __init__(self, message: str, *, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class AccountLocked(Exception):
    """Raised when the user's account is temporarily locked due to too many
    failed attempts."""

    def __init__(self, message: str, *, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


# Defaults for the per-IP throttle that protects the ``/login/forgot/``
# request endpoint. Tuned so a typo-prone user can still ask 3-4 times
# but an attacker enumerating usernames or flooding SMTP gets stopped.
FORGOT_PASSWORD_IP_MAX_DEFAULT = 5
FORGOT_PASSWORD_IP_WINDOW_DEFAULT = 600  # 10 minutes

# Defaults for the per-IP throttle that protects ``/login/verify-mfa/resend/``.
# The per-user rate limit inside ``_check_email_mfa_rate_limit`` is per
# account; this one adds a per-IP cap so an attacker hitting the same
# resend endpoint with rotating users cannot cost-amplify the SMTP path.
MFA_RESEND_IP_MAX_DEFAULT = 8
MFA_RESEND_IP_WINDOW_DEFAULT = 300  # 5 minutes


def _count_recent_audit_by_action(
    *, action: str, ip: str = "", username: str = "", seconds: int
) -> int:
    """Count audit events matching ``action`` within the window.

    Used by the per-action throttles below. The lookup uses an exact JSON
    path match for ``ip`` and ``ip_address`` so a prefix like
    ``192.168.1.1`` does not collide with ``192.168.1.10``.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=max(1, seconds))
    queryset = AuditEvent.objects.filter(action=action, created_at__gte=cutoff)
    if ip:
        from django.db.models import Q

        queryset = queryset.filter(Q(payload__ip=ip) | Q(payload__ip_address=ip))
    if username:
        queryset = queryset.filter(target_username__iexact=username)
    return queryset.count()


def check_forgot_password_throttle(*, ip: str) -> None:
    """Refuse a ``/login/forgot/`` request when the IP has already asked
    for too many resets in the window. The bump happens atomically: each
    call counts as one attempt regardless of whether the downstream SMTP
    succeeds, so a hostile IP cannot drain the budget on a broken
    upstream and then retry for free.
    """
    if not ip:
        return
    from django.conf import settings as django_settings

    ip_max = int(getattr(
        django_settings, "FORGOT_PASSWORD_IP_MAX", FORGOT_PASSWORD_IP_MAX_DEFAULT
    ))
    ip_window = int(getattr(
        django_settings, "FORGOT_PASSWORD_IP_WINDOW", FORGOT_PASSWORD_IP_WINDOW_DEFAULT
    ))
    _bump_throttle_counter(
        scope="forgot_password_ip", key=ip, window_seconds=ip_window
    )
    # Sliding-window read so an attacker cannot burst ~2x the cap by
    # straddling the bucket boundary; the previous fixed-bucket read
    # let a 5-cap window admit 9 requests in two seconds.
    sliding = _read_throttle_counter_sliding(
        scope="forgot_password_ip", key=ip, window_seconds=ip_window
    )
    if sliding > ip_max:
        raise LoginThrottled(
            _(
                "Demasiados pedidos de recuperacion desde esta direccion. "
                "Espera unos minutos antes de volver a intentarlo."
            ),
            retry_after=ip_window,
        )


def check_mfa_resend_throttle(*, ip: str) -> None:
    """Refuse a ``/login/verify-mfa/resend/`` when the IP has triggered
    too many resends already. Same atomic-bump semantics as
    :func:`check_forgot_password_throttle`.
    """
    if not ip:
        return
    from django.conf import settings as django_settings

    ip_max = int(getattr(django_settings, "MFA_RESEND_IP_MAX", MFA_RESEND_IP_MAX_DEFAULT))
    ip_window = int(getattr(
        django_settings, "MFA_RESEND_IP_WINDOW", MFA_RESEND_IP_WINDOW_DEFAULT
    ))
    _bump_throttle_counter(
        scope="mfa_resend_ip", key=ip, window_seconds=ip_window
    )
    # Sliding read closes the bucket-boundary burst — see the longer
    # rationale on :func:`_read_throttle_counter_sliding`.
    sliding = _read_throttle_counter_sliding(
        scope="mfa_resend_ip", key=ip, window_seconds=ip_window
    )
    if sliding > ip_max:
        raise LoginThrottled(
            _(
                "Demasiados reenvios desde esta direccion. "
                "Espera unos minutos antes de pedir otro codigo."
            ),
            retry_after=ip_window,
        )


LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT = 3
"""How many lockout windows a username may consume in a row before the
account flips to ``locked_at`` and requires an admin to unlock it.
Three feels right: a real user who genuinely forgot their password runs
into one window, maybe two, but a sustained brute-force hits it
repeatedly."""


def _consecutive_lockouts_for(username: str, *, window: int) -> int:
    """Return how many lockout windows in a row the user has tripped.

    We look at the audit history rather than the throttle counter:
    counters reset every window, but the audit row ``login_locked_out``
    is a permanent record of "this window was completely consumed".
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=max(1, window) * 6)
    rows_qs = (
        AuditEvent.objects.filter(
            action="login_locked_out",
            target_username__iexact=username,
            created_at__gte=cutoff,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)[:10]
    )
    rows = list(rows_qs)
    if len(rows) < 2:
        return len(rows)
    # Count groups whose timestamps fall in distinct windows (gap >= window/2)
    distinct = 1
    last = rows[0]
    for ts in rows[1:]:
        if (last - ts).total_seconds() >= window * 0.5:
            distinct += 1
            last = ts
    return distinct


def maybe_permanently_lock(username: str) -> bool:
    """Flip the account to ``locked_at`` when the threshold is reached.

    Returns True when the lock was applied (or was already applied).
    Idempotent — calling it twice is safe.
    """
    from django.conf import settings as django_settings

    if not username:
        return False
    threshold = int(getattr(
        django_settings,
        "LOCKOUT_PERMANENT_CONSECUTIVE",
        LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT,
    ))
    if threshold <= 0:
        return False
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        return False
    if user.locked_at is not None:
        return True
    cfg = _throttle_settings()
    consecutive = _consecutive_lockouts_for(username, window=cfg["user_window"])
    if consecutive < threshold:
        return False
    user.locked_at = timezone.now()
    user.locked_reason = f"throttle:{consecutive}_consecutive_lockouts"
    user.save(update_fields=["locked_at", "locked_reason", "updated_at"])
    record_audit(
        "user_locked_permanently",
        target_username=user.username,
        payload={"reason": user.locked_reason, "consecutive": consecutive},
    )
    return True


def admin_unlock_user(*, actor_username: str, username: str) -> dict[str, Any]:
    """Clear ``locked_at`` so the user can attempt to log in again."""
    if not username:
        raise ValueError("usuario requerido")
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        raise ValueError("user not found")
    if user.locked_at is None:
        return {"ok": True, "status": "not-locked"}
    user.locked_at = None
    user.locked_reason = ""
    user.save(update_fields=["locked_at", "locked_reason", "updated_at"])
    actor = User.objects.filter(username__iexact=actor_username).first()
    record_audit(
        "user_unlocked_by_admin",
        actor=actor,
        target_username=user.username,
        payload={},
    )
    return {"ok": True, "status": "unlocked"}


def check_login_throttle(*, username: str, ip: str) -> None:
    """Raise ``LoginThrottled`` or ``AccountLocked`` if the caller should
    be refused. Returns silently if the login may proceed.

    Reads the counter that :func:`record_login_failure` writes. This is a
    **check-then-act** gate: the read here is NOT in the same locked
    transaction as the increment (which only happens *after* an auth
    failure), so a burst of concurrent requests can each read a stale
    sub-cap count and slip through in one window before any of them commit
    a failure — i.e. the per-window cap is a soft ceiling, not a hard one,
    under high concurrency (M3 security review).

    Why this is an accepted bound, not a hole: the counters catch up (no
    permanent bypass), the **permanent lockout** (``locked_at``, set after
    a few fully-consumed windows) caps the *total* attempts to a few dozen,
    and the smallest keyspace this gates — a 6-digit MFA code (10^6) — makes
    even a burst per window a negligible guessing edge. A hard fix (count
    attempts, or reserve-then-verify inside one locked txn) would change the
    lockout semantics and is deferred.

    Hard-locked accounts (``locked_at`` set by the permanent-lockout
    promotion) are always refused regardless of throttle counters until
    an admin clears the flag.
    """
    cfg = _throttle_settings()

    if username:
        user = User.objects.filter(username__iexact=username).first()
        if user is not None and user.locked_at is not None:
            raise AccountLocked(
                _(
                    "Esta cuenta esta bloqueada por seguridad. Contacta a un "
                    "administrador para desbloquearla."
                ),
                retry_after=0,
            )

    if ip:
        ip_fails = _read_throttle_counter_sliding(
            scope="login_fail_ip", key=ip, window_seconds=cfg["ip_window"]
        )
        if ip_fails >= cfg["ip_max"]:
            raise LoginThrottled(
                _("Demasiados intentos desde esta direccion. Espera unos segundos."),
                retry_after=cfg["ip_window"],
            )

    if username:
        user_fails = _read_throttle_counter_sliding(
            scope="login_fail_user",
            key=username.lower(),
            window_seconds=cfg["user_window"],
        )
        if user_fails >= cfg["user_max"]:
            raise AccountLocked(
                _(
                    "Cuenta bloqueada temporalmente por demasiados intentos fallidos. "
                    "Espera unos minutos o usa la recuperacion de clave."
                ),
                retry_after=cfg["user_window"],
            )
