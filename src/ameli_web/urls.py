from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import Http404, HttpResponseForbidden
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
    path("admin/metrics/email-queue", admin_views.admin_email_queue_metrics, name="admin-email-queue-metrics"),
    path("admin/maintenance/", admin_views.admin_maintenance_toggle, name="admin-maintenance-toggle"),
    path("admin/maintenance/status/", admin_views.admin_maintenance_status, name="admin-maintenance-status"),
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
    path(
        "admin/users/<str:username>/unlock",
        admin_views.admin_unlock_user,
        name="admin-unlock-user",
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


def _serve_static(request, path):
    """Resolve a ``/static/<path>`` request via Django's finder pipeline.

    The default ``django.views.static.serve`` only looks at one
    directory, which means ``/static/admin/js/nav_sidebar.js`` (shipped
    inside ``django/contrib/admin/static/``) is never found and the
    browser receives an HTML 404. That, combined with
    ``X-Content-Type-Options: nosniff``, breaks the entire Django admin
    UI under our deploy because every asset gets refused for MIME
    mismatch.

    Walking ``staticfiles.finders.find`` instead pulls in our own
    ``STATICFILES_DIRS`` plus every installed app's ``static/`` folder,
    so the admin's bundled CSS/JS resolves naturally without requiring
    ``collectstatic`` at deploy time. Production deploys behind Caddy
    or nginx never hit this handler — the proxy intercepts ``/static/``
    first.
    """
    from django.contrib.staticfiles import finders

    absolute = finders.find(path)
    if not absolute:
        raise Http404(f"static file not found: {path}")
    return serve(request, Path(absolute).name, document_root=str(Path(absolute).parent))


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
    re_path(r"^static/(?P<path>.*)$", _serve_static),
    re_path(r"^media/(?P<path>.*)$", _authenticated_media),
]
