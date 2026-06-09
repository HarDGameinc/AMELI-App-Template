from __future__ import annotations

import json
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from ameli_app import __version__
from ameli_web.accounts.models import User, UserSession
from ameli_web.accounts.services import (
    admin_disable_mfa_for_user,
    change_password_for_user,
    create_user_account,
    delete_user_account,
    filtered_audit_queryset,
    filtered_users_queryset,
    list_recent_audit_entries,
    list_recent_sessions,
    list_users,
    paginate_admin_sessions,
    paginate_audit_for_admin,
    paginate_users_for_admin,
    serialize_audit_event,
    reset_user_password,
    revoke_session_record,
    serialize_user,
    summarize_users,
    update_user_account,
)


def _expects_json(request: HttpRequest) -> bool:
    content_type = request.headers.get("Content-Type", "")
    accept = request.headers.get("Accept", "")
    return (
        "application/json" in content_type
        or "application/json" in accept
        or bool(request.headers.get("X-CSRF-Token"))
    )


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _is_fetch_request(request: HttpRequest) -> bool:
    """True when the request looks like an AJAX panel swap, not a navigation.

    The frontend swap helper sets ``X-Requested-With: fetch`` (our marker)
    on the partial fetches. A direct browser refresh, share link, or a
    crawler will not carry that header, so they get the full page even if
    ``?partial=`` is present in the URL.
    """
    return request.headers.get("X-Requested-With", "").lower() in {"fetch", "xmlhttprequest"}


def _json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json body") from exc


def superadmin_required(view_func):
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            if _expects_json(request):
                return _json_error("authentication required", status=401)
            return redirect(f"/login/?next={request.path}")
        if not user.is_staff:
            if _expects_json(request):
                return _json_error("admin access required", status=403)
            return redirect("/profile/")
        return view_func(request, *args, **kwargs)

    return _wrapped


USERS_PER_PAGE_COOKIE = "ps_users_per_page"
AUDIT_PER_PAGE_COOKIE = "ps_audit_per_page"
SESSIONS_PER_PAGE_COOKIE = "ps_admin_sessions_per_page"


@require_GET
@superadmin_required
def admin_panel(request: HttpRequest) -> HttpResponse:
    from ameli_web.pagination import coerce_page, persist_per_page_cookie, resolve_per_page

    current_session_key = str(request.session.session_key or "")
    users_filters = {
        "search": (request.GET.get("users_search") or "").strip(),
        "role": (request.GET.get("users_role") or "").strip(),
        "status": (request.GET.get("users_status") or "").strip(),
    }
    users_per_page = resolve_per_page(request, USERS_PER_PAGE_COOKIE, default=25, query_param="users_per_page")
    users_page = paginate_users_for_admin(
        page=coerce_page(request.GET.get("users_page")),
        per_page=users_per_page,
        **users_filters,
    )
    audit_filters = {
        "actor": (request.GET.get("audit_actor") or "").strip(),
        "target": (request.GET.get("audit_target") or "").strip(),
        "action": (request.GET.get("audit_action") or "").strip(),
        "outcome": (request.GET.get("audit_outcome") or "").strip(),
        "date_from": (request.GET.get("audit_date_from") or "").strip(),
        "date_to": (request.GET.get("audit_date_to") or "").strip(),
        "payload": (request.GET.get("audit_payload") or "").strip(),
    }
    audit_per_page = resolve_per_page(request, AUDIT_PER_PAGE_COOKIE, default=30, query_param="audit_per_page")
    audit_page = paginate_audit_for_admin(
        page=coerce_page(request.GET.get("audit_page")),
        per_page=audit_per_page,
        **audit_filters,
    )
    sessions_filters = {
        "search": (request.GET.get("admin_sessions_search") or "").strip(),
        "status": (request.GET.get("admin_sessions_status") or "").strip(),
        "ip": (request.GET.get("admin_sessions_ip") or "").strip(),
    }
    sessions_per_page = resolve_per_page(
        request, SESSIONS_PER_PAGE_COOKIE, default=20, query_param="admin_sessions_per_page"
    )
    sessions_page = paginate_admin_sessions(
        page=coerce_page(request.GET.get("admin_sessions_page")),
        per_page=sessions_per_page,
        current_session_key=current_session_key,
        **sessions_filters,
    )

    context = {
        "version": __version__,
        "users": users_page.items,
        "users_pagination": users_page.as_context(
            page_param="users_page",
            anchor="admin-users-panel",
            per_page_param="users_per_page",
        ),
        "users_filters": users_filters,
        "audit_entries": audit_page.items,
        "audit_pagination": audit_page.as_context(
            page_param="audit_page",
            anchor="admin-audit-panel",
            per_page_param="audit_per_page",
        ),
        "audit_filters": audit_filters,
        "current_user": serialize_user(request.user),
        "user_summary": summarize_users(),
        "recent_sessions": sessions_page.items,
        "sessions_pagination": sessions_page.as_context(
            page_param="admin_sessions_page",
            anchor="admin-sessions-panel",
            per_page_param="admin_sessions_per_page",
        ),
        "sessions_filters": sessions_filters,
        "native_admin_url": "/django-admin/",
        "csrf_token": get_token(request),
    }
    # Only honor ``?partial=`` for real fetch requests. If someone refreshes
    # mid-swap or shares a deep link, ``partial=`` may linger in the URL —
    # serve the full page so the layout/css renders.
    partial = (request.GET.get("partial") or "").strip() if _is_fetch_request(request) else ""
    if partial == "users":
        response = render(request, "admin/_users_panel.html", context)
    elif partial == "audit":
        response = render(request, "admin/_audit_panel.html", context)
    elif partial == "sessions":
        response = render(request, "admin/_sessions_panel.html", context)
    else:
        response = render(request, "admin/panel.html", context)
    persist_per_page_cookie(response, request, USERS_PER_PAGE_COOKIE, query_param="users_per_page")
    persist_per_page_cookie(response, request, AUDIT_PER_PAGE_COOKIE, query_param="audit_per_page")
    persist_per_page_cookie(response, request, SESSIONS_PER_PAGE_COOKIE, query_param="admin_sessions_per_page")
    return response


@require_http_methods(["GET", "POST"])
@superadmin_required
def admin_users(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        users = list_users()
        return JsonResponse({"ok": True, "users": users, "summary": summarize_users()})
    payload = _json_body(request)
    try:
        result = create_user_account(
            actor_username=request.user.username,
            username=str(payload.get("username") or "").strip(),
            password=str(payload.get("password") or "").strip(),
            role=str(payload.get("role") or User.ROLE_PUBLIC).strip(),
            must_change_password=bool(payload.get("must_change_password")),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_GET
@superadmin_required
def admin_audit(request: HttpRequest) -> JsonResponse:
    limit = int(request.GET.get("limit", "30") or "30")
    actor = request.GET.get("actor")
    target = request.GET.get("target")
    return JsonResponse(
        {
            "ok": True,
            "items": list_recent_audit_entries(limit=limit, actor_username=actor, target_username=target),
        }
    )


@require_GET
@superadmin_required
def admin_sessions(request: HttpRequest) -> JsonResponse:
    limit = int(request.GET.get("limit", "30") or "30")
    current_session_key = str(request.session.session_key or "")
    return JsonResponse(
        {"ok": True, "items": list_recent_sessions(limit=limit, current_session_key=current_session_key)}
    )


@require_POST
@superadmin_required
def admin_revoke_session(request: HttpRequest, session_key: str) -> JsonResponse:
    session = UserSession.objects.select_related("user").filter(session_key=session_key).first()
    if session is None:
        return _json_error("session not found", status=404)
    revoke_session_record(session, actor=request.user, reason="admin-revoke")
    return JsonResponse({"ok": True, "status": "updated", "session_key": session_key})


@require_http_methods(["POST", "PATCH", "DELETE"])
@superadmin_required
def admin_update_user(request: HttpRequest, username: str) -> JsonResponse:
    if request.method == "DELETE":
        try:
            result = delete_user_account(actor_username=request.user.username, username=username)
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse(result)
    payload = _json_body(request)
    try:
        result = update_user_account(
            actor_username=request.user.username,
            username=username,
            password=(str(payload["password"]).strip() if payload.get("password") else None),
            enabled=payload.get("enabled"),
            must_change_password=payload.get("must_change_password"),
            role=payload.get("role"),
            mfa_required=payload.get("mfa_required"),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
def admin_disable_user_mfa(request: HttpRequest, username: str) -> JsonResponse:
    try:
        result = admin_disable_mfa_for_user(actor_username=request.user.username, username=username)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
def admin_reset_user_password(request: HttpRequest, username: str) -> JsonResponse:
    payload = _json_body(request)
    try:
        result = reset_user_password(
            actor_username=request.user.username,
            username=username,
            password=(str(payload["password"]).strip() if payload.get("password") else None),
            must_change_password=bool(payload.get("must_change_password", True)),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@require_POST
@superadmin_required
def admin_change_password(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    try:
        result = change_password_for_user(
            request.user.username,
            str(payload.get("current_password") or "").strip(),
            str(payload.get("new_password") or "").strip(),
            current_session_key=str(request.session.session_key or ""),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


_AUDIT_EXPORT_COLUMNS = [
    "id",
    "created_at",
    "actor_username",
    "target_username",
    "action",
    "display_result_label",
    "payload",
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
    import csv
    import io

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


_USERS_EXPORT_COLUMNS = [
    "username",
    "display_name",
    "role",
    "is_active",
    "must_change_password",
    "last_login",
    "date_joined",
]


def _users_export_filters(request: HttpRequest) -> dict[str, str]:
    """Read the same users filters used by the panel view."""
    return {
        "search": (request.GET.get("users_search") or "").strip(),
        "role": (request.GET.get("users_role") or "").strip(),
        "status": (request.GET.get("users_status") or "").strip(),
    }


def _iter_users_csv_rows(queryset):
    """Stream the users queryset row by row, encoding each row as a CSV line."""
    import csv
    import io

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


