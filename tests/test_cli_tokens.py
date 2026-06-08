from __future__ import annotations

import json

import pytest

from ameli_app.cli import main


@pytest.fixture()
def cfg_path():
    return "config/app.yaml.example"


@pytest.fixture()
def seeded_user(db, cfg_path, capsys):
    """Bootstrap an admin so tokens have an owner to attach to."""
    main([
        "--config", cfg_path,
        "bootstrap-admin", "--username", "admin", "--password", "AdminPass!12?",
    ])
    capsys.readouterr()  # drain the bootstrap JSON so tests see only their own output
    return "admin"


def _run_and_capture(capsys, args):
    rc = main(args)
    out = capsys.readouterr()
    return rc, out


@pytest.mark.django_db
def test_create_token_prints_plaintext_once(capsys, seeded_user, cfg_path):
    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "create-token", "--user", seeded_user, "--name", "deploy",
    ])

    assert rc == 0
    payload = json.loads(out.out)
    assert payload["ok"] is True
    assert payload["token"].startswith("ameli_")
    assert payload["record"]["name"] == "deploy"


@pytest.mark.django_db
def test_create_token_unknown_user_fails(capsys, seeded_user, cfg_path):
    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "create-token", "--user", "ghost", "--name", "x",
    ])

    assert rc == 2
    assert "user not found" in out.err


@pytest.mark.django_db
def test_create_token_with_expiry_persists(capsys, seeded_user, cfg_path):
    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "create-token", "--user", seeded_user, "--name", "ephemeral",
        "--expires-in-days", "7",
    ])

    assert rc == 0
    payload = json.loads(out.out)
    assert payload["record"]["expires_at"] is not None


@pytest.mark.django_db
def test_create_token_rejects_negative_expiry(capsys, seeded_user, cfg_path):
    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "create-token", "--user", seeded_user, "--name", "x",
        "--expires-in-days", "-1",
    ])

    assert rc == 2
    assert "positive integer" in out.err


@pytest.mark.django_db
def test_list_tokens_after_create(capsys, seeded_user, cfg_path):
    main([
        "--config", cfg_path,
        "create-token", "--user", seeded_user, "--name", "first",
    ])
    capsys.readouterr()

    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "list-tokens", "--user", seeded_user,
    ])

    assert rc == 0
    payload = json.loads(out.out)
    assert payload["ok"] is True
    assert len(payload["tokens"]) == 1
    assert payload["tokens"][0]["name"] == "first"
    # never expose plaintext
    assert "token" not in payload["tokens"][0]


@pytest.mark.django_db
def test_revoke_token_marks_it_revoked(capsys, seeded_user, cfg_path):
    create_rc = main([
        "--config", cfg_path,
        "create-token", "--user", seeded_user, "--name", "x",
    ])
    out = capsys.readouterr()
    payload = json.loads(out.out)
    token_id = payload["record"]["id"]

    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "revoke-token", "--user", seeded_user, "--id", str(token_id),
    ])

    assert rc == 0
    payload = json.loads(out.out)
    assert payload["status"] in {"revoked", "already-revoked"}


@pytest.mark.django_db
def test_revoke_token_unknown_id_fails(capsys, seeded_user, cfg_path):
    rc, out = _run_and_capture(capsys, [
        "--config", cfg_path,
        "revoke-token", "--user", seeded_user, "--id", "99999",
    ])

    assert rc == 2
    assert "token not found" in out.err
