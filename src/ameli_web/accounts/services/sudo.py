"""Sudo grants for sensitive admin actions.

Extracted from the monolithic services.py on 2026-06-27 (PC-1 step 4).
The public API is unchanged: callers continue to ``from
ameli_web.accounts.services import grant_sudo, revoke_sudo,
session_in_sudo, verify_sudo_credentials, send_sudo_email_code,
SudoRequired`` because ``services/__init__.py`` re-exports the names.

Architecture:

- ``grant_sudo`` / ``revoke_sudo`` / ``session_in_sudo`` are the
  session-cookie helpers: stamp / clear / check the ``sudo_until``
  expiry stored on the session.
- ``verify_sudo_credentials`` is the re-auth entry point invoked by
  the ``/admin/sudo/`` endpoint. It is rate-limited per user via
  ``_SUDO_FAIL_SCOPE`` (Phase B B1, 24-jun) so a cookie thief cannot
  enumerate the 6-digit MFA space.
- ``send_sudo_email_code`` delegates to the email-MFA pipeline so
  an operator can sudo without the TOTP app at hand.

Cycle handling: ``verify_sudo_credentials`` calls back into helpers
that still live in ``services/__init__.py`` (``consume_email_mfa_code``,
``consume_recovery_code``) and the sibling ``mfa`` module. The mfa
module is a direct sibling so it imports cleanly via ``from ..mfa
import ...``; the same-package helpers are imported lazily inside
the function body to avoid the import-time cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from .throttle import _bump_throttle_counter, _read_throttle_counter

# ============================ Sudo-mode for admin actions ============================
#
# An admin who is already logged in with MFA can still be impersonated if
# their session cookie leaks (XSS, shared workstation, network attack).
# A leaked superadmin cookie lets the attacker create another superadmin,
# clear someone's MFA, reset a password and so on — without re-asserting
# control of the password or the second factor.
#
# Sudo-mode raises the bar: every sensitive admin action requires the
# operator to confirm with their password (and MFA code if enrolled) in
# the last few minutes. We keep the grant in the session under
# ``sudo_until`` so the operator does not have to re-enter their
# credentials for every click during a maintenance window.

SUDO_GRACE_SECONDS_DEFAULT = 300  # 5 minutes


class SudoRequired(Exception):
    """Raised when an admin action runs without a fresh sudo grant."""


def grant_sudo(session, *, seconds: int | None = None) -> int:
    """Stamp ``sudo_until`` on the session and return the grace window."""
    from django.conf import settings as django_settings

    grace = int(
        seconds
        if seconds is not None
        else getattr(django_settings, "SUDO_GRACE_SECONDS", SUDO_GRACE_SECONDS_DEFAULT)
    )
    grace = max(30, grace)  # don't let an operator footgun themselves with 0
    expires_at = timezone.now() + timedelta(seconds=grace)
    session["sudo_until"] = expires_at.isoformat()
    session.modified = True
    return grace


def revoke_sudo(session) -> None:
    """Drop any active sudo grant (used on logout and on password change)."""
    if "sudo_until" in session:
        del session["sudo_until"]
        session.modified = True


def session_in_sudo(session) -> bool:
    """Return True when the session still has a valid sudo grant."""
    raw = session.get("sudo_until")
    if not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return False
    return expires_at > timezone.now()


# Sudo brute-force gate: dedicated counter so the sudo failures don't
# share the login-fail bucket (a noisy login would otherwise lock
# legit sudo flows). 5 fails / 60s window is conservative — sudo is a
# re-auth for someone already inside, the keyspace is small (6-digit
# MFA + password).
_SUDO_FAIL_SCOPE = "sudo_fail_user"
_SUDO_FAIL_WINDOW_SECONDS = 60
_SUDO_FAIL_THRESHOLD = 5


def _sudo_throttle_key(user) -> str:
    return (getattr(user, "username", "") or "").lower()


def _check_sudo_throttle(user) -> None:
    """Raise if the user has burnt through the sudo-fail budget in the
    current window. Read-only; counter increments happen in
    ``_record_sudo_failure``."""
    key = _sudo_throttle_key(user)
    if not key:
        return
    count = _read_throttle_counter(
        scope=_SUDO_FAIL_SCOPE, key=key, window_seconds=_SUDO_FAIL_WINDOW_SECONDS
    )
    if count >= _SUDO_FAIL_THRESHOLD:
        raise ValueError(
            "demasiados intentos de sudo. Esperá un minuto y volvé a intentar.",
        )


def _record_sudo_failure(user) -> int:
    key = _sudo_throttle_key(user)
    if not key:
        return 0
    return _bump_throttle_counter(
        scope=_SUDO_FAIL_SCOPE, key=key, window_seconds=_SUDO_FAIL_WINDOW_SECONDS
    )


def verify_sudo_credentials(user, *, password: str, mfa_code: str = "") -> None:
    """Confirm the operator owns the session by re-checking their password
    and (when applicable) a fresh MFA code.

    Accepts any of the enrolled methods so the operator can use whatever
    is closest at hand:

    * TOTP code from the authenticator app (when ``mfa_totp_enabled``)
    * Single-use code emailed via :func:`send_sudo_email_code` (when
      ``mfa_email_enabled``)
    * Recovery code (always, so an operator who lost both devices can
      still sudo)

    Raises :class:`ValueError` with a user-facing message if anything is
    missing or wrong. Returns silently on success.

    PHASE_B_SECURITY_REVIEW B1: a per-user sudo-fail counter
    (``_SUDO_FAIL_SCOPE``) gates this entry point so an attacker
    holding a sudo'd cookie cannot enumerate the 6-digit MFA space.
    Fails inside the window raise a distinct user-facing message and
    revoke any in-flight sudo grant — the operator has to wait the
    cooldown.
    """
    from .. import mfa

    if not user or not user.is_authenticated:
        raise ValueError("autenticacion requerida")
    _check_sudo_throttle(user)
    try:
        if not user.check_password(password or ""):
            raise ValueError("contrasena invalida")
        if not user.mfa_enabled:
            return
        code = (mfa_code or "").strip()
        if not code:
            raise ValueError("codigo 2fa requerido")
        if user.mfa_totp_enabled and user.mfa_secret and mfa.verify_totp(mfa.decrypt_secret(user.mfa_secret), code):
            return
        # Lazy import to keep services/__init__.py the single entry point
        # for module load order; sudo.py is imported before mfa.py is fully
        # initialised when this module is first hit from a request.
        from .mfa import consume_email_mfa_code, consume_recovery_code

        if user.mfa_email_enabled and consume_email_mfa_code(user, code):
            return
        if consume_recovery_code(user, code):
            return
        raise ValueError("codigo 2fa invalido o expirado")
    except ValueError:
        _record_sudo_failure(user)
        raise


def send_sudo_email_code(user) -> dict[str, Any]:
    """Send a single-use email code so the operator can sudo without the
    TOTP app. Reuses the login-time email MFA pipeline (with the same
    per-user rate-limit) so this path stays consistent.
    """
    if not (user and user.is_authenticated):
        raise ValueError("autenticacion requerida")
    if not user.mfa_email_enabled:
        raise ValueError("email 2fa no esta activado para esta cuenta")
    # Lazy import: same reason as verify_sudo_credentials above.
    from .mfa import send_mfa_email_login_code

    return send_mfa_email_login_code(user)


def _build_sudo_helpers() -> dict[str, Any]:  # pragma: no cover - reflective use
    """Expose the internal helpers for tests that want to mock them by
    name. Not part of the public API; provided to mirror the previous
    monolithic module's call-by-name flexibility."""
    return {
        "_check_sudo_throttle": _check_sudo_throttle,
        "_record_sudo_failure": _record_sudo_failure,
        "_sudo_throttle_key": _sudo_throttle_key,
        "_SUDO_FAIL_SCOPE": _SUDO_FAIL_SCOPE,
        "_SUDO_FAIL_WINDOW_SECONDS": _SUDO_FAIL_WINDOW_SECONDS,
        "_SUDO_FAIL_THRESHOLD": _SUDO_FAIL_THRESHOLD,
    }
