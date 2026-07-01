"""Email backend + SMTP config + password reset TTL.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

from .base import _IS_DEV_ENV, CFG

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
