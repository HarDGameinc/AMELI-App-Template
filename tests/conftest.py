from __future__ import annotations

import os
from pathlib import Path

import pytest

from ameli_app.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml.example"

os.environ.setdefault("APP_CONFIG", str(CONFIG_PATH))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
os.environ.setdefault("AMELI_APP_DJANGO_SECRET_KEY", "test-secret-key")


@pytest.fixture()
def config_path() -> Path:
    return CONFIG_PATH


@pytest.fixture()
def app_settings(config_path: Path):
    return load_settings(config_path=config_path)


def pytest_addoption(parser):
    """Global pytest CLI option declared at the root conftest as
    pytest requires (subdirectory conftests cannot register
    ``pytest_addoption``). The flag is consumed by
    ``tests/e2e/conftest.py:pytest_collection_modifyitems`` to opt
    into the Playwright e2e suite."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run the Playwright e2e tests in tests/e2e/",
    )

