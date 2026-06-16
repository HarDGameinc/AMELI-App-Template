from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from ameli_app.config import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
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

# Subresource Integrity hashes for third-party JS/CSS we load from a
# public CDN (Swagger UI + ReDoc, in dashboard/views.py). The dashboard
# helpers render ``integrity="sha384-..."`` only when a value is set,
# so the unconfigured baseline still serves the docs pages without
# hard-failing — pinning the version (above) is the first defence,
# integrity is the second. Operators can compute hashes once with:
#
#   curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A
#
# and paste them into env vars below.
CDN_SRI_HASHES = {
    "swagger_ui_css": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_CSS", "").strip(),
    "swagger_ui_bundle": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_BUNDLE", "").strip(),
    "swagger_ui_preset": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_PRESET", "").strip(),
    "redoc_bundle": os.environ.get("AMELI_APP_SRI_REDOC_BUNDLE", "").strip(),
}

# Operational endpoints (``/health``, ``/api/health``, ``/metrics``) are
# public by default so probes and Prometheus scrapers reach them without
# fuss. When this list has at least one entry, the views refuse any
# client IP not in the list — useful when the deploy is exposed on a
# network where ``/health`` would leak version and uptime to anyone.
HEALTH_METRICS_ALLOWLIST = {
    item.strip()
    for item in os.environ.get("AMELI_APP_HEALTH_METRICS_ALLOWLIST", "").split(",")
    if item.strip()
}
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


def _default_sqlite_path() -> str:
    # SQLite is intentionally kept only as a local fallback when DATABASE_URL
    # is not configured. Real installs are expected to use PostgreSQL.
    explicit = os.environ.get("AMELI_APP_SQLITE_PATH", "").strip()
    if explicit:
        return explicit
    if CFG.data_dir:
        return str(CFG.data_dir / "django-dev.sqlite3")
    return str(Path(tempfile.gettempdir()) / "ameli-app-template-django-dev.sqlite3")


def _database_settings() -> dict[str, str]:
    dsn = (CFG.database_url or "").strip()
    if not dsn:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _default_sqlite_path(),
        }

    parsed = urlparse(dsn)
    base_scheme = parsed.scheme.split("+", 1)[0]
    if base_scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(f"Unsupported DATABASE_URL scheme for Django: {parsed.scheme}")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ameli_web.accounts",
    "ameli_web.audit",
    "ameli_web.dashboard",
]

MIDDLEWARE = [
    "ameli_web.request_id.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "ameli_web.accounts.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "ameli_web.accounts.middleware.UserSessionMiddleware",
    "ameli_web.accounts.middleware.MaintenanceModeMiddleware",
    "ameli_web.accounts.middleware.MustChangePasswordMiddleware",
    "ameli_web.accounts.middleware.AdminAccessAuditMiddleware",
    "ameli_web.accounts.middleware.DjangoAdminSudoGateMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ameli_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(Path(__file__).resolve().parent / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "ameli_web.accounts.context_processors.account_navigation",
            ],
        },
    }
]

WSGI_APPLICATION = "ameli_web.wsgi.application"
ASGI_APPLICATION = "ameli_web.asgi.application"

DATABASES = {"default": _database_settings()}

# Argon2id is the OWASP-recommended hasher and resists GPU attacks better
# than PBKDF2-SHA256. We use a custom subclass that reads its work
# factors from settings so an operator can tune them per deploy without
# touching the source. PBKDF2 stays as a fallback so existing hashes
# keep verifying; Django re-encodes them with Argon2 on the next
# successful login (``UPDATE_LAST_LOGIN_ENCODING`` behaviour) — and the
# same re-encode kicks in when an operator bumps a work factor.
PASSWORD_HASHERS = [
    "ameli_web.accounts.hashers.ConfigurableArgon2Hasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# Argon2id work factors. Defaults match Django's bundled hasher; the
# operator can raise them on beefier hardware to push back against an
# offline GPU-cluster cracker without forking Django. See
# ``accounts/hashers.py`` for the OWASP reference and the live-rehash
# semantics.
ARGON2_TIME_COST = int(os.environ.get("AMELI_APP_ARGON2_TIME_COST", "2"))
ARGON2_MEMORY_COST = int(os.environ.get("AMELI_APP_ARGON2_MEMORY_COST", "102400"))
ARGON2_PARALLELISM = int(os.environ.get("AMELI_APP_ARGON2_PARALLELISM", "8"))

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "ameli_web.accounts.validators.PasswordPolicyValidator"},
    {"NAME": "ameli_web.accounts.validators.HIBPPasswordValidator"},
]

# Toggle the HIBP k-anonymity check. Off by default to keep the baseline
# network-independent (the validator silently passes when this is false
# or when the network call fails). Operators in a position to make the
# outbound call can flip it on for an extra layer of defence.
HIBP_PASSWORD_CHECK = os.environ.get("AMELI_APP_HIBP_PASSWORD_CHECK", "").strip().lower() in {
    "1", "true", "yes", "on",
}

# Secret key for the audit-log HMAC chain. When set, every audit row is
# stamped with HMAC-SHA256 over its canonical payload + the previous
# row's hmac, so ``ameli-app verify-audit`` can detect tampering after
# the fact (edited row, deleted row, reordered row). Leave blank to keep
# the chain off — rows still write, just without an integrity stamp.
#
# Generate one with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# and paste it into AMELI_APP_AUDIT_HMAC_KEY in the env file. Once set
# DO NOT rotate without re-anchoring or all historical rows fail
# verification.
AUDIT_HMAC_KEY = os.environ.get("AMELI_APP_AUDIT_HMAC_KEY", "").strip()

# TOTP shared secrets are wrapped with Fernet (AES-128-CBC + HMAC-SHA256)
# before they hit the DB. The key is a 32-byte url-safe base64 token —
# generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# and paste it into AMELI_APP_MFA_ENCRYPTION_KEY in the env file.
#
# Leave blank to keep the secret in plaintext (dev / CI convenience).
# Outside ``dev`` the boot guard below refuses to start without a key.
# Encryption is a different secret from SECRET_KEY and AUDIT_HMAC_KEY
# on purpose — losing one should not compromise the others.
MFA_ENCRYPTION_KEY = os.environ.get("AMELI_APP_MFA_ENCRYPTION_KEY", "").strip()

if not _IS_DEV_ENV and not MFA_ENCRYPTION_KEY:
    raise RuntimeError(
        "AMELI_APP_MFA_ENCRYPTION_KEY is empty outside the dev environment. "
        "Without it, TOTP secrets land in the DB as plaintext (ASVS V2.8 gap). "
        "Generate one with `python -c 'from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())'` and set it in the env file."
    )

LANGUAGE_CODE = "es-cl"
TIME_ZONE = CFG.timezone or "America/Santiago"
USE_I18N = True
USE_TZ = True

# Languages we ship with the Template. Operators can add more by dropping
# additional ``.po`` files under ``locale/<code>/LC_MESSAGES/django.po``
# and registering the code here.
LANGUAGES = [
    ("es", "Espanol"),
    ("en", "English"),
]
LOCALE_PATHS = [str(PROJECT_DIR / "locale")]

STATIC_URL = "/static/"
STATICFILES_DIRS = [str(PROJECT_DIR / "src" / "ameli_app" / "static")]
MEDIA_ROOT = str(CFG.profile_uploads_dir)
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/profile/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_NAME = CFG.session_cookie_name or "ameli_app_session"
# Default to secure cookies outside dev so the operator opts INTO an
# insecure deploy explicitly rather than the other way around.
SESSION_COOKIE_SECURE = bool(CFG.session_cookie_secure) if _IS_DEV_ENV else True
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

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --- Email / password reset --------------------------------------------------
_EMAIL_BACKEND_MAP = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "file": "django.core.mail.backends.filebased.EmailBackend",
    "locmem": "django.core.mail.backends.locmem.EmailBackend",
    "dummy": "django.core.mail.backends.dummy.EmailBackend",
}
EMAIL_BACKEND = _EMAIL_BACKEND_MAP.get(
    CFG.email_backend, "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = CFG.email_host or ""
EMAIL_PORT = CFG.email_port or 587
EMAIL_HOST_USER = CFG.email_username or ""
EMAIL_HOST_PASSWORD = CFG.email_password or ""
EMAIL_USE_TLS = bool(CFG.email_use_tls)
EMAIL_USE_SSL = bool(CFG.email_use_ssl)
DEFAULT_FROM_EMAIL = CFG.email_from_address or "noreply@ameli-template.local"
if EMAIL_BACKEND == "django.core.mail.backends.filebased.EmailBackend":
    EMAIL_FILE_PATH = str((CFG.data_dir / "outbox").resolve())

# Outside dev, refuse to boot when there is no real outbound email
# pipeline. The console / dummy / locmem backends keep mail in memory
# so password reset and MFA-email flows silently fail — operators
# would not learn that until a user got locked out. Forcing the issue
# at startup avoids the silent broken-state.
if not _IS_DEV_ENV:
    _email_backend_label = (CFG.email_backend or "console").lower()
    if _email_backend_label not in {"smtp", "file"}:
        raise RuntimeError(
            "email.backend must be 'smtp' (real outbound) or 'file' "
            "(disk outbox for review) outside the dev environment. "
            f"Got '{_email_backend_label}'. Without it the password "
            "reset and MFA-by-email flows silently fail."
        )
    if _email_backend_label == "smtp" and not EMAIL_HOST:
        raise RuntimeError(
            "email.backend is 'smtp' but email.host is empty. Set "
            "AMELI_APP_EMAIL_HOST (or the YAML key) to the SMTP relay "
            "host so password reset and MFA-by-email can deliver."
        )

PASSWORD_RESET_TIMEOUT = max(60, int(CFG.password_reset_timeout_seconds or 3600))
