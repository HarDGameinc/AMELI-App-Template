"""Regression coverage for the ``postgresql+psycopg://`` URL
normalisation in ``scripts/backup.sh``.

Closes the wire-test finding from 2026-06-19 PT-4: the
``DATABASE_URL`` stored in ``app.env`` uses the SQLAlchemy
dialect form ``postgresql+psycopg://user:pwd@host:port/db`` so
that Django + Alembic both pick the right driver. libpq does
NOT understand the ``+psycopg`` suffix — when passed to
``pg_dump`` verbatim, libpq silently discards the URI and falls
back to a default socket + peer-auth connection, which on a root
deploy lands on ``FATAL: no existe el rol root`` and the dump
never happens.

backup.sh now strips the ``+<driver>`` suffix before invoking
``pg_dump``. This test pins the sed expression by feeding it
representative URLs and checking the output. Static-only (no pg
required).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKUP_SH = ROOT / "scripts" / "backup.sh"

# Every test in this file shells out to ``sed -E ...`` to reproduce the
# regex used inside backup.sh. Windows has neither ``sed`` on PATH by
# default nor a POSIX-shell interpreter that understands the escape
# sequences in the regex — the test would fail before it can assert
# anything about backup.sh. Skip the whole module on Windows; CI (Linux)
# runs it unchanged.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sed") is None,
    reason="sed / POSIX shell required; unavailable on Windows",
)


def _strip_driver(url: str) -> str:
    """Reproduce the sed expression embedded in backup.sh so we
    can pin its behaviour from Python.
    """
    proc = subprocess.run(
        ["sed", "-E", r"s@^postgresql\+[A-Za-z0-9_]+://@postgresql://@"],
        input=url, check=True, capture_output=True, text=True,
    )
    return proc.stdout


# ---------------------------------------------------------------------------
# sed behaviour
# ---------------------------------------------------------------------------

def test_strips_psycopg_suffix():
    assert _strip_driver("postgresql+psycopg://u:p@h:5432/db") == \
        "postgresql://u:p@h:5432/db"


def test_strips_psycopg2_suffix():
    assert _strip_driver("postgresql+psycopg2://u:p@h:5432/db") == \
        "postgresql://u:p@h:5432/db"


def test_strips_asyncpg_suffix():
    assert _strip_driver("postgresql+asyncpg://u:p@h:5432/db") == \
        "postgresql://u:p@h:5432/db"


def test_leaves_plain_postgresql_url_unchanged():
    url = "postgresql://u:p@h:5432/db"
    assert _strip_driver(url) == url


def test_leaves_postgres_prefix_unchanged():
    """The check in backup.sh accepts both ``postgresql`` and
    ``postgres`` prefixes. The sed only normalises the
    ``postgresql+X`` form; a bare ``postgres://`` should pass
    through untouched.
    """
    url = "postgres://u:p@h:5432/db"
    assert _strip_driver(url) == url


def test_does_not_touch_url_with_driver_in_path():
    """A driver-like substring further into the URL must NOT be
    stripped — only the leading scheme.
    """
    url = "postgresql://u:p@h:5432/postgresql+psycopg_db"
    assert _strip_driver(url) == url


# ---------------------------------------------------------------------------
# Contract pin — the actual line still exists in backup.sh
# ---------------------------------------------------------------------------

def test_backup_sh_carries_url_normaliser():
    body = BACKUP_SH.read_text()
    # The sed expression escapes the ``+`` (``\+``); search for that
    # exact byte sequence so a refactor that drops the normaliser
    # fails the test loudly.
    assert "postgresql\\+" in body, \
        "backup.sh missing the driver-suffix sed (postgresql\\+...)"
    assert re.search(r"sed\s+-E\s+'s@\^postgresql\\\+", body), \
        "backup.sh sed expression has drifted; update the test or the script"
