from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine

from .config import Settings

metadata = MetaData()


def create_db_engine(settings: Settings) -> Engine:
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not configured")
    return create_engine(settings.database_url, pool_pre_ping=True)


def database_status(settings: Settings) -> dict[str, Any]:
    if not settings.database_url:
        return {
            "ok": True,
            "configured": False,
            "message": "DATABASE_URL is not configured; database checks skipped.",
        }

    try:
        engine = create_db_engine(settings)
        with engine.connect() as conn:
            value = conn.execute(text("select 1")).scalar_one()
        return {"ok": value == 1, "configured": True, "message": "Database reachable."}
    except Exception as exc:  # pragma: no cover - depends on external service
        return {
            "ok": False,
            "configured": True,
            "message": str(exc),
        }
