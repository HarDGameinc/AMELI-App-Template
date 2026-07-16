"""Smoke checks for the Dockerfile + docker-compose.yml.

These don't pull / build images (CI without buildx would choke).
They parse the manifests and guard against drift that would
silently make ``docker compose up`` unusable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
DOCKERIGNORE = ROOT / ".dockerignore"


def test_dockerfile_exists_and_is_multi_stage():
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Multi-stage = at least 2 FROM ... AS lines.
    stages = [line for line in text.splitlines() if line.startswith("FROM ") and " AS " in line]
    assert len(stages) >= 2, "Dockerfile must use multi-stage build"


def test_dockerfile_runs_as_non_root():
    text = DOCKERFILE.read_text(encoding="utf-8")
    # The final ``USER`` directive must NOT be root.
    user_lines = [line for line in text.splitlines() if line.startswith("USER ")]
    assert user_lines, "Dockerfile must drop root via USER directive"
    assert user_lines[-1].strip() != "USER root"


def test_dockerfile_pins_django_settings_module():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "DJANGO_SETTINGS_MODULE=ameli_web.settings" in text


def test_dockerfile_uses_tini_as_entrypoint():
    """Tini reaps zombies and forwards SIGTERM cleanly to uvicorn —
    important so ``docker stop`` actually stops the notifier daemon
    instead of waiting for the sleep loop to finish."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "tini" in text
    assert 'ENTRYPOINT ["/usr/bin/tini"' in text


def test_compose_defines_api_notifier_and_db():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = set(data.get("services", {}).keys())
    assert {"api", "notifier", "db"} <= services


def test_compose_api_depends_on_healthy_db():
    """If the api comes up before postgres is ready, the boot guard
    fails before the api can retry."""
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api = data["services"]["api"]
    depends = api.get("depends_on", {})
    assert depends.get("db", {}).get("condition") == "service_healthy"


def test_compose_notifier_waits_for_api():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    notifier = data["services"]["notifier"]
    depends = notifier.get("depends_on", {})
    assert "api" in depends


def test_compose_uses_console_email_backend_so_no_real_smtp_required():
    """Dev compose must not require a real SMTP — running the stack on
    a developer laptop without an SMTP relay would otherwise break
    every flow that sends mail."""
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api_env = data["services"]["api"]["environment"]
    assert "console" in api_env.get("AMELI_APP_EMAIL_BACKEND", "")


def test_dockerignore_excludes_volatile_paths():
    text = DOCKERIGNORE.read_text(encoding="utf-8")
    for path in (".git", ".venv", "__pycache__", "*.sqlite3"):
        assert path in text, f".dockerignore must exclude {path}"


# ---- regression guards for the 2026-07-15 dry-run fixes (handoff §5) ----


def test_compose_uses_django_prefixed_env_names():
    """The code reads AMELI_APP_DJANGO_{SECRET_KEY,DEBUG,ALLOWED_HOSTS}
    (config.py / base.py). The un-prefixed names are inert and silently
    fall back to the insecure default SECRET_KEY + DEBUG=False."""
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for svc in ("api", "notifier"):
        env = data["services"][svc]["environment"]
        assert "AMELI_APP_DJANGO_SECRET_KEY" in env, svc
        assert "AMELI_APP_SECRET_KEY" not in env, f"{svc}: inert un-prefixed name"
        assert env.get("APP_ENV") == "dev", svc
        assert "AMELI_APP_MFA_ENCRYPTION_KEY" in env, svc


def test_dockerfile_installs_hash_pinned_lock():
    """Parity with the prod deploy (ASVS V14.2.3): the image installs the
    hash-pinned lock, not the loose ``requirements.txt`` ranges (which could
    pull a different Django than the lock pins)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in text
    assert "pip install -r requirements.txt" not in text


def test_dockerfile_sets_pythonpath_to_app_src():
    """The editable install's .pth points at the builder's /build/src, which
    does not exist in the runtime image; PYTHONPATH=/app/src makes
    ``import ameli_web`` resolve instead of ModuleNotFoundError."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'PYTHONPATH="/app/src"' in text


def test_dockerfile_copies_version_file():
    """version.py resolves ``parents[2]/VERSION``; without copying it the
    image reports ``v0.0.0-dev`` at /health."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY VERSION" in text


def test_dockerfile_has_dev_target_for_tests():
    """A ``dev`` target layers the dev-deps (pytest) on top of runtime so
    ``docker compose run --rm api pytest`` works without bloating prod."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "AS dev" in text
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert data["services"]["api"]["build"].get("target") == "dev"


def test_gitattributes_forces_lf_on_shell_scripts():
    """A Windows clone with autocrlf=true otherwise checks out *.sh with
    CRLF, breaking ``source _common.sh`` inside Linux containers."""
    ga = ROOT / ".gitattributes"
    assert ga.exists(), ".gitattributes must exist"
    assert "eol=lf" in ga.read_text(encoding="utf-8")
