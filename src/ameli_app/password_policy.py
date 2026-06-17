from __future__ import annotations

import secrets
import string

MIN_PASSWORD_LENGTH = 12
ALLOWED_PASSWORD_SYMBOLS = "!@#$%^&*()-_=+?"  # noqa: S105 - allowlist constant, not a credential
ALLOWED_PASSWORD_CHARACTERS = (
    string.ascii_uppercase + string.ascii_lowercase + string.digits + ALLOWED_PASSWORD_SYMBOLS
)


def password_policy_help_text() -> str:
    return (
        f"Password must be at least {MIN_PASSWORD_LENGTH} characters long and include at least "
        f"one uppercase letter, one lowercase letter, one digit, and one allowed symbol "
        f"({ALLOWED_PASSWORD_SYMBOLS})."
    )


def validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must contain at least {MIN_PASSWORD_LENGTH} characters")
    if not any(char.isupper() for char in password):
        raise ValueError("password must contain at least one uppercase letter")
    if not any(char.islower() for char in password):
        raise ValueError("password must contain at least one lowercase letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("password must contain at least one digit")
    if not any(char in ALLOWED_PASSWORD_SYMBOLS for char in password):
        raise ValueError("password must contain at least one allowed symbol")
    invalid_symbols = sorted(
        {
            char
            for char in password
            if not char.isalnum() and char not in ALLOWED_PASSWORD_SYMBOLS
        }
    )
    if invalid_symbols:
        invalid_list = "".join(invalid_symbols)
        raise ValueError(
            f"password contains unsupported symbols: {invalid_list}. "
            f"Allowed symbols: {ALLOWED_PASSWORD_SYMBOLS}"
        )


def generate_compliant_password(length: int = 16) -> str:
    size = max(MIN_PASSWORD_LENGTH, int(length))
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(ALLOWED_PASSWORD_SYMBOLS),
    ]
    while len(required) < size:
        required.append(secrets.choice(ALLOWED_PASSWORD_CHARACTERS))
    secrets.SystemRandom().shuffle(required)
    candidate = "".join(required)
    validate_password_policy(candidate)
    return candidate
