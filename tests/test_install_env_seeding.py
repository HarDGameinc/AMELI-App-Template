"""Regression coverage for what ``install.sh`` seeds on a fresh install.

Closes the 2026-07-22 server test findings (handoff §3.1 B1/B2/B3). A
from-scratch **prod** install could not boot at all, and every blocker was
invisible to CI because this path had never been executed end-to-end:

* ``initialize_runtime_env`` seeded the three crypto keys but not
  ``AMELI_APP_DJANGO_ALLOWED_HOSTS`` nor ``AMELI_APP_TRUSTED_PROXIES``,
  both of which are fail-closed in ``settings/base.py`` outside dev. The
  wizard meant to set them (``ameli-app configure``) boots Django, so it
  could not run either -- a circular dependency.
* ``config/app.yaml.example`` was copied verbatim, keeping
  ``environment: "dev"`` (which silently disables the prod guards) and
  relative paths that resolve inside the checkout, which
  ``settings/i18n_static.py`` refuses.

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


def _seed(tmp_path: Path, *, env: str = "prod", slug: str = "tmpl-test") -> dict[str, Path]:
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

    script = r'''
set -euo pipefail
source <(tail -n +6 "${COMMON_SH_PATH}")
initialize_runtime_env
'''
    subprocess.run(
        ["bash", "-c", script],
        env=shell_env, check=True, capture_output=True, text=True,
    )
    return {"env": etc_dir / "app.env", "yaml": etc_dir / "app.yaml", "app_dir": app_dir}


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
