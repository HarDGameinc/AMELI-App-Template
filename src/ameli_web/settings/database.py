"""Database configuration — SQLite fallback + Postgres via DATABASE_URL, with optional psycopg pool.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .base import _int_env


def _cfg():
    """Read CFG from the package namespace so tests that
    ``monkeypatch.setattr(settings, "CFG", ...)`` see the swap.

    A top-of-module ``from .base import CFG`` would bind this module to
    the original object and no monkeypatch on ``settings.CFG`` (the
    package attribute) would take effect. Late-binding through the
    package's ``__init__`` keeps the historical test API working after
    the PC-4 split.
    """
    from ameli_web import settings as _pkg
    return _pkg.CFG


def _default_sqlite_path() -> str:
    # SQLite is intentionally kept only as a local fallback when DATABASE_URL
    # is not configured. Real installs are expected to use PostgreSQL.
    explicit = os.environ.get("AMELI_APP_SQLITE_PATH", "").strip()
    if explicit:
        return explicit
    cfg = _cfg()
    if cfg.data_dir:
        return str(cfg.data_dir / "django-dev.sqlite3")
    return str(Path(tempfile.gettempdir()) / "ameli-app-template-django-dev.sqlite3")


def _db_pool_options() -> dict[str, int | bool] | None:
    """Build the ``OPTIONS["pool"]`` dict for psycopg3's connection
    pool when the operator opted in via env vars.

    Django 5.1+ (we run 5.2) integrates ``psycopg_pool.ConnectionPool``
    when ``OPTIONS["pool"]`` is set on a postgres backend AND the
    ``psycopg_pool`` package is installed. Without the package the
    backend errors loud at first query — the boot guard below
    short-circuits to ``None`` and we never wire the pool, so a
    missing optional dep degrades to per-request connections (the
    Django default) instead of crashing on a query.
    """
    raw_min = os.environ.get("AMELI_APP_DB_POOL_MIN_SIZE", "").strip()
    raw_max = os.environ.get("AMELI_APP_DB_POOL_MAX_SIZE", "").strip()
    if not raw_min and not raw_max:
        return None
    try:
        from psycopg_pool import ConnectionPool  # noqa: F401
    except ImportError:
        return None
    opts: dict[str, int | bool] = {}
    if raw_min:
        try:
            opts["min_size"] = int(raw_min)
        except ValueError:
            pass
    if raw_max:
        try:
            opts["max_size"] = int(raw_max)
        except ValueError:
            pass
    return opts or None


def _database_settings() -> dict[str, Any]:
    cfg = _cfg()
    dsn = (cfg.database_url or "").strip()
    if not dsn:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _default_sqlite_path(),
        }

    parsed = urlparse(dsn)
    base_scheme = parsed.scheme.split("+", 1)[0]
    if base_scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(f"Unsupported DATABASE_URL scheme for Django: {parsed.scheme}")
    # ``CONN_MAX_AGE`` keeps connections open across requests
    # (default Django behaviour is to open/close per request, which
    # at moderate concurrency makes Postgres connection churn the
    # dominant cost). Default 60 s here is a conservative middle
    # ground — long enough to amortise across a typical user
    # session, short enough that idle workers do not hold sockets
    # forever. ``CONN_HEALTH_CHECKS`` runs a cheap probe before
    # re-using a stale connection (Django 4.1+) so a connection
    # killed by Postgres ``idle_in_transaction_session_timeout`` or
    # by a restart of pgbouncer surfaces as a controlled error
    # rather than a 500.
    settings: dict[str, Any] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": _int_env("AMELI_APP_DB_CONN_MAX_AGE_SECONDS", default=60),
        "CONN_HEALTH_CHECKS": True,
    }
    pool_opts = _db_pool_options()
    if pool_opts is not None:
        settings["OPTIONS"] = {"pool": pool_opts}
    return settings


DATABASES = {"default": _database_settings()}
