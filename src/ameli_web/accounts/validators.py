from __future__ import annotations

import hashlib
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError

from ameli_app.password_policy import password_policy_help_text, validate_password_policy

logger = logging.getLogger(__name__)


class PasswordPolicyValidator:
    def validate(self, password, user=None) -> None:
        try:
            validate_password_policy(str(password or ""))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def get_help_text(self) -> str:
        return password_policy_help_text()


HIBP_API_URL = "https://api.pwnedpasswords.com/range/{prefix}"


def _query_hibp(prefix: str, *, timeout: float = 3.0) -> str:
    """Tiny indirection around the HIBP API so tests can mock it cleanly.

    We do NOT use ``requests`` to keep the template dependency-free.
    """
    req = Request(
        HIBP_API_URL.format(prefix=prefix),
        headers={
            "User-Agent": "AMELI-App-Template-HIBP",
            "Add-Padding": "true",  # HIBP returns extra padding entries when set
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


class HIBPPasswordValidator:
    """Reject passwords known to appear in public breaches via Have I Been
    Pwned's k-anonymity API.

    The validator never sends the plaintext or full hash off-box: only
    the first five characters of the SHA-1 hash go over the wire, and
    the server returns the set of full-hash suffixes that share that
    prefix. We compare locally — the actual password remains private.

    Disabled by default to keep the baseline network-independent. Flip
    on via ``AMELI_APP_HIBP_PASSWORD_CHECK=true`` (read into
    ``settings.HIBP_PASSWORD_CHECK`` in settings.py).

    Network failures are not fatal: the validator audits via the
    configured logger and lets the password through. The policy
    validator above is the strict gate; HIBP is best-effort defence in
    depth.
    """

    threshold = 1
    """Reject if the password appears at least this many times in the
    HIBP corpus. ``1`` blocks any leaked password regardless of how
    obscure the breach; raise to ``50`` or so if you want to tolerate
    historic noise."""

    def __init__(self, threshold: int | None = None) -> None:
        if threshold is not None:
            self.threshold = int(threshold)

    def _enabled(self) -> bool:
        return bool(getattr(settings, "HIBP_PASSWORD_CHECK", False))

    def validate(self, password, user=None) -> None:
        if not self._enabled():
            return
        plaintext = str(password or "")
        if not plaintext:
            return
        digest = hashlib.sha1(plaintext.encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            body = _query_hibp(prefix)
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("HIBP check unavailable; allowing password: %s", exc)
            return
        # Each line is "SUFFIX:COUNT". Walk until we find ours.
        for line in body.splitlines():
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            if parts[0].strip().upper() != suffix:
                continue
            try:
                count = int(parts[1].strip())
            except ValueError:
                continue
            if count >= self.threshold:
                raise ValidationError(
                    "Esta contrasena aparece en breaches publicos conocidos "
                    "(HIBP). Elegi otra que no este filtrada.",
                )
            return

    def get_help_text(self) -> str:
        return (
            "Comprobamos contra Have I Been Pwned para rechazar claves que "
            "ya se filtraron en breaches publicos."
        )
