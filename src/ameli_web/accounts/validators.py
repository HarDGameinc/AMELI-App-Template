from __future__ import annotations

from django.core.exceptions import ValidationError

from ameli_app.password_policy import password_policy_help_text, validate_password_policy


class PasswordPolicyValidator:
    def validate(self, password, user=None) -> None:
        try:
            validate_password_policy(str(password or ""))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def get_help_text(self) -> str:
        return password_policy_help_text()
