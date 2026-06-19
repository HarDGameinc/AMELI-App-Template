"""Regression coverage for scripts/_common.sh slug auto-detection.

Closes the wire-test finding from 2026-06-19 PT-4 bloque 4: when
``backup.sh`` was invoked interactively without ``APP_SLUG=`` it
fell back to the literal default ``ameli-app``, computed
``ENV_FILE=/etc/ameli-app-dev/app.env`` and silently skipped the
DB dump because the real env file lives at
``/etc/ameli-app-template-dev/app.env``. _common.sh now derives
the slug from the project directory basename (strip trailing
``-dev`` or ``-prod``) so the same operator that invokes
backup.sh from ``/opt/ameli-app-template-dev/`` gets the
expected ENV_FILE without exporting APP_SLUG=.

The test sources a stub wrapper that re-points PROJECT_DIR to
the simulated path, then sources the body of _common.sh, and
asserts the resolved APP_SLUG / APP_INSTANCE / ENV_FILE.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON_SH = ROOT / "scripts" / "_common.sh"


def _resolve(project_dir: str, *, env: str = "dev", explicit_slug: str | None = None) -> dict[str, str]:
    """Run ``_common.sh`` with PROJECT_DIR pinned and return the
    resolved APP_SLUG / APP_INSTANCE / ETC_DIR / ENV_FILE.
    """
    shell_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),  # noqa: S108 - test sandbox, no secrets
        "PROJECT_DIR_STUB": project_dir,
        "COMMON_SH_PATH": str(COMMON_SH),
        "APP_ENV": env,
    }
    if explicit_slug is not None:
        shell_env["APP_SLUG"] = explicit_slug

    script = r'''
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR_STUB}"
SCRIPT_DIR="${PROJECT_DIR_STUB}/scripts"
# Skip the first 5 lines of _common.sh that re-derive
# PROJECT_DIR / SCRIPT_DIR via BASH_SOURCE — we want to keep
# our stubbed values.
source <(tail -n +6 "${COMMON_SH_PATH}")
echo "APP_SLUG=${APP_SLUG}"
echo "APP_INSTANCE=${APP_INSTANCE}"
echo "ENV_FILE=${ENV_FILE}"
echo "ETC_DIR=${ETC_DIR}"
'''
    proc = subprocess.run(
        ["bash", "-c", script],
        env=shell_env, check=True, capture_output=True, text=True,
    )
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def test_slug_derived_from_dev_suffix_project_dir():
    out = _resolve("/opt/ameli-app-template-dev", env="dev")
    assert out["APP_SLUG"] == "ameli-app-template"
    assert out["APP_INSTANCE"] == "ameli-app-template-dev"
    assert out["ENV_FILE"] == "/etc/ameli-app-template-dev/app.env"


def test_slug_derived_from_prod_suffix_project_dir():
    out = _resolve("/opt/ameli-app-template-prod", env="prod")
    assert out["APP_SLUG"] == "ameli-app-template"
    assert out["APP_INSTANCE"] == "ameli-app-template-prod"
    assert out["ENV_FILE"] == "/etc/ameli-app-template-prod/app.env"


def test_slug_falls_back_when_project_dir_has_no_env_suffix():
    """If the checkout was renamed (e.g. ``/opt/scratch``) and
    does not carry the ``-dev``/``-prod`` suffix, fall back to
    the literal default so behaviour is at least predictable.
    """
    out = _resolve("/opt/scratch", env="dev")
    assert out["APP_SLUG"] == "ameli-app"


def test_explicit_slug_wins_over_autodetection():
    """An exported APP_SLUG must take precedence — the install
    script and CI fixtures rely on this to pin the slug.
    """
    out = _resolve("/opt/ameli-app-template-dev", env="dev", explicit_slug="my-custom-slug")
    assert out["APP_SLUG"] == "my-custom-slug"
    assert out["APP_INSTANCE"] == "my-custom-slug-dev"
    assert out["ENV_FILE"] == "/etc/my-custom-slug-dev/app.env"
