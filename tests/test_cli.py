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
