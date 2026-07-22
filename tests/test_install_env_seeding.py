"""Regression coverage for what ``install.sh`` seeds on a fresh install.

Closes the 2026-07-22 server test findings (handoff §3.1). A from-scratch
**prod** install could not boot at all, and every blocker was invisible to
CI because this path had never been executed end-to-end:

* ``initialize_runtime_env`` seeded the three crypto keys but not
  ``AMELI_APP_DJANGO_ALLOWED_HOSTS`` nor ``AMELI_APP_TRUSTED_PROXIES``,
  both of which are fail-closed in ``settings/base.py`` outside dev. The
  wizard meant to set them (``ameli-app configure``) boots Django, so it
  could not run either -- a circular dependency.
* ``config/app.yaml.example`` was copied verbatim, keeping
  ``environment: "dev"`` (which silently disables the prod guards) and
  relative paths that resolve inside the checkout, which
  ``settings/i18n_static.py`` refuses.
* ``.env.example`` -- the *dev* env file -- was likewise copied verbatim,
  seeding ``DEBUG=true`` (loud) plus a pinned session cookie name and
  ``SESSION_COOKIE_SECURE=false`` (both silent security downgrades).

These tests source ``_common.sh`` with every directory redirected into a
tmpdir and assert on the files it produces.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="sources _common.sh via a bash subprocess; POSIX-only",
)

ROOT = Path(__file__).resolve().parent.parent
COMMON_SH = ROOT / "scripts" / "_common.sh"


def _seed(
    tmp_path: Path,
    *,
    env: str = "prod",
    slug: str = "tmpl-test",
    api_port: str | None = None,
    web_port: str | None = None,
) -> dict[str, Path | str]:
    """Run ``initialize_runtime_env`` against a sandboxed instance layout.

    Returns the paths of the produced ``app.env`` / ``app.yaml``.
    """
    instance = f"{slug}-{env}"
    app_dir = tmp_path / "opt" / instance
    etc_dir = tmp_path / "etc" / instance
    (app_dir / "config").mkdir(parents=True, exist_ok=True)
    etc_dir.mkdir(parents=True, exist_ok=True)

    # install.sh copies the project tree into APP_DIR before seeding; we
    # only need the two example files the seeding step reads.
    (app_dir / ".env.example").write_bytes((ROOT / ".env.example").read_bytes())
    (app_dir / "config" / "app.yaml.example").write_bytes(
        (ROOT / "config" / "app.yaml.example").read_bytes()
    )

    shell_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "COMMON_SH_PATH": str(COMMON_SH),
        "APP_ENV": env,
        "APP_SLUG": slug,
        "APP_DIR": str(app_dir),
        "ETC_DIR": str(etc_dir),
        "DATA_DIR": str(tmp_path / "var" / "lib" / instance),
        "LOG_DIR": str(tmp_path / "var" / "log" / instance),
        "BACKUP_DIR": str(tmp_path / "var" / "backups" / instance),
        # chown/chmod to a real system group would need root; _common.sh
        # tolerates their failure (`|| true`), which is what runs here.
        "RUN_GROUP": "nonexistent-test-group",
        "RUN_USER": "nonexistent-test-user",
    }
    if api_port is not None:
        shell_env["AMELI_APP_API_PORT"] = api_port
    if web_port is not None:
        shell_env["AMELI_APP_WEB_PORT"] = web_port

    script = r'''
set -euo pipefail
source <(tail -n +6 "${COMMON_SH_PATH}")
initialize_runtime_env
'''
    proc = subprocess.run(
        ["bash", "-c", script],
        env=shell_env, check=True, capture_output=True, text=True,
    )
    return {
        "env": etc_dir / "app.env",
        "yaml": etc_dir / "app.yaml",
        "app_dir": app_dir,
        "stdout": proc.stdout,
    }


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


# ---------------------------------------------------------------------------
# B1 / B2 -- the fail-closed guards with no safe default outside dev
# ---------------------------------------------------------------------------

def test_seeds_allowed_hosts_on_fresh_prod_install(tmp_path):
    values = _env_values(_seed(tmp_path)["env"])
    hosts = values["AMELI_APP_DJANGO_ALLOWED_HOSTS"]

    assert hosts, "empty ALLOWED_HOSTS makes settings/base.py refuse to boot"
    # The post-install smoke check hits 127.0.0.1:<api_port>/health.
    assert "127.0.0.1" in hosts.split(",")
    # ALLOWED_HOSTS is matched against the Host header, where a literal
    # IPv6 address arrives bracketed -- a bare "::1" would never match.
    assert "::1" not in hosts.split(",")


def test_seeded_allowed_hosts_never_uses_a_wildcard(tmp_path):
    """base.py rejects ``*`` outside dev (Host header injection), so a
    seeded wildcard would trade one boot failure for another."""
    values = _env_values(_seed(tmp_path)["env"])
    assert "*" not in values["AMELI_APP_DJANGO_ALLOWED_HOSTS"].split(",")


def test_seeds_trusted_proxies_on_fresh_prod_install(tmp_path):
    values = _env_values(_seed(tmp_path)["env"])
    assert values["AMELI_APP_TRUSTED_PROXIES"] == "127.0.0.1,::1"


def test_seeding_is_idempotent_and_preserves_operator_values(tmp_path):
    """An upgrade must never clobber what the operator narrowed down."""
    paths = _seed(tmp_path)
    env_file = paths["env"]

    text = env_file.read_text().replace(
        _env_values(env_file)["AMELI_APP_DJANGO_ALLOWED_HOSTS"],
        "app.example.com",
    )
    env_file.write_text(text)
    secret_before = _env_values(env_file)["AMELI_APP_DJANGO_SECRET_KEY"]

    _seed(tmp_path)  # second run, same layout

    values = _env_values(env_file)
    assert values["AMELI_APP_DJANGO_ALLOWED_HOSTS"] == "app.example.com"
    assert values["AMELI_APP_DJANGO_SECRET_KEY"] == secret_before


# ---------------------------------------------------------------------------
# B3 -- app.yaml must be rendered for the instance, not copied verbatim
# ---------------------------------------------------------------------------

def test_rendered_config_uses_the_install_environment(tmp_path):
    """``environment: "dev"`` in a prod install silently disables every
    fail-closed guard in settings/base.py."""
    yaml_text = _seed(tmp_path, env="prod")["yaml"].read_text()
    assert 'environment: "prod"' in yaml_text
    assert 'environment: "dev"' not in yaml_text


def test_rendered_config_uses_the_install_slug(tmp_path):
    yaml_text = _seed(tmp_path, slug="tmpl-test")["yaml"].read_text()
    assert 'slug: "tmpl-test"' in yaml_text


def test_rendered_config_paths_are_absolute_and_outside_the_checkout(tmp_path):
    """settings/i18n_static.py refuses MEDIA_ROOT or data_dir inside the
    checkout -- a redeploy (rsync --delete) would wipe user uploads.

    MEDIA_ROOT derives from ``auth.profile_uploads_dir``, *not* from
    ``paths.data_dir`` (see ameli_app/config.py), so that key is the one
    that actually matters here.
    """
    paths = _seed(tmp_path)
    yaml_text = paths["yaml"].read_text()
    app_dir = str(paths["app_dir"])

    rendered = {
        line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip().strip('"')
        for line in yaml_text.splitlines()
        if line.startswith("  ")
        and ":" in line
        and line.split(":", 1)[0].strip()
        in {"profile_uploads_dir", "data_dir", "log_dir", "backup_dir"}
    }
    assert set(rendered) == {"profile_uploads_dir", "data_dir", "log_dir", "backup_dir"}

    for key, value in rendered.items():
        assert value.startswith("/"), f"{key} stayed relative: {value!r}"
        assert not value.startswith(app_dir), f"{key} resolves inside the checkout"


def test_operator_edited_config_is_never_re_rendered(tmp_path):
    """render_config_file runs only on a file we just created."""
    paths = _seed(tmp_path)
    paths["yaml"].write_text('app:\n  environment: "custom-by-operator"\n')

    _seed(tmp_path)

    assert paths["yaml"].read_text() == 'app:\n  environment: "custom-by-operator"\n'


# ---------------------------------------------------------------------------
# B6/B7/B8 -- .env.example is the DEV env file; prod must not inherit it
# ---------------------------------------------------------------------------

def test_prod_env_never_inherits_debug_true(tmp_path):
    """B6: base.py refuses to boot with DEBUG outside dev. Loud, but it
    made a from-scratch prod install impossible."""
    values = _env_values(_seed(tmp_path, env="prod")["env"])
    assert values["AMELI_APP_DJANGO_DEBUG"] == "false"


def test_prod_env_does_not_pin_the_session_cookie_name(tmp_path):
    """B7 (silent): cookies.py treats *any* explicit name as a deliberate
    operator override and skips the ASVS V3.4.4 ``__Host-`` prefix. An
    installer-seeded value is nobody's deliberate choice."""
    values = _env_values(_seed(tmp_path, env="prod")["env"])
    assert "AMELI_APP_SESSION_COOKIE_NAME" not in values


def test_prod_env_forces_secure_session_cookie(tmp_path):
    """B8 (silent): without Secure the session cookie leaks over any
    plaintext hop, and ``__Host-`` cannot apply."""
    values = _env_values(_seed(tmp_path, env="prod")["env"])
    assert values["AMELI_APP_SESSION_COOKIE_SECURE"] == "true"


def test_dev_env_keeps_the_developer_friendly_values(tmp_path):
    """The rewrite is prod-only -- a dev install still gets DEBUG."""
    values = _env_values(_seed(tmp_path, env="dev")["env"])
    assert values["AMELI_APP_DJANGO_DEBUG"] == "true"
    assert values["AMELI_APP_SESSION_COOKIE_SECURE"] == "false"


def test_warns_when_an_existing_prod_env_carries_the_dev_values(tmp_path):
    """Instances provisioned by an older installer already carry the
    downgrade. Re-running install must not rewrite their env file, but it
    must not let the problem pass unnoticed either.
    """
    paths = _seed(tmp_path, env="prod")
    env_file = paths["env"]
    env_file.write_text(
        "AMELI_APP_DJANGO_DEBUG=true\n"
        "AMELI_APP_SESSION_COOKIE_SECURE=false\n"
        "AMELI_APP_SESSION_COOKIE_NAME=ameli_app_session\n",
        encoding="utf-8",
    )

    stdout = _seed(tmp_path, env="prod")["stdout"]

    assert "AMELI_APP_DJANGO_DEBUG activo" in stdout
    assert "SESSION_COOKIE_SECURE=false" in stdout
    assert "__Host-" in stdout
    # ...and the operator's file is left exactly as it was.
    assert "AMELI_APP_SESSION_COOKIE_NAME=ameli_app_session" in env_file.read_text()


# ---------------------------------------------------------------------------
# B9 -- the console email backend is dev-only
# ---------------------------------------------------------------------------

def test_prod_config_seeds_a_deliverable_email_backend(tmp_path):
    """settings/email.py refuses to boot outside dev on "console": mail
    stays in memory, so password reset and MFA-by-email fail silently.
    "file" writes .eml to <data_dir>/outbox -- nothing is lost and the
    deploy boots; the operator moves to smtp when it has credentials.
    """
    yaml_text = _seed(tmp_path, env="prod")["yaml"].read_text()
    assert '  backend: "file"' in yaml_text
    assert '  backend: "console"' not in yaml_text


def test_dev_config_keeps_the_console_email_backend(tmp_path):
    yaml_text = _seed(tmp_path, env="dev")["yaml"].read_text()
    assert '  backend: "console"' in yaml_text


# ---------------------------------------------------------------------------
# B10 -- explicit operator input must not be shadowed by .env.example
# ---------------------------------------------------------------------------

def test_explicit_ports_reach_the_env_file(tmp_path):
    """``AMELI_APP_API_PORT=18190 bash scripts/install.sh`` used to be
    discarded: .env.example already carried AMELI_APP_API_PORT=18080, and
    ``default_env`` only writes a key that is missing. The units were
    rendered from 18190 while the app read 18080 -- on a host running
    several instances that means listening on someone else's port.
    """
    values = _env_values(
        _seed(tmp_path, env="prod", api_port="18190", web_port="18191")["env"]
    )
    assert values["AMELI_APP_API_PORT"] == "18190"
    assert values["AMELI_APP_WEB_PORT"] == "18191"


def test_prod_defaults_are_not_the_dev_ports(tmp_path):
    """Without an explicit port, a prod install must land on the prod
    defaults (8080/8081), not on the dev ones .env.example ships."""
    values = _env_values(_seed(tmp_path, env="prod")["env"])
    assert values["AMELI_APP_API_PORT"] == "8080"
    assert values["AMELI_APP_WEB_PORT"] == "8081"


def test_warns_when_an_existing_env_file_disagrees_with_the_units(tmp_path):
    """Instances provisioned before render_env_file carry the drift; the
    install must say so instead of silently listening elsewhere."""
    paths = _seed(tmp_path, env="prod", api_port="18190")
    env_file = paths["env"]
    env_file.write_text(
        env_file.read_text().replace(
            "AMELI_APP_API_PORT=18190", "AMELI_APP_API_PORT=19999"
        ),
        encoding="utf-8",
    )

    stdout = _seed(tmp_path, env="prod", api_port="18190")["stdout"]

    assert "AMELI_APP_API_PORT=19999" in stdout
    assert "19999" in stdout


# ---------------------------------------------------------------------------
# B12 -- install.sh must not dirty its own checkout
# ---------------------------------------------------------------------------

def test_repo_file_modes_match_what_repair_permissions_applies():
    """The documented install clones straight into /opt/<instance>, so
    APP_DIR *is* the git checkout and ``repair_permissions`` chmods it.
    Any file whose recorded mode differs from the applied one shows up as
    modified forever, and `git pull` then aborts with "local changes
    would be overwritten" -- breaking the documented update path.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s", "scripts/", "deploy/git-hooks/"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout

    wrong = [
        line for line in out.splitlines()
        if line and not line.startswith("100755")
    ]
    assert not wrong, (
        "repair_permissions sets these executable; git must record 100755 "
        f"or the checkout is dirty after every install: {wrong}"
    )
