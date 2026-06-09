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
    "django.middleware.security.SecurityMiddleware",
    "ameli_web.accounts.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "ameli_web.accounts.middleware.UserSessionMiddleware",
    "ameli_web.accounts.middleware.AdminAccessAuditMiddleware",
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

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "ameli_web.accounts.validators.PasswordPolicyValidator"},
]

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
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True  # we read the token from the {% csrf_token %} tag, not from JS.
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# When a TLS-terminating proxy (Caddy, nginx) sits in front, Django needs
# to know the original scheme to make ``request.is_secure()`` honest and
# to set ``Secure`` cookies correctly. Configure your proxy to forward
# ``X-Forwarded-Proto`` and uncomment the next line in production. Left
# commented out by default to avoid trusting a header from an unknown
# upstream when the operator is still bringing up TLS.
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS: only meaningful when the deploy is reachable over HTTPS, and
# easy to lock yourself out of staging if you set it too early. Off by
# default. Enable when TLS is stable.
SECURE_HSTS_SECONDS = 0

# Strict, source-friendly CSP. ``django-csp`` would give finer control
# but adding it ships fine for this baseline.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

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

PASSWORD_RESET_TIMEOUT = max(60, int(CFG.password_reset_timeout_seconds or 3600))
