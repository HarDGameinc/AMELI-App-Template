"""Data-migration correctness for ``accounts.0012_mfa_secret_encrypt``.

The reversibility round-trip in ``test_migrations.py`` exercises this
migration only as a **no-op** (dev/CI has no ``MFA_ENCRYPTION_KEY``), and
``test_mfa_secret_encryption.py`` covers the *runtime* encrypt/decrypt seam —
but the migration's own bulk backfill (walk every row, skip already-encrypted
ones, re-write plaintext) was untested. That is security-relevant code: a bug
here would leave TOTP shared secrets in plaintext at rest, or double-encrypt
and lock users out. These call the migration's ``RunPython`` callables
directly against the test DB.
"""
from __future__ import annotations

import importlib

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model

# The migration module name starts with a digit, so it cannot be a normal
# ``import``; pull it in by string.
_MIGRATION = importlib.import_module(
    "ameli_web.accounts.migrations.0012_mfa_secret_encrypt"
)
User = get_user_model()


def _make_user(username: str, secret: str):
    """Create a user with an exact raw ``mfa_secret`` (no service-layer
    encryption in the way — we want to control the at-rest bytes)."""
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
    )
    user.mfa_secret = secret
    user.save(update_fields=["mfa_secret"])
    return user


@pytest.mark.django_db
def test_forward_backfill_encrypts_only_plaintext_rows(settings):
    key = Fernet.generate_key().decode("ascii")
    settings.MFA_ENCRYPTION_KEY = key
    fernet = Fernet(key.encode("ascii"))

    plain = pyotp.random_base32()
    already = pyotp.random_base32()
    u_plain = _make_user("mig-plain", plain)
    u_empty = _make_user("mig-empty", "")
    u_enc = _make_user("mig-enc", fernet.encrypt(already.encode()).decode("ascii"))
    enc_before = u_enc.mfa_secret

    _MIGRATION.encrypt_existing_secrets(django_apps, None)

    u_plain.refresh_from_db()
    u_empty.refresh_from_db()
    u_enc.refresh_from_db()

    # Plaintext row is now ciphertext that decrypts back to the original.
    assert u_plain.mfa_secret != plain
    assert fernet.decrypt(u_plain.mfa_secret.encode("ascii")).decode() == plain
    # The "no secret" sentinel is left untouched.
    assert u_empty.mfa_secret == ""
    # An already-encrypted row is recognised and NOT re-encrypted (no double
    # wrap — otherwise a second migrate would corrupt it).
    assert u_enc.mfa_secret == enc_before
    assert fernet.decrypt(u_enc.mfa_secret.encode("ascii")).decode() == already


@pytest.mark.django_db
def test_forward_backfill_is_idempotent(settings):
    key = Fernet.generate_key().decode("ascii")
    settings.MFA_ENCRYPTION_KEY = key
    fernet = Fernet(key.encode("ascii"))
    plain = pyotp.random_base32()
    user = _make_user("mig-idem", plain)

    _MIGRATION.encrypt_existing_secrets(django_apps, None)
    user.refresh_from_db()
    once = user.mfa_secret

    _MIGRATION.encrypt_existing_secrets(django_apps, None)
    user.refresh_from_db()
    twice = user.mfa_secret

    # Second run detects the row is already encrypted and skips it.
    assert once == twice
    assert fernet.decrypt(twice.encode("ascii")).decode() == plain


@pytest.mark.django_db
def test_reverse_backfill_decrypts_rows(settings):
    key = Fernet.generate_key().decode("ascii")
    settings.MFA_ENCRYPTION_KEY = key
    fernet = Fernet(key.encode("ascii"))
    plain = pyotp.random_base32()
    user = _make_user("mig-rev", fernet.encrypt(plain.encode()).decode("ascii"))

    _MIGRATION.decrypt_existing_secrets(django_apps, None)

    user.refresh_from_db()
    assert user.mfa_secret == plain


@pytest.mark.django_db
def test_forward_backfill_without_key_is_noop(settings):
    """Dev/CI mode: no key configured → the backfill must not touch any row
    (runtime helpers pass plaintext through)."""
    settings.MFA_ENCRYPTION_KEY = ""
    plain = pyotp.random_base32()
    user = _make_user("mig-nokey", plain)

    _MIGRATION.encrypt_existing_secrets(django_apps, None)

    user.refresh_from_db()
    assert user.mfa_secret == plain
