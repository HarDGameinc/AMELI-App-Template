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
    path("health/deep", dashboard_views.health_deep, name="health-deep"),
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


def _safe_username_slug(username: str) -> str:
    """Mirror the slug logic used in ``accounts.models.avatar_upload_to``.

    Kept here (instead of imported) to avoid a circular import between
    ``urls.py`` and ``accounts.models``. If the upload-side slug logic
    changes, this MUST be updated in lockstep — otherwise the ownership
    check breaks for any user whose username contains non-alphanumeric
    characters.
    """
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in (username or "user")).strip("-") or "user"


def _parse_avatar_filename(path: str):
    """Extract ``(safe_username, token)`` from an avatar media path.

    Returns ``None`` when the path does not match the
    ``avatars/<slug>-<16hex>.<ext>`` shape produced by
    ``avatar_upload_to``. A malformed avatar path is treated as a 404
    upstream — never as a 403 — so the response does not leak whether
    the file would have existed under a different request user.
    """
    import re

    if not path.startswith("avatars/"):
        return None
    name = path[len("avatars/"):]
    match = re.match(r"^(.+)-([0-9a-f]{16})\.[A-Za-z0-9]+$", name)
    if not match:
        return None
    return match.group(1), match.group(2)


def _authenticated_media(request, path):
    """Gate ``/media/`` behind login + (for avatars) ownership.

    ASVS V4.2.1 — sensitive resources protected against IDOR. The
    previous implementation only checked authentication; any logged-in
    user could fetch any other user's avatar by guessing the random
    64-bit filename token (or by reading the token out of the admin
    user-list JSON, which leaks ``avatar_url`` for every account).

    The current implementation:

    * Anonymous request → 403 (unchanged).
    * Authenticated request for a NON-avatar path (e.g. a future blob
      type) → unchanged auth-only gate; we keep the existing
      ``tests/test_media_auth_gate.py`` contract green.
    * Authenticated request for an avatar path:
        - owner of the file (slug matches current user) → serve.
        - superadmin (``is_staff``) → serve. An operator viewing the
          admin user list may legitimately need to see avatars.
        - malformed path → 404 (does not leak owner existence).
        - other → 403 + ``media_access_denied`` audit row keyed to
          the AVATAR OWNER's slug, not the requester (so an operator
          grep-ing the audit chain can see "Carlos tried to fetch
          Alice's avatar" rather than "Carlos tried something").

    Defence in depth: when Caddy/nginx serves ``/media/`` directly in
    production, it usually still proxies authenticated requests
    through this view first; the view's verdict is the authoritative
    one.
    """
    from ameli_web.accounts.permissions import can_view_avatar, is_authenticated

    user = getattr(request, "user", None)
    if not is_authenticated(user):
        return HttpResponseForbidden("authentication required")
    parsed = _parse_avatar_filename(path)
    if parsed is not None:
        safe_username, _token = parsed
        requester_slug = _safe_username_slug(user.username)
        if not can_view_avatar(user, owner_slug=safe_username, requester_slug=requester_slug):
            # Deliberate: audit the OWNER's slug as the target so the
            # audit chain answers "who was probed?" rather than just
            # "who probed?". The requester is captured by ``actor``.
            from ameli_web.accounts.services import record_audit

            record_audit(
                "media_access_denied",
                actor=user,
                target_username=safe_username,
                payload={"path": path, "reason": "not_owner"},
            )
            return HttpResponseForbidden("access denied")
    # Non-avatar paths and authorised avatar paths fall through to the
    # same ``serve`` path the previous implementation used.
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

# Branded HTTP error handlers (ASVS V7.4.1). Django invokes these
# only when ``DEBUG=False`` — in dev the yellow screen of death wins.
# All four go through ``ameli_web.error_views._render`` which extends
# ``base.html`` and surfaces the ``request_id`` so the user can quote
# it in support. See module docstring for the full rationale.
handler400 = "ameli_web.error_views.handler_400"
handler403 = "ameli_web.error_views.handler_403"
handler404 = "ameli_web.error_views.handler_404"
handler500 = "ameli_web.error_views.handler_500"
