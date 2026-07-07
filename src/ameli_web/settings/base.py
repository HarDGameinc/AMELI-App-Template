"""Bootstrap: paths, environment name, secret key, ALLOWED_HOSTS, TRUSTED_PROXIES.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
Every other submodule reads ``CFG``, ``ENV_NAME``, ``_IS_DEV_ENV``,
``BASE_DIR``, ``PROJECT_DIR`` and ``_int_env`` from here — keep them
here so the import graph is a tree, not a cycle.
"""
from __future__ import annotations

import os
from pathlib import Path

from ameli_app.config import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
PROJECT_DIR = BASE_DIR
CFG = load_settings()
ENV_NAME = (os.environ.get("APP_ENV", "").strip().lower() or CFG.environment or "dev")
SECRET_KEY = CFG.django_secret_key
DEBUG = CFG.django_debug

# Boot-time guards: refuse to start a non-dev deploy that still uses the
# repo's bundled defaults for SECRET_KEY or DEBUG. These are the two
# misconfigurations most likely to leak through a copy-paste install
# and they have outsized impact (session forgery, traceback PII leak).
_INSECURE_DEFAULT_SECRET = "ameli-app-dev-secret-key"  # noqa: S105 (intentional reference)
_IS_DEV_ENV = ENV_NAME == "dev"

if SECRET_KEY == _INSECURE_DEFAULT_SECRET and not _IS_DEV_ENV:
    raise RuntimeError(
        "AMELI_APP_DJANGO_SECRET_KEY is the bundled default; refuse to boot "
        "outside the dev environment. Generate one with "
        "`python -c 'import secrets; print(secrets.token_urlsafe(60))'` "
        "and set it in the env file."
    )
if DEBUG and not _IS_DEV_ENV:
    raise RuntimeError(
        "AMELI_APP_DJANGO_DEBUG=true is not allowed outside the dev environment. "
        "Debug mode leaks SECRET_KEY, env vars, and stack traces."
    )

_default_allowed = "*" if _IS_DEV_ENV else ""
ALLOWED_HOSTS = [
    item.strip()
    for item in os.environ.get("AMELI_APP_DJANGO_ALLOWED_HOSTS", _default_allowed).split(",")
    if item.strip()
]
if not ALLOWED_HOSTS:
    raise RuntimeError(
        "AMELI_APP_DJANGO_ALLOWED_HOSTS is empty. Set it to the comma-separated "
        "list of hostnames this deploy answers to (e.g. 'metro.lan,10.0.0.5'). "
        "Wildcards are accepted only in the dev environment."
    )
if "*" in ALLOWED_HOSTS and not _IS_DEV_ENV:
    raise RuntimeError(
        "AMELI_APP_DJANGO_ALLOWED_HOSTS contains '*' outside the dev environment. "
        "Wildcards enable Host header injection and password reset poisoning."
    )

CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.environ.get("AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]

# Wrong settings here are silent: a missing entry makes throttling and audit
# IPs collapse onto the proxy address; an extra entry lets the next hop
# spoof IPs. We force the operator to make this decision explicitly outside
# the dev environment, defaulting to just loopback in dev for convenience.
_trusted_proxies_env = os.environ.get("AMELI_APP_TRUSTED_PROXIES", "").strip()
if _trusted_proxies_env:
    TRUSTED_PROXIES = {
        item.strip() for item in _trusted_proxies_env.split(",") if item.strip()
    }
elif _IS_DEV_ENV:
    TRUSTED_PROXIES = {"127.0.0.1", "::1"}
else:
    raise RuntimeError(
        "AMELI_APP_TRUSTED_PROXIES is empty outside the dev environment. "
        "Set it to the comma-separated list of REMOTE_ADDR values for the "
        "reverse proxies sitting in front of this deploy (typically "
        "'127.0.0.1,::1' when Caddy/nginx runs on the same host). Leaving "
        "it blank collapses throttling onto the proxy address and lets the "
        "first hop spoof client IPs."
    )


def _int_env(name: str, *, default: int) -> int:
    """Shared helper — parse an int from env with a default fallback."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
