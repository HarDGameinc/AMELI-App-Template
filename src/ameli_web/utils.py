from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.conf import settings

_ui_timezone = ZoneInfo(settings.TIME_ZONE)


def coerce_datetime(value: object) -> datetime | None:
    if value in (None, "", "-"):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_ui_timezone)


def format_timestamp_ui(value: object) -> str:
    dt = coerce_datetime(value)
    if dt is None:
        return "-" if value in (None, "", "-") else str(value)
    return dt.strftime("%d-%m-%Y %H:%M")


def relative_minutes_label(value: object) -> str:
    dt = coerce_datetime(value)
    if dt is None:
        return "-"
    delta = datetime.now(dt.tzinfo) - dt
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 1:
        return "hace menos de 1 min"
    if minutes == 1:
        return "hace 1 min"
    if minutes < 60:
        return f"hace {minutes} min"
    hours = minutes // 60
    if hours == 1:
        return "hace 1 hora"
    if hours < 24:
        return f"hace {hours} horas"
    days = hours // 24
    if days == 1:
        return "hace 1 día"
    return f"hace {days} días"
