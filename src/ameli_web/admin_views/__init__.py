"""Public entry point for ``ameli_web.admin_views``.

After PC-3 (2026-07-01) admin view functions live in per-domain
submodules. This file re-exports them so ``from ameli_web import
admin_views`` in ``ameli_web/urls.py`` keeps working as-is with
``admin_views.<name>``.

New views should be added to the appropriate submodule and re-exported
here. External importers should continue to use the flat
``ameli_web.admin_views`` surface.
"""
from __future__ import annotations

# ruff: noqa: I001

from ._common import (
    AUDIT_PER_PAGE_COOKIE as AUDIT_PER_PAGE_COOKIE,
    SESSIONS_PER_PAGE_COOKIE as SESSIONS_PER_PAGE_COOKIE,
    USERS_PER_PAGE_COOKIE as USERS_PER_PAGE_COOKIE,
    _expects_json as _expects_json,
    _is_fetch_request as _is_fetch_request,
    _json_body as _json_body,
    _json_error as _json_error,
    sudo_required as sudo_required,
    superadmin_required as superadmin_required,
)
from .audit import admin_audit as admin_audit
from .exports import (
    _csv_safe as _csv_safe,
    admin_audit_export as admin_audit_export,
    admin_users_export as admin_users_export,
)
from .maintenance import (
    admin_maintenance_status as admin_maintenance_status,
    admin_maintenance_toggle as admin_maintenance_toggle,
)
from .metrics import admin_email_queue_metrics as admin_email_queue_metrics
from .panel import admin_panel as admin_panel
from .sessions import (
    admin_revoke_session as admin_revoke_session,
    admin_sessions as admin_sessions,
)
from .sudo import (
    admin_django_admin_enter as admin_django_admin_enter,
    admin_sudo as admin_sudo,
    admin_sudo_email_code as admin_sudo_email_code,
    admin_sudo_status as admin_sudo_status,
)
from .users import (
    admin_change_password as admin_change_password,
    admin_disable_user_mfa as admin_disable_user_mfa,
    admin_reset_user_password as admin_reset_user_password,
    admin_unlock_user as admin_unlock_user,
    admin_update_user as admin_update_user,
    admin_users as admin_users,
)
