from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

import pytest

from ameli_app import cli

# ---------------------------------------------------------------------------
# Pure helpers: env file read/write round-trip
# ---------------------------------------------------------------------------


def test_read_env_file_ignores_comments_and_blanks(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text(
        "# a comment\n"
        "\n"
        "FOO=one\n"
        "  # indented comment\n"
        "BAR=two three four\n"
        "invalid line without equals\n"
        "BAZ=  spaces around  \n",
        encoding="utf-8",
    )
    assert cli._read_env_file(env) == {
        "FOO": "one",
        "BAR": "two three four",
        "BAZ": "spaces around",
    }


def test_write_env_updates_in_place_preserves_comments(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text(
        "# header comment\n"
        "APP_ENV=prod\n"
        "\n"
        "# section: hosts\n"
        "AMELI_APP_DJANGO_ALLOWED_HOSTS=old.example.com\n"
        "AMELI_APP_TRUSTED_PROXIES=127.0.0.1\n",
        encoding="utf-8",
    )
    cli._write_env_updates(
        env,
        {
            "AMELI_APP_DJANGO_ALLOWED_HOSTS": "new.example.com",
            "AMELI_APP_EMAIL_HOST": "smtp.example.com",
        },
    )
    content = env.read_text(encoding="utf-8")
    # comments preserved
    assert "# header comment" in content
    assert "# section: hosts" in content
    # in-place update
    assert "AMELI_APP_DJANGO_ALLOWED_HOSTS=new.example.com" in content
    assert "AMELI_APP_DJANGO_ALLOWED_HOSTS=old.example.com" not in content
    # new key appended
    assert "AMELI_APP_EMAIL_HOST=smtp.example.com" in content
    # untouched line preserved
    assert "AMELI_APP_TRUSTED_PROXIES=127.0.0.1" in content


def test_write_env_updates_is_idempotent(tmp_path: Path):
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    updates = {"AMELI_APP_DJANGO_ALLOWED_HOSTS": "app.example.com"}
    cli._write_env_updates(env, updates)
    first = env.read_text(encoding="utf-8")
    cli._write_env_updates(env, updates)
    second = env.read_text(encoding="utf-8")
    assert first == second


def test_autodetect_allowed_hosts_always_includes_loopback():
    value = cli._autodetect_allowed_hosts()
    parts = value.split(",")
    assert "localhost" in parts
    assert "127.0.0.1" in parts
    # dedup: parts unique
    assert len(parts) == len(set(parts))


# ---------------------------------------------------------------------------
# `_handle_configure`: --check reports; --yes gates on missing env vars
# ---------------------------------------------------------------------------


def _args(env_file: str, *, section: str = "all", yes: bool = True, check: bool = True):
    return argparse.Namespace(
        command="configure",
        config=None,
        env_file=env_file,
        section=section,
        yes=yes,
        check=check,
    )


def test_configure_check_reports_writes_without_touching_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ALLOWED_HOSTS", "app.example.com")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_TRUSTED_PROXIES", "10.0.0.1")
    # admin not required in --check when no user set; the section still
    # runs but produces no bootstrap. Provide them so the gate passes.
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_USER", "admin")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_PASSWORD", "SecurePass!12?")

    before = env.read_text(encoding="utf-8")
    exit_code = cli._handle_configure(_args(str(env)))
    after = env.read_text(encoding="utf-8")

    assert exit_code == 0
    assert before == after  # --check must not touch the file
    body = json.loads(capsys.readouterr().out)
    assert body["env_file"] == str(env)
    assert body["would_set"]["AMELI_APP_DJANGO_ALLOWED_HOSTS"] == "app.example.com"
    assert body["would_set"]["AMELI_APP_TRUSTED_PROXIES"] == "10.0.0.1"
    assert body["bootstrap_admin"] is True


def test_configure_non_interactive_missing_vars_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    for k in ("ALLOWED_HOSTS", "TRUSTED_PROXIES", "ADMIN_USER", "ADMIN_PASSWORD"):
        monkeypatch.delenv(f"AMELI_APP_CONFIGURE_{k}", raising=False)

    exit_code = cli._handle_configure(_args(str(env)))

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "AMELI_APP_CONFIGURE_ALLOWED_HOSTS" in err
    assert "AMELI_APP_CONFIGURE_TRUSTED_PROXIES" in err


def test_configure_smtp_optional_stays_out_when_host_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """SMTP is optional: an empty EMAIL_HOST keeps the console backend
    and does NOT emit any AMELI_APP_EMAIL_* into the env file."""
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ALLOWED_HOSTS", "app.example.com")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_USER", "admin")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_PASSWORD", "SecurePass!12?")
    monkeypatch.delenv("AMELI_APP_CONFIGURE_EMAIL_HOST", raising=False)

    exit_code = cli._handle_configure(_args(str(env)))

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    # No SMTP keys in would_set — the section short-circuits on empty host.
    assert "AMELI_APP_EMAIL_HOST" not in body["would_set"]
    assert "AMELI_APP_EMAIL_BACKEND" not in body["would_set"]


def test_configure_section_hosts_only_writes_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ALLOWED_HOSTS", "app.example.com")
    args = _args(str(env), section="hosts", check=False)
    exit_code = cli._handle_configure(args)
    assert exit_code == 0
    content = env.read_text(encoding="utf-8")
    assert "AMELI_APP_DJANGO_ALLOWED_HOSTS=app.example.com" in content
    # Not the other sections
    assert "AMELI_APP_TRUSTED_PROXIES" not in content
    # bootstrap_admin not touched
    body = json.loads(capsys.readouterr().out)
    assert body["bootstrap_admin"] is None


def test_configure_missing_env_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    args = argparse.Namespace(
        command="configure",
        config=None,
        env_file=None,  # no --env-file, no autodetect on this test machine
        section="all",
        yes=True,
        check=True,
    )
    # Force autodetect miss by pointing at a directory that will not resolve
    # to /opt/<slug>-<env>/app.env; the test just needs a clean "no file"
    # path — since we did not create anything, autodetect returns None.
    exit_code = cli._handle_configure(args)
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "cannot locate the runtime env file" in err


# ---------------------------------------------------------------------------
# Superadmin bootstrap failure (2026-07-22 server test, handoff §3.1 B4)
# ---------------------------------------------------------------------------


def test_configure_reports_env_written_when_django_cannot_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Creating the superadmin needs a bootable Django, which needs the
    very config this wizard writes. When the deploy is not there yet, a
    raw traceback reads as "configure failed" and hides the fact that the
    env file *was* written. Fail legibly instead.
    """
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ALLOWED_HOSTS", "app.example.com")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_USER", "admin")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_PASSWORD", "SecurePass!12?")

    def _boom(_args):
        raise RuntimeError("AMELI_APP_TRUSTED_PROXIES is empty outside dev")

    monkeypatch.setattr(cli, "_bootstrap_django", _boom)

    exit_code = cli._handle_configure(_args(str(env), check=False))

    assert exit_code == 1  # non-zero, but not a crash
    body = json.loads(capsys.readouterr().out)
    # The env writes survived and are reported.
    assert "AMELI_APP_DJANGO_ALLOWED_HOSTS" in body["written"]
    assert "AMELI_APP_TRUSTED_PROXIES" in body["written"]
    content = env.read_text(encoding="utf-8")
    assert "AMELI_APP_DJANGO_ALLOWED_HOSTS=app.example.com" in content
    # The failure is named, and the operator is told how to finish.
    assert "RuntimeError" in body["bootstrap_admin_error"]
    assert body["bootstrap_admin"] is None
    assert "bootstrap-admin" in body["hint"]


def test_configure_bootstrap_success_reports_no_error_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """The happy path must stay clean: exit 0, no error/hint noise."""
    env = tmp_path / "app.env"
    env.write_text("APP_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ALLOWED_HOSTS", "app.example.com")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_USER", "admin")
    monkeypatch.setenv("AMELI_APP_CONFIGURE_ADMIN_PASSWORD", "SecurePass!12?")

    monkeypatch.setattr(cli, "_bootstrap_django", lambda _args: None)
    fake = types.ModuleType("ameli_web.accounts.services")
    fake.bootstrap_superadmin = lambda u, p, must_change_password: {  # noqa: ARG005
        "username": u,
        "created": True,
    }
    monkeypatch.setitem(sys.modules, "ameli_web.accounts.services", fake)

    exit_code = cli._handle_configure(_args(str(env), check=False))

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["bootstrap_admin"] == {"username": "admin", "created": True}
    assert "bootstrap_admin_error" not in body
    assert "hint" not in body
