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
ALLOWED_HOSTS = [
    item.strip() for item in os.environ.get("AMELI_APP_DJANGO_ALLOWED_HOSTS", "*").split(",") if item.strip()
]
CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.environ.get("AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]


def _default_sqlite_path() -> str:
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
    if parsed.scheme not in {"postgres", "postgresql"}:
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "ameli_web.accounts.middleware.UserSessionMiddleware",
    "ameli_web.accounts.middleware.AdminAccessAuditMiddleware",
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
SESSION_COOKIE_SECURE = bool(CFG.session_cookie_secure)
SESSION_COOKIE_AGE = max(300, int(CFG.session_max_age_seconds or 43200))
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
