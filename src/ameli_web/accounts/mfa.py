"""Pure helpers for the TOTP-based MFA flow.

The functions in this module do not touch Django ORM models so they
are trivial to unit-test and reuse from views, services and management
commands. Storage and user-binding live in services.py and views.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import pyotp

# Alphabet without easily-confused characters (0/O, 1/I/l). Used for
# recovery codes only; the TOTP secret itself uses base32 via pyotp.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_GROUP_SIZE = 4
RECOVERY_GROUPS = 3  # final code looks like XXXX-XXXX-XXXX (12 chars)
RECOVERY_TOTAL_CHARS = RECOVERY_GROUP_SIZE * RECOVERY_GROUPS
RECOVERY_CODES_PER_ENROLLMENT = 10


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret suitable for authenticator apps."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    """Build the otpauth:// URI that authenticator apps consume from a QR."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """Verify a TOTP code against the secret with a small drift tolerance.

    `valid_window=1` accepts the current step plus the previous and next
    30-second windows so a small clock drift does not lock the user out.
    """
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return bool(pyotp.TOTP(secret).verify(code, valid_window=valid_window))


def generate_recovery_code() -> str:
    """Return a single recovery code in XXXX-XXXX-XXXX format."""
    chars = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_TOTAL_CHARS))
    groups = [chars[i : i + RECOVERY_GROUP_SIZE] for i in range(0, RECOVERY_TOTAL_CHARS, RECOVERY_GROUP_SIZE)]
    return "-".join(groups)


def generate_recovery_codes(count: int = RECOVERY_CODES_PER_ENROLLMENT) -> list[str]:
    """Return `count` unique recovery codes."""
    seen: set[str] = set()
    while len(seen) < count:
        seen.add(generate_recovery_code())
    return sorted(seen)


def normalize_recovery_code(code: str) -> str:
    """Canonicalize a code for hashing/lookup.

    Drops anything that is not an alphabet character (including dashes,
    spaces and the easily-confused characters intentionally excluded
    from the alphabet) and upper-cases the rest. This means a user may
    type the code in any combination of capitalization, spacing or
    separator style and still match the stored hash.
    """
    return "".join(ch for ch in code.upper() if ch in RECOVERY_ALPHABET)


def hash_recovery_code(code: str) -> str:
    """SHA-256 hex digest of the canonical recovery code form."""
    canonical = normalize_recovery_code(code)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recovery_codes_match(stored_hash: str, candidate: str) -> bool:
    """Constant-time comparison between a stored hash and a candidate code."""
    return hmac.compare_digest(stored_hash, hash_recovery_code(candidate))
