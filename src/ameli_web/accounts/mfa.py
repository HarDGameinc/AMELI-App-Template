"""Pure helpers for the TOTP-based MFA flow.

The functions in this module do not touch Django ORM models so they
are trivial to unit-test and reuse from views, services and management
commands. Storage and user-binding live in services.py and views.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg

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


EMAIL_CODE_LENGTH = 6
EMAIL_CODE_TTL_SECONDS = 600  # 10 minutes
EMAIL_CODE_RESEND_INTERVAL_SECONDS = 60
EMAIL_CODE_HOURLY_LIMIT = 5


def generate_email_code() -> str:
    """Return a fresh 6-digit numeric code as a zero-padded string."""
    value = secrets.randbelow(10 ** EMAIL_CODE_LENGTH)
    return f"{value:0{EMAIL_CODE_LENGTH}d}"


def hash_email_code(code: str) -> str:
    """SHA-256 hex digest of the candidate email code (digits only)."""
    candidate = "".join(ch for ch in code if ch.isdigit())
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()


def email_codes_match(stored_hash: str, candidate: str) -> bool:
    """Constant-time check between a stored email-code hash and a candidate."""
    return hmac.compare_digest(stored_hash, hash_email_code(candidate))


def render_qr_svg(uri: str) -> str:
    """Render an otpauth:// URI as an inline SVG QR code.

    Uses SvgPathImage (single <path>) instead of the rect-based default
    so that the result embeds cleanly via innerHTML without inheriting
    surrounding styles. Strips the <?xml ... ?> prolog because browsers
    do not need it for inline SVG.
    """
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(uri, image_factory=factory, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    raw = buf.getvalue().decode("utf-8")
    if raw.startswith("<?xml"):
        raw = raw.split("?>", 1)[1].lstrip()
    return raw


# ============================ TOTP secret-at-rest encryption ============================
#
# ASVS V2.8.1-2.8.6 expects the TOTP shared secret to be encrypted at
# rest with a key distinct from the DB master credential. We wrap
# storage with Fernet (AES-128-CBC + HMAC-SHA256, authenticated) keyed
# off ``settings.MFA_ENCRYPTION_KEY`` — a 32-byte url-safe base64 token
# loaded from the env var ``AMELI_APP_MFA_ENCRYPTION_KEY``.
#
# Operating modes (mirrors the AUDIT_HMAC_KEY pattern):
#
# * Key unset (dev / CI): ``encrypt_secret`` and ``decrypt_secret``
#   pass through plaintext unchanged. Lets the dev environment work
#   without a key and lets tests that hard-code a base32 secret keep
#   working without touching them.
# * Key set: ``encrypt_secret`` returns a Fernet ciphertext;
#   ``decrypt_secret`` tries Fernet first and falls back to "treat as
#   plaintext" when ``InvalidToken`` fires. This second path is
#   essential during the rollout window when the production DB still
#   has legacy plaintext rows that have not been migrated yet — the
#   user can still log in while the data migration is running.
#
# The boot guard in ``settings.py`` refuses to start when the key is
# missing AND the environment is not ``dev``, so the "operator forgot
# the key in prod" misconfiguration cannot land silently.


def _fernet():
    """Resolve the Fernet instance from settings, or ``None`` when no
    key is configured. Cached as a module-level attribute so we do not
    re-instantiate per call.

    Importing ``cryptography.fernet`` here (lazy) keeps the dep optional
    for environments that explicitly do not enable MFA encryption — the
    template still boots without ``cryptography`` installed as long as
    no key is set.
    """
    from django.conf import settings

    key = getattr(settings, "MFA_ENCRYPTION_KEY", "") or ""
    if not key:
        return None
    cached = getattr(_fernet, "_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    from cryptography.fernet import Fernet

    instance = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    _fernet._cache = (key, instance)  # type: ignore[attr-defined]
    return instance


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a base32 TOTP secret for at-rest storage.

    Empty input round-trips to empty (we use ``""`` as the "no secret"
    sentinel everywhere; encrypting it would burn a constant ciphertext
    that still tests as truthy and break the existing ``bool(user.mfa_secret)``
    checks). Without a configured key the plaintext is returned as-is
    so dev / CI continue to work.
    """
    if not plaintext:
        return ""
    fernet = _fernet()
    if fernet is None:
        return plaintext
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored TOTP secret back to its base32 form.

    Three branches mirror the operating modes:

    * Empty stored value → empty plaintext (no secret).
    * No configured key → return as-is (dev mode; assumes the stored
      value is already plaintext).
    * Key configured → try Fernet decryption; on ``InvalidToken`` the
      stored value is treated as legacy plaintext and returned
      unchanged. This is the seam that keeps a running deploy
      authenticating users during the rollout window before the data
      migration has encrypted every existing row.
    """
    if not stored:
        return ""
    fernet = _fernet()
    if fernet is None:
        return stored
    try:
        return fernet.decrypt(stored.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 — InvalidToken or any decode error
        return stored
