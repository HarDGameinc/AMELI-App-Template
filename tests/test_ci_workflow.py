"""Smoke tests for the .github/workflows/ci.yml file.

These don't run the workflow — they just guard against regressions
that would silently break CI (missing steps, drift in the Python
matrix, env vars that no longer match boot guards).
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_file_exists():
    assert WORKFLOW.is_file(), "missing .github/workflows/ci.yml"


def test_workflow_runs_on_main_and_dev():
    data = _load()
    # PyYAML parses the bare ``on:`` key as Python True. Fish out the
    # value either way.
    triggers = data.get("on") or data.get(True)
    assert triggers is not None
    branches = set(triggers.get("push", {}).get("branches") or [])
    assert {"main", "dev"} <= branches


def test_workflow_includes_required_steps():
    data = _load()
    job = data["jobs"]["lint-and-test"]
    step_names = [step.get("name") for step in job["steps"] if step.get("name")]
    required = {"Ruff (lint)", "Django system checks", "Apply migrations", "Pytest"}
    missing = required - set(step_names)
    assert not missing, f"missing CI steps: {missing}"


def test_workflow_runs_python_311_and_312():
    data = _load()
    matrix = data["jobs"]["lint-and-test"]["strategy"]["matrix"]
    assert "3.11" in matrix["python-version"]
    assert "3.12" in matrix["python-version"]


def test_workflow_env_satisfies_settings_boot_guards():
    """settings.py refuses to boot without these env vars set. CI must
    keep them populated or every job dies on import."""
    data = _load()
    env = data["jobs"]["lint-and-test"]["env"]
    for key in (
        "DJANGO_SETTINGS_MODULE",
        "AMELI_APP_SECRET_KEY",
        "AMELI_APP_ALLOWED_HOSTS",
        "AMELI_APP_TRUSTED_PROXIES",
    ):
        assert key in env, f"CI env missing {key}"
    assert env["DJANGO_SETTINGS_MODULE"] == "ameli_web.settings"
    assert len(env["AMELI_APP_SECRET_KEY"]) >= 32


def test_workflow_uses_concurrency_to_cancel_stale_runs():
    """A new commit on the same ref should cancel the previous in-flight
    run — otherwise PR queues stack up."""
    data = _load()
    concurrency = data.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is True


def test_workflow_includes_makemigrations_check():
    """``makemigrations --check`` catches a model change merged without
    its migration."""
    data = _load()
    job = data["jobs"]["lint-and-test"]
    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "makemigrations --check" in runs
