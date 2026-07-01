"""Public entry point for ``ameli_web.accounts.views``.

After PC-2 (2026-07-01) view functions and classes live in per-domain
submodules. This file re-exports them so ``from . import views`` in
``accounts/urls.py`` keeps working as-is with ``views.<name>``.

New views should be added to the appropriate submodule and re-exported
here. External importers should continue to use the flat
``ameli_web.accounts.views`` surface.
"""
from __future__ import annotations

# ruff: noqa: I001

from .account import delete_my_account_view as delete_my_account_view
from .auth import (
    TemplateLoginView as TemplateLoginView,
    logout_view as logout_view,
    verify_mfa_resend_view as verify_mfa_resend_view,
    verify_mfa_view as verify_mfa_view,
)
from .email_change import (
    email_change_cancel_self_view as email_change_cancel_self_view,
    email_change_cancel_view as email_change_cancel_view,
    email_change_confirm_view as email_change_confirm_view,
    email_change_request_view as email_change_request_view,
)
from .mfa import (
    mfa_confirm_view as mfa_confirm_view,
    mfa_disable_view as mfa_disable_view,
    mfa_email_confirm_view as mfa_email_confirm_view,
    mfa_email_disable_view as mfa_email_disable_view,
    mfa_email_start_view as mfa_email_start_view,
    mfa_regenerate_view as mfa_regenerate_view,
    mfa_start_view as mfa_start_view,
    mfa_totp_disable_view as mfa_totp_disable_view,
)
from .password import (
    _build_public_base_url as _build_public_base_url,
    change_password_view as change_password_view,
    forgot_password_view as forgot_password_view,
    reset_password_view as reset_password_view,
)
from .profile import (
    delete_avatar_view as delete_avatar_view,
    profile_view as profile_view,
    send_profile_test_email_view as send_profile_test_email_view,
    update_avatar as update_avatar,
    update_preferences as update_preferences,
)
from .sessions import (
    admin_session_json as admin_session_json,
    revoke_other_sessions_view as revoke_other_sessions_view,
    revoke_session_view as revoke_session_view,
)
