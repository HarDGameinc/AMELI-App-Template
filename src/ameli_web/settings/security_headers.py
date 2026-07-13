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
            "(e.g. 'X-Forwarded-Proto=https' or 'HTTP_X_FORWARDED_PROTO=https')."
        )
    _proxy_header_name, _proxy_header_value = (
        part.strip() for part in _proxy_ssl_header.split("=", 1)
    )
    # Django matches this against ``request.META[name]``, whose HTTP-header
    # keys are WSGI-mangled: ``HTTP_`` prefix, dashes -> underscores, upper
    # case. Operators routinely set the on-the-wire name ('X-Forwarded-Proto')
    # and the setting then silently never matches -> ``request.is_secure()``
    # stays False behind a TLS proxy, a security downgrade with no error.
    # Normalise the wire form to the META key so both spellings work.
    if not _proxy_header_name.startswith("HTTP_"):
        _proxy_header_name = "HTTP_" + _proxy_header_name.upper().replace("-", "_")
    SECURE_PROXY_SSL_HEADER = (_proxy_header_name, _proxy_header_value)

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
# ``includeSubDomains`` extends the HSTS policy to every subdomain OF THIS
# host (for ``app.example.com`` that means ``*.app.example.com`` — NOT
# siblings like ``other.example.com`` and NOT the parent ``example.com``).
# It defaults OFF (opt-in), matching Django's own default: asserting HSTS for
# a subtree you may not fully control — or that still has HTTP-only hosts —
# locks browsers onto HTTPS for it irreversibly for the max-age window, and
# preloading amplifies that. A deploy that owns and HTTPS-serves its entire
# subtree opts in with ``AMELI_APP_HSTS_INCLUDE_SUBDOMAINS=true``. Unrecognised
# values fail closed (raise) like the other guards in this module. The flag is
# never emitted when HSTS is off.
_hsts_subdomains_env = os.environ.get("AMELI_APP_HSTS_INCLUDE_SUBDOMAINS", "").strip().lower()
if _hsts_subdomains_env in {"", "0", "false", "no", "off"}:
    _include_subdomains = False
elif _hsts_subdomains_env in {"1", "true", "yes", "on"}:
    _include_subdomains = True
else:
    raise RuntimeError(
        f"AMELI_APP_HSTS_INCLUDE_SUBDOMAINS={_hsts_subdomains_env!r} is not a "
        "boolean. Use true/false (or leave unset for the default of off). Set "
        "it to true only when this host owns and HTTPS-serves every subdomain "
        "beneath it — includeSubDomains locks browsers onto HTTPS for the "
        "whole subtree for the max-age window."
    )
SECURE_HSTS_INCLUDE_SUBDOMAINS = _include_subdomains and SECURE_HSTS_SECONDS > 0
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
