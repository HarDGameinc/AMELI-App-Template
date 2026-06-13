from __future__ import annotations

import pytest

from ameli_app.config import _read_secret_file, _resolve_email_password


def test_resolve_uses_explicit_env_first(monkeypatch, tmp_path):
    pwd_file = tmp_path / "secret.txt"
    pwd_file.write_text("from-file\n")
    monkeypatch.setenv("AMELI_APP_EMAIL_PASSWORD", "from-env")

    result = _resolve_email_password({"password_file": str(pwd_file)})

    assert result == "from-env"


def test_resolve_uses_password_file_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD", raising=False)
    pwd_file = tmp_path / "secret.txt"
    pwd_file.write_text("from-file-content\n")

    result = _resolve_email_password({"password_file": str(pwd_file)})

    assert result == "from-file-content"


def test_resolve_uses_password_file_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD", raising=False)
    pwd_file = tmp_path / "elsewhere.txt"
    pwd_file.write_text("from-env-file-path\n")
    monkeypatch.setenv("AMELI_APP_EMAIL_PASSWORD_FILE", str(pwd_file))

    result = _resolve_email_password({})

    assert result == "from-env-file-path"


def test_resolve_falls_back_to_legacy_password_env(monkeypatch):
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("CUSTOM_SMTP_PASSWORD", "legacy-value")

    result = _resolve_email_password({"password_env": "CUSTOM_SMTP_PASSWORD"})

    assert result == "legacy-value"


def test_resolve_returns_empty_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("AMELI_APP_EMAIL_PASSWORD", raising=False)

    assert _resolve_email_password({}) == ""


def test_read_secret_file_strips_trailing_whitespace(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("  abc123  \n\n")

    assert _read_secret_file(secret) == "abc123"


def test_read_secret_file_missing_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        _read_secret_file(tmp_path / "does-not-exist.txt")
