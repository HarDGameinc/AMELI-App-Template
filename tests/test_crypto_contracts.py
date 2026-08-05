"""Upstream finding T-7 (2026-08-04): ``decrypt_secret`` never raising is a
deliberate CONTRACT (a wrong-key rotation or a legacy plaintext row must
surface as a failed auth, not a 500). A fork copied the pattern and added a
``json.loads`` after the fallback, breaking it. Pin the contract here.
"""
from __future__ import annotations

from cryptography.fernet import Fernet
from django.conf import settings

from ameli_web.accounts import mfa


def _set_key(monkeypatch, key: str) -> None:
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", key)
    # Drop the per-key cache so the next _fernet() rebuilds with the new key.
    monkeypatch.setattr(mfa._fernet, "_cache", None, raising=False)


def test_decrypt_secret_returns_input_on_invalid_token(monkeypatch):
    _set_key(monkeypatch, Fernet.generate_key().decode())
    # Not valid Fernet ciphertext -> InvalidToken -> returned unchanged, NO raise.
    assert mfa.decrypt_secret("legacy-plaintext-not-ciphertext") == \
        "legacy-plaintext-not-ciphertext"


def test_decrypt_secret_never_raises_after_key_rotation(monkeypatch):
    key_a = Fernet.generate_key().decode()
    _set_key(monkeypatch, key_a)
    token = mfa.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"  # actually encrypted

    # Rotate to a different key: the old token can't be opened.
    _set_key(monkeypatch, Fernet.generate_key().decode())
    # Must NOT raise — returns the (now-undecryptable) stored value as-is.
    assert mfa.decrypt_secret(token) == token


def test_decrypt_secret_roundtrips_and_handles_empty(monkeypatch):
    _set_key(monkeypatch, Fernet.generate_key().decode())
    assert mfa.decrypt_secret(mfa.encrypt_secret("JBSWY3DPEHPK3PXP")) == "JBSWY3DPEHPK3PXP"
    assert mfa.decrypt_secret("") == ""
