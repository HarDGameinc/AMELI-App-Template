"""CSV/JSON export helpers + audit/users export endpoints.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

import csv
import io
import json

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET

from ameli_web.accounts.services import (
    filtered_audit_queryset,
    filtered_users_queryset,
    serialize_audit_event,
)

from ._common import (
    superadmin_required,
)

_AUDIT_EXPORT_COLUMNS = [
    "id",
    "created_at",
    "actor_username",
    "target_username",
    "action",
    "display_result_label",
    "payload",
]


_USERS_EXPORT_COLUMNS = [
    "username",
    "display_name",
    "role",
    "is_active",
    "must_change_password",
    "last_login",
    "date_joined",
]


def _audit_export_filters(request: HttpRequest) -> dict[str, str]:
    """Read the same audit filters used by the panel view."""
    return {
        "actor": (request.GET.get("audit_actor") or "").strip(),
        "target": (request.GET.get("audit_target") or "").strip(),
        "action": (request.GET.get("audit_action") or "").strip(),
        "outcome": (request.GET.get("audit_outcome") or "").strip(),
        "date_from": (request.GET.get("audit_date_from") or "").strip(),
        "date_to": (request.GET.get("audit_date_to") or "").strip(),
        "payload": (request.GET.get("audit_payload") or "").strip(),
    }


def _csv_safe(value):
    """Defang CSV-injection ("formula injection") payloads.

    Excel and LibreOffice treat any cell whose first character is one of
    ``= + - @`` (also tab/CR after a quote, sometimes) as a formula. An
    attacker who controls a username, target field or audit payload can
    inject ``=HYPERLINK(...)`` and have the operator's spreadsheet phone
    home or execute external functions. We neutralise the cell by prefixing
    it with a single quote, which Excel strips on display but interpreters
    no longer treat as code.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _iter_audit_csv_rows(queryset):
    """Stream the audit queryset row by row, encoding each row as a CSV line.

    Yielding strings into :class:`StreamingHttpResponse` lets us export an
    arbitrary number of events without holding everything in memory.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def _flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow(_AUDIT_EXPORT_COLUMNS)
    yield _flush()

    for event in queryset.iterator(chunk_size=200):
        row = serialize_audit_event(event)
        writer.writerow([
            row.get("id"),
            row.get("created_at"),
            _csv_safe(row.get("actor_username")),
            _csv_safe(row.get("target_username")),
            _csv_safe(row.get("action")),
            _csv_safe(row.get("display_result_label")),
            _csv_safe(json.dumps(row.get("payload") or {}, ensure_ascii=False, sort_keys=True)),
        ])
        yield _flush()


def _iter_audit_json_rows(queryset):
    """Stream the audit queryset as a single JSON array."""
    yield "["
    first = True
    for event in queryset.iterator(chunk_size=200):
        row = serialize_audit_event(event)
        payload = {
            "id": row.get("id"),
            "created_at": row.get("created_at"),
            "actor_username": row.get("actor_username") or "",
            "target_username": row.get("target_username") or "",
            "action": row.get("action") or "",
            "result": row.get("display_result_label") or "",
            "payload": row.get("payload") or {},
        }
        yield ("" if first else ",") + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        first = False
    yield "]"


@require_GET
@superadmin_required
def admin_audit_export(request: HttpRequest) -> HttpResponse:
    """Download the (filtered) audit log as CSV or JSON."""
    fmt = (request.GET.get("format") or "csv").strip().lower()
    queryset = filtered_audit_queryset(**_audit_export_filters(request))

    if fmt == "json":
        response = StreamingHttpResponse(_iter_audit_json_rows(queryset), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="audit.json"'
        return response

    response = StreamingHttpResponse(_iter_audit_csv_rows(queryset), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit.csv"'
    return response


def _users_export_filters(request: HttpRequest) -> dict[str, str]:
    """Read the same users filters used by the panel view."""
    return {
        "search": (request.GET.get("users_search") or "").strip(),
        "role": (request.GET.get("users_role") or "").strip(),
        "status": (request.GET.get("users_status") or "").strip(),
    }


def _iter_users_csv_rows(queryset):
    """Stream the users queryset row by row, encoding each row as a CSV line."""

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def _flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow(_USERS_EXPORT_COLUMNS)
    yield _flush()

    for user in queryset.iterator(chunk_size=200):
        writer.writerow([
            _csv_safe(user.username),
            _csv_safe(user.display_name),
            _csv_safe(user.role),
            "yes" if user.is_active else "no",
            "yes" if user.must_change_password else "no",
            user.last_login.isoformat() if user.last_login else "",
            user.date_joined.isoformat() if user.date_joined else "",
        ])
        yield _flush()


def _iter_users_json_rows(queryset):
    """Stream the users queryset as a single JSON array."""
    yield "["
    first = True
    for user in queryset.iterator(chunk_size=200):
        payload = {
            "username": user.username,
            "display_name": user.display_name or "",
            "role": user.role,
            "is_active": bool(user.is_active),
            "must_change_password": bool(user.must_change_password),
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        }
        yield ("" if first else ",") + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        first = False
    yield "]"


@require_GET
@superadmin_required
def admin_users_export(request: HttpRequest) -> HttpResponse:
    """Download the (filtered) users list as CSV or JSON."""
    fmt = (request.GET.get("format") or "csv").strip().lower()
    queryset = filtered_users_queryset(**_users_export_filters(request))

    if fmt == "json":
        response = StreamingHttpResponse(_iter_users_json_rows(queryset), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="users.json"'
        return response

    response = StreamingHttpResponse(_iter_users_csv_rows(queryset), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="users.csv"'
    return response




# ============================ Sudo (re-auth gate) ============================
