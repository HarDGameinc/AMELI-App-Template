from __future__ import annotations

import base64

import pyotp
import pytest

from ameli_web.accounts.mfa import (
    RECOVERY_ALPHABET,
    RECOVERY_CODES_PER_ENROLLMENT,
    RECOVERY_TOTAL_CHARS,
    generate_recovery_code,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    normalize_recovery_code,
    provisioning_uri,
    recovery_codes_match,
    verify_totp,
)


# ---- TOTP secret ----


def test_generate_secret_is_valid_base32():
    secret = generate_secret()

    # pyotp emits base32 without padding; round-trip via base64.b32decode
    assert isinstance(secret, str)
    assert len(secret) >= 16
    # Should decode cleanly (Add padding if missing)
    padded = secret + "=" * ((-len(secret)) % 8)
    base64.b32decode(padded)


def test_generate_secret_returns_unique_values():
    samples = {generate_secret() for _ in range(20)}
    assert len(samples) == 20


# ---- Provisioning URI ----


def test_provisioning_uri_contains_username_and_issuer():
    uri = provisioning_uri("ABCDEFGHIJKLMNOP", username="admin", issuer="AMELI App Template")

    assert uri.startswith("otpauth://totp/")
    assert "admin" in uri
    # Issuer with spaces gets URL-encoded; check both possible forms
    assert "AMELI" in uri
    assert "secret=ABCDEFGHIJKLMNOP" in uri


# ---- TOTP verification ----


def test_verify_totp_accepts_current_code():
    secret = generate_secret()
    code = pyotp.TOTP(secret).now()

    assert verify_totp(secret, code) is True


def test_verify_totp_rejects_wrong_code():
    secret = generate_secret()
    code = pyotp.TOTP(secret).now()
    # Flip last digit to a different value
    wrong = code[:-1] + ("0" if code[-1] != "0" else "1")

    assert verify_totp(secret, wrong) is False


def test_verify_totp_rejects_empty_or_short_or_non_digit_input():
    secret = generate_secret()

    assert verify_totp(secret, "") is False
    assert verify_totp(secret, "12345") is False  # 5 digits
    assert verify_totp(secret, "abcdef") is False  # non-digit
    assert verify_totp("", "123456") is False  # no secret


def test_verify_totp_accepts_code_with_spaces():
    secret = generate_secret()
    code = pyotp.TOTP(secret).now()
    spaced = f"{code[:3]} {code[3:]}"

    assert verify_totp(secret, spaced) is True


# ---- Recovery codes ----


def test_generate_recovery_code_has_expected_format():
    code = generate_recovery_code()

    # XXXX-XXXX-XXXX with separators
    assert len(code) == RECOVERY_TOTAL_CHARS + 2  # two dashes
    groups = code.split("-")
    assert len(groups) == 3
    assert all(len(group) == 4 for group in groups)
    body = code.replace("-", "")
    assert all(ch in RECOVERY_ALPHABET for ch in body)


def test_generate_recovery_codes_returns_unique_set():
    codes = generate_recovery_codes()

    assert len(codes) == RECOVERY_CODES_PER_ENROLLMENT
    assert len(set(codes)) == RECOVERY_CODES_PER_ENROLLMENT


def test_generate_recovery_codes_respects_count_argument():
    codes = generate_recovery_codes(count=5)

    assert len(codes) == 5


# ---- Recovery code hashing ----


def test_normalize_recovery_code_uppercases_and_strips_unknown():
    raw = "  abcd efgh ijkl  "
    normalized = normalize_recovery_code(raw)

    # Lowercase letters get upper-cased, non-alphabet chars get dropped
    assert normalized == "ABCDEFGHIJKL"


def test_hash_recovery_code_is_deterministic_and_case_insensitive():
    a = hash_recovery_code("ABCD-EFGH-JKLM")
    b = hash_recovery_code("abcd-efgh-jklm")
    c = hash_recovery_code("ABCD EFGH JKLM")

    assert a == b == c
    assert isinstance(a, str)
    assert len(a) == 64  # sha256 hex digest


def test_recovery_codes_match_accepts_matching_pair():
    code = generate_recovery_code()
    stored = hash_recovery_code(code)

    assert recovery_codes_match(stored, code) is True
    # And case/space tolerant
    assert recovery_codes_match(stored, code.lower()) is True


def test_recovery_codes_match_rejects_non_matching():
    stored = hash_recovery_code("ABCD-EFGH-JKLM")

    assert recovery_codes_match(stored, "ABCD-EFGH-JKLN") is False
    assert recovery_codes_match(stored, "") is False
