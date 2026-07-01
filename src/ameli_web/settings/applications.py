"""INSTALLED_APPS, MIDDLEWARE, TEMPLATES, URL / WSGI / ASGI targets + silk conditional install.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

import os
from pathlib import Path

from .integrations import SILK_ENABLED

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
if SILK_ENABLED:
    INSTALLED_APPS.append("silk")

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
if SILK_ENABLED:
    # Silk's middleware must run AFTER auth (so it can attribute requests
    # to users) but BEFORE the request-body is consumed. Appending at
    # the end keeps it after our auth + session machinery; silk reads
    # the body lazily so it does not interfere with downstream
    # middleware that needs to re-read.
    MIDDLEWARE.append("silk.middleware.SilkyMiddleware")
    # Silk defaults below match docs/OPERATIONS.md § "django-silk
    # profiler". The most important one is SILKY_AUTHENTICATION /
    # SILKY_AUTHORISATION: the /silk/ panel exposes raw SQL and full
    # request data, so it MUST be gated to authenticated superadmins.
    SILKY_AUTHENTICATION = True
    SILKY_AUTHORISATION = True
    # Only request paths matching this regex get profiled — keep the
    # health probes / static assets out of the silk DB so it stays
    # small. Operators can override via env if they want everything.
    _silk_intercept = os.environ.get("AMELI_APP_SILK_INTERCEPT_REGEX", "").strip()
    if _silk_intercept:
        SILKY_INTERCEPT_REGEX = _silk_intercept
    else:
        SILKY_INTERCEPT_REGEX = r"^/(profile|admin|api)/"
    # Cap on records retained — silk would otherwise grow unbounded.
    SILKY_MAX_RECORDED_REQUESTS = int(
        os.environ.get("AMELI_APP_SILK_MAX_RECORDED_REQUESTS", "1000")
    )
    SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT = 10

ROOT_URLCONF = "ameli_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(Path(__file__).resolve().parent.parent / "templates")],
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
