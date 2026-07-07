"""Password hashers + validators + auth-related crypto keys + auth routing.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
Groups: password hashing (Argon2id + fallbacks), password policy
validators, audit HMAC key, MFA encryption key, login URLs, AUTH_USER_MODEL.
"""
from __future__ import annotations

import os

from .base import _IS_DEV_ENV

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

# Secret key for the audit-log HMAC chain. When set, every audit row is
# stamped with HMAC-SHA256 over its canonical payload + the previous
# row's hmac, so ``ameli-app verify-audit`` can detect tampering after
# the fact (edited row, deleted row, reordered row).
#
# Generate one with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# and paste it into AMELI_APP_AUDIT_HMAC_KEY in the env file. Once set
# DO NOT rotate without re-anchoring or all historical rows fail
# verification.
#
# Empty value: in ``dev`` rows still write without an integrity stamp
# (convenient for local CI / first-boot). Outside dev the boot guard
# below refuses to start without a key — forgetting it in prod used to
# silently disable the entire chain (independent security audit
# 2026-06-19 flagged this as a HIGH finding).
AUDIT_HMAC_KEY = os.environ.get("AMELI_APP_AUDIT_HMAC_KEY", "").strip()

if not _IS_DEV_ENV and not AUDIT_HMAC_KEY:
    raise RuntimeError(
        "AMELI_APP_AUDIT_HMAC_KEY is empty outside the dev environment. "
        "Without it, audit rows write with hmac='' and the chain integrity "
        "check (ASVS V7.3.2, V6.3.1) is vacuously disabled — tampering goes "
        "undetected. Generate one with `python -c \"import secrets; "
        "print(secrets.token_urlsafe(48))\"` and paste it into "
        "AMELI_APP_AUDIT_HMAC_KEY in the env file. Once set DO NOT rotate "
        "without re-anchoring (see `ameli-app rotate-audit-key`)."
    )

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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/profile/"
LOGOUT_REDIRECT_URL = "/login/"
