from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from ameli_app.cli import main

User = get_user_model()


def test_cli_version(config_path, capsys):
    result = main(["--config", str(config_path), "version"])

    assert result == 0
    assert "AMELI App Template" in capsys.readouterr().out


def test_cli_config_check(config_path, capsys):
    result = main(["--config", str(config_path), "config-check"])

    assert result == 0
    assert '"ok": true' in capsys.readouterr().out


def test_cli_worker_once(config_path, capsys):
    result = main(["--config", str(config_path), "worker-once"])

    assert result == 0
    assert '"worker": "capture"' in capsys.readouterr().out


def test_cli_notify_once(config_path, capsys):
    result = main(["--config", str(config_path), "notify-once"])

    assert result == 0
    assert '"worker": "notify"' in capsys.readouterr().out


@pytest.mark.django_db
def test_cli_bootstrap_admin_and_list_users(config_path, capsys):
    result = main(
        [
            "--config",
            str(config_path),
            "bootstrap-admin",
            "--username",
            "admin",
            "--password",
            "ChangeThisNow!1?",
            "--must-change-password",
        ]
    )

    assert result == 0
    bootstrap_payload = json.loads(capsys.readouterr().out)
    assert bootstrap_payload["ok"] is True
    assert bootstrap_payload["status"] == "created"

    result = main(["--config", str(config_path), "list-users"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["users"][0]["username"] == "admin"
    assert User.objects.filter(username="admin", role="superadmin").exists()


@pytest.mark.django_db
def test_cli_create_user(config_path, capsys):
    main(
        [
            "--config",
            str(config_path),
            "bootstrap-admin",
            "--username",
            "admin",
            "--password",
            "ChangeThisNow!1?",
        ]
    )
    capsys.readouterr()

    result = main(
        [
            "--config",
            str(config_path),
            "create-user",
            "--username",
            "viewer",
            "--password",
            "ViewerPass!1?",
            "--role",
            "public",
            "--actor",
            "admin",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["username"] == "viewer"
    assert User.objects.filter(username="viewer", role="public").exists()


@pytest.mark.django_db
def test_cli_verify_audit_strict_precondition_exits_three_on_break(
    config_path, capsys, settings, monkeypatch
):
    """#8 — `verify-audit --strict-precondition` returns exit 3 (distinct
    from generic exit 1) when the chain is broken, so an automation
    pipeline can distinguish "can't rotate yet" from other failures."""
    monkeypatch.setenv("AMELI_APP_AUDIT_HMAC_KEY", "k")
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.services import record_audit
    from ameli_web.audit.models import AuditEvent

    a = record_audit("first")
    record_audit("second")
    AuditEvent.objects.filter(id=a.id).update(payload={"tamper": True})

    result = main(["--config", str(config_path), "verify-audit", "--strict-precondition"])
    assert result == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False

    # Without the flag the legacy exit code (1) is preserved.
    result = main(["--config", str(config_path), "verify-audit"])
    assert result == 1


@pytest.mark.django_db
def test_cli_rotate_audit_key_apply_env_rewrites_file(
    config_path, capsys, tmp_path, settings, monkeypatch
):
    """#8 — `--apply-env` writes the new key into the env file
    atomically as part of a successful rotation."""
    monkeypatch.setenv("AMELI_APP_AUDIT_HMAC_KEY", "old")
    settings.AUDIT_HMAC_KEY = "old"
    from ameli_web.accounts.services import record_audit

    record_audit("event_a")

    env_file = tmp_path / "app.env"
    env_file.write_text(
        "AMELI_APP_LOG_LEVEL=INFO\n"
        "AMELI_APP_AUDIT_HMAC_KEY=old\n",
        encoding="utf-8",
    )

    result = main([
        "--config", str(config_path),
        "rotate-audit-key",
        "--from-key", "old",
        "--to-key", "newvalue",
        "--apply-env", str(env_file),
    ])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["env_file"]["ok"] is True
    assert "AMELI_APP_AUDIT_HMAC_KEY=newvalue\n" in env_file.read_text(encoding="utf-8")
