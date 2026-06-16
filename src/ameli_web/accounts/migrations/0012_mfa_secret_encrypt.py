"""Migrate ``User.mfa_secret`` to encrypted-at-rest storage.

Two-step migration:

1. Schema change — grow ``mfa_secret.max_length`` from 64 to 255 so the
   Fernet ciphertext (~100 chars for a 32-char base32 input) fits.
2. Data backfill — when ``settings.MFA_ENCRYPTION_KEY`` is configured,
   walk every row with a non-empty ``mfa_secret`` that is NOT already
   Fernet-encoded and re-write it as ciphertext. When the key is unset
   the backfill is a no-op (dev / CI mode) — runtime decryption falls
   back to "treat as plaintext" via ``mfa.decrypt_secret``.

Idempotent: a second run finds every row already encrypted and skips.
The detection is via ``cryptography.fernet`` — if the row decrypts under
the live key it's already encrypted, otherwise it's plaintext (or
encrypted under a previous key, which is an operator-rotation concern
handled separately).
"""
from __future__ import annotations

from django.conf import settings
from django.db import migrations, models


def _try_decrypt(fernet, stored: str) -> bool:
    """Return True if ``stored`` is valid Fernet ciphertext under
    ``fernet`` — i.e. the row is already encrypted and we should skip.
    """
    try:
        fernet.decrypt(stored.encode("ascii"))
        return True
    except Exception:
        return False


def encrypt_existing_secrets(apps, schema_editor):
    """Forward backfill — encrypt any plaintext ``mfa_secret`` rows."""
    key = (getattr(settings, "MFA_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        # Dev / CI mode. Runtime helpers already pass-through plaintext
        # so no data conversion is required.
        return

    from cryptography.fernet import Fernet

    try:
        fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001 — bad key, surface a friendly error
        # The schema part of this migration (``AlterField``) already
        # applied before this RunPython step. Raising here aborts the
        # migration AFTER the column was widened — that's safe because
        # the runtime helpers tolerate plaintext rows under a configured
        # key (the rollout-window fallback). Operators fix the key and
        # re-run; rows stay readable in the meantime.
        raise RuntimeError(
            "AMELI_APP_MFA_ENCRYPTION_KEY is set but does not look like "
            "a valid Fernet key (must be 32 url-safe base64 bytes). "
            "Generate a fresh one with `python -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\"` and "
            "set it in the env file. Underlying error: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    User = apps.get_model("accounts", "User")
    qs = User.objects.exclude(mfa_secret="")
    for user in qs.iterator(chunk_size=200):
        if _try_decrypt(fernet, user.mfa_secret):
            # Already encrypted under the live key — skip.
            continue
        # Plaintext (or ciphertext under a previous key; operator-side
        # concern). Treat as plaintext and re-encrypt under the live key.
        cipher = fernet.encrypt(user.mfa_secret.encode("utf-8")).decode("ascii")
        User.objects.filter(pk=user.pk).update(mfa_secret=cipher)


def decrypt_existing_secrets(apps, schema_editor):
    """Reverse backfill — decrypt every Fernet row back to plaintext.

    Used when an operator runs ``migrate accounts 0011``. Without the
    key configured we cannot recover the plaintext, so we leave the
    ciphertext untouched and let the operator un-set the key + re-run.
    """
    key = (getattr(settings, "MFA_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return

    from cryptography.fernet import Fernet

    fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    User = apps.get_model("accounts", "User")
    qs = User.objects.exclude(mfa_secret="")
    for user in qs.iterator(chunk_size=200):
        try:
            plain = fernet.decrypt(user.mfa_secret.encode("ascii")).decode("utf-8")
        except Exception:
            # Already plaintext (legacy row that never got encrypted)
            # or encrypted under a key we don't hold — leave alone.
            continue
        User.objects.filter(pk=user.pk).update(mfa_secret=plain)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_maintenancemode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="mfa_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(encrypt_existing_secrets, decrypt_existing_secrets),
    ]
