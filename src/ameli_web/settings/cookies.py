"""Session + CSRF cookie policy (name, Secure, HttpOnly, SameSite, __Host- prefix).

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

import os

from .base import _IS_DEV_ENV, CFG

# Default to secure cookies outside dev so the operator opts INTO an
# insecure deploy explicitly rather than the other way around.
SESSION_COOKIE_SECURE = bool(CFG.session_cookie_secure) if _IS_DEV_ENV else True

# ASVS V3.4.4 — ``__Host-`` cookie prefix. Browsers enforce three
# properties on cookies whose name literally starts with ``__Host-``:
# the ``Secure`` flag MUST be set, ``Domain`` MUST be absent, and
# ``Path`` MUST be ``/``. The prefix turns those into a contract the
# browser checks per-request, so a misconfigured deploy that forgets
# the Secure flag (or accidentally sets a Domain) is REJECTED rather
# than serving an attackable cookie.
#
# Default policy (no operator override):
# * Outside dev → cookie name becomes ``__Host-ameli_app_session`` /
#   ``__Host-ameli_csrf`` (Secure is True, Domain default-empty,
#   Path default ``/``).
# * In dev → cookie name stays ``ameli_app_session`` / ``ameli_csrf``
#   because dev typically runs over plain HTTP and the browser would
#   reject a ``__Host-``-prefixed cookie sent without ``Secure``.
#
# Operator override: setting ``AMELI_APP_SESSION_COOKIE_NAME`` (or the
# YAML ``auth.session_cookie_name``) wins — for operators behind a
# reverse proxy that strips the prefix or for legacy deploys with
# bookmarked cookies. The boot guard below catches the misconfig where
# the operator picked a ``__Host-`` name but did NOT meet the three
# constraints.
_SESSION_COOKIE_NAME_CONFIGURED = CFG.session_cookie_name or ""
if _SESSION_COOKIE_NAME_CONFIGURED:
    SESSION_COOKIE_NAME = _SESSION_COOKIE_NAME_CONFIGURED
elif SESSION_COOKIE_SECURE:
    SESSION_COOKIE_NAME = "__Host-ameli_app_session"
else:
    SESSION_COOKIE_NAME = "ameli_app_session"

if SESSION_COOKIE_NAME.startswith("__Host-"):
    # Browser will reject the cookie if any of these constraints
    # is violated; we'd rather refuse to boot than ship a deploy
    # whose users mysteriously stay logged out.
    if not SESSION_COOKIE_SECURE:
        raise RuntimeError(
            "SESSION_COOKIE_NAME starts with '__Host-' but "
            "SESSION_COOKIE_SECURE is False. The browser will REJECT "
            "this cookie. Either rename it or enable Secure."
        )
    # Django does not set SESSION_COOKIE_DOMAIN by default; if the
    # operator pinned it via env we catch it here.
    if os.environ.get("AMELI_APP_SESSION_COOKIE_DOMAIN", "").strip():
        raise RuntimeError(
            "SESSION_COOKIE_NAME starts with '__Host-' but a Domain "
            "is set via AMELI_APP_SESSION_COOKIE_DOMAIN. The browser "
            "will REJECT this cookie. Drop the Domain or rename."
        )

SESSION_COOKIE_AGE = max(300, int(CFG.session_max_age_seconds or 43200))
SESSION_COOKIE_HTTPONLY = True  # JS cannot read the session cookie.
SESSION_COOKIE_SAMESITE = "Lax"
# When True, every authenticated request renews the session's expiry, so
# ``SESSION_COOKIE_AGE`` works as an "inactivity timeout": the user only
# gets logged out if they stop hitting the app for that many seconds.
# When False, the cookie age is a hard maximum from creation regardless
# of activity. Default: True (the friendlier behaviour for operators).
SESSION_SAVE_EVERY_REQUEST = bool(CFG.session_idle_renewal)
# Expire on browser close when set; defaults to False so refreshing a tab
# doesn't lose the session (matches the rest of the Template's UX).
SESSION_EXPIRE_AT_BROWSER_CLOSE = bool(CFG.session_expire_at_browser_close)
# Absolute session ceiling (ASVS V3.3.3): even with continuous activity,
# the session expires this many seconds after the original login (the
# ``UserSession.created_at`` anchor). The user is forced to re-authenticate
# on the next request after the ceiling is crossed. ``SESSION_COOKIE_AGE``
# above is the IDLE timeout — this one is the ABSOLUTE timeout.
#
# Default: 30 days (2_592_000 s). Operators can shorten for sensitive
# deploys via ``AMELI_APP_SESSION_ABSOLUTE_MAX_AGE_SECONDS`` or set to 0
# to disable (back-compat with deploys that have never enforced this).
SESSION_ABSOLUTE_MAX_AGE_SECONDS = int(
    os.environ.get("AMELI_APP_SESSION_ABSOLUTE_MAX_AGE_SECONDS", "2592000")
)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True  # we read the token from the {% csrf_token %} tag, not from JS.
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"

# ASVS V3.4.4 — same ``__Host-`` policy as the session cookie. The
# CSRF cookie does NOT carry the auth identity (it carries the CSRF
# token signature) but the same browser-enforced contract applies:
# without ``__Host-`` an attacker who can set a cookie on a parent
# domain can shadow ours and bypass CSRF.
#
# In dev we keep Django's default ``csrftoken`` so existing tests
# and any client tooling that hardcodes the default name keep working.
CSRF_COOKIE_NAME = "__Host-ameli_csrf" if CSRF_COOKIE_SECURE else "csrftoken"
if CSRF_COOKIE_NAME.startswith("__Host-") and not CSRF_COOKIE_SECURE:
    raise RuntimeError(
        "CSRF_COOKIE_NAME starts with '__Host-' but CSRF_COOKIE_SECURE "
        "is False. The browser will REJECT this cookie. Either rename "
        "it or enable Secure."
    )
