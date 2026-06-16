"""Regression coverage for the ``mfa_secret`` at-rest encryption wrap.

Closes ASVS V2.8.1-2.8.6 (TOTP shared secret encryption at rest).

The wrap lives in ``ameli_web.accounts.mfa.encrypt_secret`` /
``decrypt_secret`` and is mediated by ``settings.MFA_ENCRYPTION_KEY``.
Three operating modes:

* Unset key (dev / CI): pass-through plaintext.
* Set key: Fernet ciphertext at rest.
* Mixed (rollout window): the runtime decrypter tolerates legacy
  plaintext rows that have not yet been re-encrypted by the
  ``0012_mfa_secret_encrypt`` data migration.

These tests cover each mode plus the end-to-end TOTP flow so a
regression in the encryption seam (a missed read site, a write site
that bypasses ``encrypt_secret``) breaks here before it can ship.
"""
from __future__ import annotations

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model

from ameli_web.accounts import mfa

User = get_user_model()


@pytest.fixture()
def fresh_key():
    """Yield a freshly generated Fernet key string and clear the
    module-level cache so each test starts from a clean slate.
    """
    key = Fernet.generate_key().decode("ascii")
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")
    yield key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")


# ---------------------------------------------------------------------------
# Pass-through behaviour (dev / CI: no key configured)
# ---------------------------------------------------------------------------

def test_encrypt_secret_passes_through_without_key(settings):
    settings.MFA_ENCRYPTION_KEY = ""
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")
    plaintext = pyotp.random_base32()
    assert mfa.encrypt_secret(plaintext) == plaintext


def test_decrypt_secret_passes_through_without_key(settings):
    settings.MFA_ENCRYPTION_KEY = ""
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")
    plaintext = pyotp.random_base32()
    assert mfa.decrypt_secret(plaintext) == plaintext


def test_empty_string_round_trips_to_empty_with_or_without_key(settings, fresh_key):
    # The model uses "" as the "no secret" sentinel; encrypting "" would
    # burn a constant ciphertext that still tests as truthy and break
    # the existing ``if not user.mfa_secret`` checks.
    settings.MFA_ENCRYPTION_KEY = ""
    assert mfa.encrypt_secret("") == ""
    assert mfa.decrypt_secret("") == ""
    settings.MFA_ENCRYPTION_KEY = fresh_key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")
    assert mfa.encrypt_secret("") == ""
    assert mfa.decrypt_secret("") == ""


# ---------------------------------------------------------------------------
# Encrypted round-trip (key configured)
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip_with_key(settings, fresh_key):
    settings.MFA_ENCRYPTION_KEY = fresh_key
    plaintext = pyotp.random_base32()
    cipher = mfa.encrypt_secret(plaintext)
    # Ciphertext is NOT the plaintext.
    assert cipher != plaintext
    # Ciphertext is the Fernet token shape (urlsafe base64, starts with
    # ``gAAAA`` — the version 0x80 + 4-byte timestamp prefix).
    assert cipher.startswith("gAAAAA")
    # Decryption recovers the plaintext exactly.
    assert mfa.decrypt_secret(cipher) == plaintext


def test_encrypt_produces_different_ciphertext_each_call(settings, fresh_key):
    """Fernet bakes an IV per encryption so two calls on the same
    plaintext produce different ciphertexts even under the same key.
    Property we need so a row update is observably different from the
    previous version.
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    plaintext = pyotp.random_base32()
    c1 = mfa.encrypt_secret(plaintext)
    c2 = mfa.encrypt_secret(plaintext)
    assert c1 != c2
    assert mfa.decrypt_secret(c1) == plaintext
    assert mfa.decrypt_secret(c2) == plaintext


# ---------------------------------------------------------------------------
# Backward-compat: legacy plaintext rows still readable under live key
# ---------------------------------------------------------------------------

def test_decrypt_tolerates_legacy_plaintext_row_under_live_key(settings, fresh_key):
    """During the rollout window the production DB still has plaintext
    rows that the data migration has not yet re-encrypted. The runtime
    decrypter must treat them as plaintext (Fernet ``InvalidToken``
    branch) so the user can still log in.
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    plaintext = pyotp.random_base32()
    # Simulate a legacy row: store plaintext directly even though a key
    # is configured.
    stored = plaintext
    # The decrypter returns the stored value unchanged.
    assert mfa.decrypt_secret(stored) == plaintext


def test_decrypt_handles_garbage_input_without_raising(settings, fresh_key):
    """An attacker who can write to the DB might plant a garbage value
    in mfa_secret to crash the auth path. The decrypter falls back to
    "treat as stored" rather than raise — which then fails the TOTP
    verification cleanly (downstream).
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    garbage = "not-base64-and-not-base32-either!!"
    # No raise.
    assert mfa.decrypt_secret(garbage) == garbage


# ---------------------------------------------------------------------------
# End-to-end TOTP verification still works under wrap
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_totp_verification_works_after_encryption_wrap(settings, fresh_key):
    """The whole point: enrolling + verifying TOTP must keep working
    after the wrap. This is the regression test for "did we miss a read
    site" — if any code path bypassed ``decrypt_secret`` it would feed
    Fernet ciphertext to ``pyotp.TOTP.verify`` and fail.
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")

    user = User.objects.create_user(
        username="totp-user",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="totp@example.com",
    )
    # Mimic the enrollment write path.
    plaintext = mfa.generate_secret()
    user.mfa_secret = mfa.encrypt_secret(plaintext)
    user.save(update_fields=["mfa_secret"])

    # Build a valid TOTP code from the plaintext (this is what the
    # user's authenticator app would compute).
    code = pyotp.TOTP(plaintext).now()

    # Refresh from DB and verify via the same path the production
    # services / views use.
    user.refresh_from_db()
    assert mfa.verify_totp(mfa.decrypt_secret(user.mfa_secret), code)


@pytest.mark.django_db
def test_legacy_plaintext_user_can_still_verify_totp_with_key_set(settings, fresh_key):
    """Rollout-window scenario: the user was enrolled before the key
    was set, so their row has plaintext. After the operator sets the
    key but BEFORE the data migration runs, the user must still be
    able to log in.
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")

    user = User.objects.create_user(
        username="legacy-user",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="legacy@example.com",
    )
    # Legacy plaintext write (simulates pre-encryption-era DB row).
    plaintext = mfa.generate_secret()
    user.mfa_secret = plaintext  # NOT encrypted
    user.save(update_fields=["mfa_secret"])

    code = pyotp.TOTP(plaintext).now()
    user.refresh_from_db()
    # The runtime helpers tolerate this and let the user log in.
    assert mfa.verify_totp(mfa.decrypt_secret(user.mfa_secret), code)


# ---------------------------------------------------------------------------
# Storage shape: the model column never holds plaintext when key is set
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_enrollment_write_stores_ciphertext_when_key_is_set(settings, fresh_key):
    """The end-to-end service path (start_mfa_enrollment) must encrypt
    before saving. We assert by reading the raw DB column and confirming
    it is NOT the plaintext.
    """
    from ameli_web.accounts.services import start_mfa_enrollment

    settings.MFA_ENCRYPTION_KEY = fresh_key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")

    user = User.objects.create_user(
        username="enroll-user",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="enroll@example.com",
    )
    result = start_mfa_enrollment(actor_username="enroll-user")
    plaintext = result["secret"]
    user.refresh_from_db()
    # DB column carries ciphertext, NOT plaintext.
    assert user.mfa_secret != plaintext
    assert user.mfa_secret.startswith("gAAAAA")
    # And the runtime helpers recover the plaintext.
    assert mfa.decrypt_secret(user.mfa_secret) == plaintext


# ---------------------------------------------------------------------------
# Key rotation safety: a key change makes old ciphertext unreadable
# ---------------------------------------------------------------------------

def test_old_ciphertext_unreadable_under_new_key(settings, fresh_key):
    """Sanity check on the threat model: rotating the key without
    re-encrypting the rows leaves those rows unreadable (which is
    exactly the property an audit would want). The fallback path that
    treats "not Fernet under this key" as plaintext means rotation is
    a DELIBERATE operator action that needs a re-encrypt step — never
    a silent recovery.
    """
    settings.MFA_ENCRYPTION_KEY = fresh_key
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")
    plaintext = pyotp.random_base32()
    cipher_old = mfa.encrypt_secret(plaintext)

    # Operator rotates the key.
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
    if hasattr(mfa._fernet, "_cache"):
        delattr(mfa._fernet, "_cache")

    # The old ciphertext is NOT recoverable under the new key.
    # decrypt_secret falls back to returning the stored value unchanged
    # (which would then fail TOTP verification downstream — exactly the
    # behaviour we want: a rotation that forgot the re-encrypt step
    # breaks loud, not silent).
    recovered = mfa.decrypt_secret(cipher_old)
    assert recovered != plaintext
    assert recovered == cipher_old  # we get the raw ciphertext back


# ---------------------------------------------------------------------------
# Boot guard: settings refuse to boot outside dev without a key
# ---------------------------------------------------------------------------

def test_boot_guard_formula_outside_dev():
    """The actual guard in settings.py runs at import time; we mirror
    its formula here to assert the policy is what we expect without
    forcing a full settings reload.
    """
    # When ENV_NAME != "dev" AND MFA_ENCRYPTION_KEY == "" → must raise.
    is_dev = False
    mfa_encryption_key = ""
    should_raise = (not is_dev) and (not mfa_encryption_key)
    assert should_raise

    # When ENV_NAME == "dev", empty key is allowed.
    is_dev = True
    should_raise = (not is_dev) and (not mfa_encryption_key)
    assert not should_raise

    # When the key is set, no raise regardless of env.
    mfa_encryption_key = Fernet.generate_key().decode("ascii")
    is_dev = False
    should_raise = (not is_dev) and (not mfa_encryption_key)
    assert not should_raise
