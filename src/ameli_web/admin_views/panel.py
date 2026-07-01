"""Admin panel HTML render.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ameli_app import __version__
from ameli_web.accounts.services import (
    get_maintenance_state,
    paginate_admin_sessions,
    paginate_audit_for_admin,
    paginate_users_for_admin,
    serialize_user,
    summarize_email_queue,
    summarize_users,
)

from ._common import (
    AUDIT_PER_PAGE_COOKIE,
    SESSIONS_PER_PAGE_COOKIE,
    USERS_PER_PAGE_COOKIE,
    _is_fetch_request,
    superadmin_required,
)


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
        "email_queue_summary": summarize_email_queue(),
        "maintenance_state": get_maintenance_state(),
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
    elif partial == "admin_sessions":
        # The admin-side sessions panel uses ``admin_sessions`` so it
        # doesn't collide with the per-user sessions panel served at
        # /profile/ (``partial=sessions`` there). Without this match
        # the JS pagination footer was getting back the full /admin/
        # page and the panel rendered the whole site recursively.
        response = render(request, "admin/_sessions_panel.html", context)
    else:
        response = render(request, "admin/panel.html", context)
    persist_per_page_cookie(response, request, USERS_PER_PAGE_COOKIE, query_param="users_per_page")
    persist_per_page_cookie(response, request, AUDIT_PER_PAGE_COOKIE, query_param="audit_per_page")
    persist_per_page_cookie(response, request, SESSIONS_PER_PAGE_COOKIE, query_param="admin_sessions_per_page")
    return response
