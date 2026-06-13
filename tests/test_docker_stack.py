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
