from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.urls import include, path, re_path
from django.views.static import serve

from ameli_web import admin_views
from ameli_web.dashboard import views as dashboard_views

admin.site.site_header = "AMELI App Template"
admin.site.site_title = "AMELI App"
admin.site.index_title = "Administracion"

urlpatterns = [
    path("", dashboard_views.home, name="dashboard-home"),
    path("docs", dashboard_views.docs, name="api-docs"),
    path("redoc", dashboard_views.redoc, name="api-redoc"),
    path("openapi.json", dashboard_views.openapi_schema, name="openapi-schema"),
    path("api/health", dashboard_views.api_health, name="api-health"),
    path("health", dashboard_views.health, name="health"),
    path("metrics", dashboard_views.metrics, name="metrics"),
    path("", include(("ameli_web.accounts.urls", "accounts"), namespace="accounts")),
    path("admin/", admin_views.admin_panel, name="admin-panel"),
    path("admin/users", admin_views.admin_users, name="admin-users"),
    path("admin/audit", admin_views.admin_audit, name="admin-audit"),
    path("admin/audit/export/", admin_views.admin_audit_export, name="admin-audit-export"),
    path("admin/users/export/", admin_views.admin_users_export, name="admin-users-export"),
    path("admin/sessions", admin_views.admin_sessions, name="admin-sessions"),
    path("admin/sessions/<str:session_key>/revoke", admin_views.admin_revoke_session, name="admin-revoke-session"),
    path("admin/users/<str:username>", admin_views.admin_update_user, name="admin-update-user"),
    path(
        "admin/users/<str:username>/reset-password",
        admin_views.admin_reset_user_password,
        name="admin-reset-user-password",
    ),
    path(
        "admin/users/<str:username>/disable-mfa",
        admin_views.admin_disable_user_mfa,
        name="admin-disable-user-mfa",
    ),
    path("admin/change-password", admin_views.admin_change_password, name="admin-change-password"),
    path("admin/sudo/", admin_views.admin_sudo, name="admin-sudo"),
    path("admin/sudo", admin_views.admin_sudo),
    path("admin/sudo/status/", admin_views.admin_sudo_status, name="admin-sudo-status"),
    path("admin/sudo/email-code/", admin_views.admin_sudo_email_code, name="admin-sudo-email-code"),
    path("admin/django-admin/enter/", admin_views.admin_django_admin_enter, name="admin-django-admin-enter"),
    path("django-admin/", admin.site.urls),
]

static_root = Path(settings.STATICFILES_DIRS[0])
media_root = Path(settings.MEDIA_ROOT)


def _authenticated_media(request, path):
    """Gate ``/media/`` behind login.

    Avatars (and any future user-uploaded blob) live here. Without this
    gate, anyone who guesses a filename can fetch it bypassing the rest
    of the auth model. In production, Caddy/nginx is expected to enforce
    the same rule and serve the bytes directly; this view is the
    fallback when no reverse proxy is in front.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("authentication required")
    try:
        return serve(request, path, document_root=str(media_root))
    except Http404:
        raise


# ``django.views.static.serve`` is documented as dev-only by Django, but
# AMELI deploys typically run on internal hosts without a reverse proxy
# in front. Serving ``/static/`` ourselves keeps the UI working in that
# common case; production deploys with Caddy/nginx in front will have
# the proxy intercept ``/static/`` first and never hit this handler.
# ``/media/`` always goes through the auth gate as defence in depth even
# when a reverse proxy is present.
urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": str(static_root)}),
    re_path(r"^media/(?P<path>.*)$", _authenticated_media),
]
