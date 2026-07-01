"""Response security headers: HSTS, X-Frame-Options, proxy SSL, message storage allow-list.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

import os

from .base import ENV_NAME

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# When a TLS-terminating proxy (Caddy, nginx) sits in front, Django needs
# to know the original scheme to make ``request.is_secure()`` honest and
# to set ``Secure`` cookies correctly. The proxy must be configured to
# strip any client-provided ``X-Forwarded-Proto`` and inject its own; if
# the header is trusted while an upstream is uncontrolled, an attacker
# can mint "secure" sessions over plaintext.
_proxy_ssl_header = os.environ.get("AMELI_APP_SECURE_PROXY_SSL_HEADER", "").strip()
if _proxy_ssl_header:
    if "=" not in _proxy_ssl_header:
        raise RuntimeError(
            "AMELI_APP_SECURE_PROXY_SSL_HEADER must be 'HEADER_NAME=value' "
            "(e.g. 'HTTP_X_FORWARDED_PROTO=https')."
        )
    _proxy_header_name, _proxy_header_value = _proxy_ssl_header.split("=", 1)
    SECURE_PROXY_SSL_HEADER = (_proxy_header_name.strip(), _proxy_header_value.strip())

# HSTS: only meaningful when the deploy is reachable over HTTPS, and
# easy to lock yourself out of staging if you set it too early. The
# default outside dev is one year + includeSubDomains + preload-eligible
# because every real deploy should be HTTPS-only; an operator can set
# ``AMELI_APP_HSTS_SECONDS=0`` explicitly to opt out during initial
# rollout when TLS is still being wired up. ``preload`` itself is left
# off so the operator can choose whether to submit to hstspreload.org
# (the submission is functionally irreversible).
_hsts_default = 0 if ENV_NAME == "dev" else 31_536_000
SECURE_HSTS_SECONDS = int(os.environ.get("AMELI_APP_HSTS_SECONDS", str(_hsts_default)))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False

# The project-wide CSP is built per request by SecurityHeadersMiddleware
# so it can stamp a unique ``nonce-...`` token in script-src and
# style-src. That replaces the legacy ``'unsafe-inline'`` token: an
# attacker who reflects markup into a template still cannot execute it
# because they do not have access to the nonce minted server-side for
# that response. See accounts.middleware.build_csp.

# ASVS V5.5.1 — safe serialization for the Django messages framework.
# Django ships three first-party storages (session / cookie / fallback);
# all three serialise message bodies as signed JSON (cookie/fallback)
# or session-backed (which itself defaults to JSON). A third-party
# storage that relied on ``pickle`` to ride the same path would be a
# remote-code-execution gadget the moment the operator's
# ``SECRET_KEY`` leaks.
#
# Default: session storage (the historic choice). Operator can swap
# via ``AMELI_APP_MESSAGE_STORAGE`` but only to one of the three
# allow-listed first-party paths. Anything else refuses to boot with
# an actionable error.
_ALLOWED_MESSAGE_STORAGES = frozenset({
    "django.contrib.messages.storage.session.SessionStorage",
    "django.contrib.messages.storage.cookie.CookieStorage",
    "django.contrib.messages.storage.fallback.FallbackStorage",
})
MESSAGE_STORAGE = os.environ.get(
    "AMELI_APP_MESSAGE_STORAGE",
    "django.contrib.messages.storage.session.SessionStorage",
).strip()
if MESSAGE_STORAGE not in _ALLOWED_MESSAGE_STORAGES:
    raise RuntimeError(
        f"AMELI_APP_MESSAGE_STORAGE={MESSAGE_STORAGE!r} is not on the "
        "allow-list of safe Django messages storages. Allowed values: "
        f"{sorted(_ALLOWED_MESSAGE_STORAGES)}. A storage that uses "
        "``pickle`` is a deserialisation RCE gadget; pick one of the "
        "first-party signed-JSON storages or leave the env var unset."
    )
