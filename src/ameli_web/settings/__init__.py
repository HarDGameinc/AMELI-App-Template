"""Public Django settings entry point for the AMELI App Template.

After PC-4 (2026-07-01) the ~750-line ``settings.py`` was split into
domain modules under ``ameli_web/settings/``. Django only reads
``settings.<NAME>``; this module re-exports every constant from the
submodules in a deterministic order so the boot-time guards (secret,
allowed hosts, trusted proxies, audit key, MFA key, silk, AV, OTel,
message storage, email backend, path-inside-checkout) fire in the
same sequence they did in the monolithic file.

Import order matters: later submodules read constants defined by
earlier ones (e.g. ``applications.py`` reads ``SILK_ENABLED`` from
``integrations.py``). Do not reshuffle without tracing the
dependency graph.
"""
# ruff: noqa: I001, F401, F403
from __future__ import annotations

# 1. Base — env, secret, paths, ALLOWED_HOSTS, TRUSTED_PROXIES.
from .base import *

# 2. Third-party integrations — SRI, health allowlist, HIBP flag,
#    AV endpoint, OTel endpoint, silk toggles. Boot guards for AV /
#    OTel schemes and silk prod flag live here.
from .integrations import *

# 3. Auth basics — password hashers, validators, HMAC + MFA keys,
#    LOGIN_URL / LOGIN_REDIRECT_URL / AUTH_USER_MODEL.
from .auth import *

# 4. Cookies — session + CSRF cookie policy, __Host- prefix guards.
from .cookies import *

# 5. Security headers — HSTS, proxy SSL header, X-Frame-Options,
#    message storage allow-list.
from .security_headers import *

# 6. i18n + static + media — LANGUAGE_CODE, TIME_ZONE, STATIC_URL,
#    MEDIA_ROOT + path-inside-checkout guard.
from .i18n_static import *

# 6b. Media transform knobs — avatar resize/WebP/EXIF-strip pipeline
#     (D-5). Read only by services.images; no boot guards here.
from .media import *

# 7. Database — DATABASES + connection pool option.
from .database import *

# 8. Applications — INSTALLED_APPS, MIDDLEWARE, TEMPLATES, WSGI/ASGI,
#    ROOT_URLCONF, silk conditional install (reads SILK_ENABLED).
from .applications import *

# 9. Email — EMAIL_BACKEND, SMTP config, PASSWORD_RESET_TIMEOUT.
from .email import *

# Private helpers that ``from .X import *`` does NOT propagate (their
# leading underscore excludes them from wildcard re-export), but that
# tests and internal callers still access via ``ameli_web.settings._X``.
# Re-import explicitly so ``settings._database_settings`` (etc.) keeps
# resolving after the split.
from .base import _int_env, _IS_DEV_ENV
from .database import _database_settings, _db_pool_options, _default_sqlite_path
