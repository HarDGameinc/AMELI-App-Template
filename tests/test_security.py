import pytest

from ameli_app.password_policy import generate_compliant_password, validate_password_policy


def test_generated_password_complies():
    password = generate_compliant_password()

    validate_password_policy(password)
    assert len(password) >= 12


def test_password_policy_requires_allowed_symbol():
    with pytest.raises(ValueError):
        validate_password_policy("NoAllowedSymbol12")


def test_password_policy_rejects_unsupported_symbol():
    with pytest.raises(ValueError):
        validate_password_policy("ValidLikeThis12~A")
