"""Public entry point for ``ameli_web.accounts.services``.

After PC-1 (steps 2-8 + cleanup, 2026-06-27 to 2026-07-01) the business
logic lives in per-domain submodules. This file exists so external
callers keep working with the flat import path
``from ameli_web.accounts.services import X`` — pinning the API
surface while the internal split evolved.

New callers should import from here too, not from the submodules. The
submodule layout is an implementation detail that may keep changing.
"""
from __future__ import annotations

# ruff: noqa: I001

# Model re-exports — callers historically imported these via services
# for convenience; kept here to preserve the flat import surface.
from ..models import EmailChangeRequest as EmailChangeRequest

# Audit chain — services/audit.py (PC-1 step 2, 2026-06-27).
from .audit import (
    _audit_canonical as _audit_canonical,
    _audit_hmac as _audit_hmac,
    _audit_hmac_key as _audit_hmac_key,
    _normalise_audit_payload as _normalise_audit_payload,
    apply_audit_key_to_env_file as apply_audit_key_to_env_file,
    record_audit as record_audit,
    rotate_audit_key as rotate_audit_key,
    verify_audit_chain as verify_audit_chain,
)

# Auth-failure alerts — services/auth_alerts.py (PC-1 cleanup, 2026-07-01).
from .auth_alerts import (
    AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT as AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT,
    _auth_failures_alert_cooldown as _auth_failures_alert_cooldown,
    _maybe_alert_for_auth_failures_burst as _maybe_alert_for_auth_failures_burst,
    _send_auth_failures_alert as _send_auth_failures_alert,
)

# Email-change double-opt-in flow — services/email_change.py (PC-1 cleanup, 2026-07-01).
from .email_change import (
    EMAIL_CHANGE_TOKEN_BYTES as EMAIL_CHANGE_TOKEN_BYTES,
    EMAIL_CHANGE_TTL_HOURS_DEFAULT as EMAIL_CHANGE_TTL_HOURS_DEFAULT,
    _build_email_change_urls as _build_email_change_urls,
    _build_public_base_url as _build_public_base_url,
    _find_email_change_request as _find_email_change_request,
    _hash_email_change_token as _hash_email_change_token,
    _send_email_change_alert as _send_email_change_alert,
    _send_email_change_confirmation as _send_email_change_confirmation,
    cancel_email_change as cancel_email_change,
    confirm_email_change as confirm_email_change,
    pending_email_change_for as pending_email_change_for,
    request_email_change as request_email_change,
)

# Email queue (transport layer) — services/email_queue.py (PC-1 step 5, 2026-06-30).
from .email_queue import (
    _PasswordResetEmail as _PasswordResetEmail,
    process_email_queue as process_email_queue,
    send_with_retry as send_with_retry,
)

# Maintenance mode — services/maintenance.py (PC-1 step 7, 2026-06-30).
from .maintenance import (
    disable_maintenance as disable_maintenance,
    enable_maintenance as enable_maintenance,
    get_maintenance_state as get_maintenance_state,
)

# MFA domain (TOTP + email-based MFA + recovery codes) — services/mfa.py (PC-1 step 6, 2026-06-30).
from .mfa import (
    _check_email_mfa_rate_limit as _check_email_mfa_rate_limit,
    _create_and_send_email_challenge as _create_and_send_email_challenge,
    _send_mfa_disabled_by_admin_notification as _send_mfa_disabled_by_admin_notification,
    _send_mfa_email_code as _send_mfa_email_code,
    admin_disable_mfa_for_user as admin_disable_mfa_for_user,
    confirm_mfa_email_enrollment as confirm_mfa_email_enrollment,
    confirm_mfa_enrollment as confirm_mfa_enrollment,
    consume_email_mfa_code as consume_email_mfa_code,
    consume_recovery_code as consume_recovery_code,
    disable_mfa_email_for_self as disable_mfa_email_for_self,
    disable_mfa_for_self as disable_mfa_for_self,
    disable_mfa_totp_for_self as disable_mfa_totp_for_self,
    regenerate_recovery_codes as regenerate_recovery_codes,
    send_mfa_email_login_code as send_mfa_email_login_code,
    serialize_mfa_status as serialize_mfa_status,
    start_mfa_email_enrollment as start_mfa_email_enrollment,
    start_mfa_enrollment as start_mfa_enrollment,
)

# Password reset by email — services/password_reset.py (PC-1 step 7, 2026-06-30).
from .password_reset import (
    _build_reset_url as _build_reset_url,
    _decode_uid as _decode_uid,
    _find_user_for_reset as _find_user_for_reset,
    _send_password_reset_email as _send_password_reset_email,
    complete_password_reset as complete_password_reset,
    get_user_for_reset_token as get_user_for_reset_token,
    request_password_reset as request_password_reset,
)

# Reporting — services/reporting.py (PC-1 cleanup, 2026-07-01).
from .reporting import (
    _audit_queryset_for_filters as _audit_queryset_for_filters,
    _display_tone_for_action as _display_tone_for_action,
    filtered_audit_queryset as filtered_audit_queryset,
    list_recent_audit_entries as list_recent_audit_entries,
    paginate_audit_for_admin as paginate_audit_for_admin,
    serialize_audit_event as serialize_audit_event,
    summarize_email_queue as summarize_email_queue,
    summarize_users as summarize_users,
)

# Retention sweep — services/retention.py (PC-1 cleanup, 2026-07-01).
from .retention import (
    _prune_audit_with_anchor as _prune_audit_with_anchor,
    run_retention_sweep as run_retention_sweep,
)

# Session domain (UserSession sync/revoke/listing) — services/session.py (PC-1 step 7, 2026-06-30).
from .session import (
    _admin_sessions_queryset_for_filters as _admin_sessions_queryset_for_filters,
    _trusted_proxies as _trusted_proxies,
    client_ip as client_ip,
    list_recent_sessions as list_recent_sessions,
    list_user_sessions as list_user_sessions,
    paginate_admin_sessions as paginate_admin_sessions,
    paginate_user_sessions as paginate_user_sessions,
    revoke_other_sessions as revoke_other_sessions,
    revoke_session_record as revoke_session_record,
    serialize_session as serialize_session,
    sync_request_session as sync_request_session,
)

# Sudo grants for sensitive admin actions — services/sudo.py (PC-1 step 4, 2026-06-27).
from .sudo import (
    SUDO_GRACE_SECONDS_DEFAULT as SUDO_GRACE_SECONDS_DEFAULT,
    SudoRequired as SudoRequired,
    _check_sudo_throttle as _check_sudo_throttle,
    _record_sudo_failure as _record_sudo_failure,
    _sudo_throttle_key as _sudo_throttle_key,
    grant_sudo as grant_sudo,
    revoke_sudo as revoke_sudo,
    send_sudo_email_code as send_sudo_email_code,
    session_in_sudo as session_in_sudo,
    verify_sudo_credentials as verify_sudo_credentials,
)

# Throttle counters + login lockout + auxiliary rate limits — services/throttle.py (PC-1 step 3, 2026-06-27).
from .throttle import (
    AccountLocked as AccountLocked,
    FORGOT_PASSWORD_IP_MAX_DEFAULT as FORGOT_PASSWORD_IP_MAX_DEFAULT,
    FORGOT_PASSWORD_IP_WINDOW_DEFAULT as FORGOT_PASSWORD_IP_WINDOW_DEFAULT,
    LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT as LOCKOUT_PERMANENT_CONSECUTIVE_DEFAULT,
    LOGIN_LOCKOUT_USER_MAX_DEFAULT as LOGIN_LOCKOUT_USER_MAX_DEFAULT,
    LOGIN_LOCKOUT_USER_WINDOW_DEFAULT as LOGIN_LOCKOUT_USER_WINDOW_DEFAULT,
    LOGIN_THROTTLE_IP_MAX_DEFAULT as LOGIN_THROTTLE_IP_MAX_DEFAULT,
    LOGIN_THROTTLE_IP_WINDOW_DEFAULT as LOGIN_THROTTLE_IP_WINDOW_DEFAULT,
    LoginThrottled as LoginThrottled,
    MFA_RESEND_IP_MAX_DEFAULT as MFA_RESEND_IP_MAX_DEFAULT,
    MFA_RESEND_IP_WINDOW_DEFAULT as MFA_RESEND_IP_WINDOW_DEFAULT,
    _bump_throttle_counter as _bump_throttle_counter,
    _consecutive_lockouts_for as _consecutive_lockouts_for,
    _count_recent_audit_by_action as _count_recent_audit_by_action,
    _count_recent_login_failures as _count_recent_login_failures,
    _read_throttle_counter as _read_throttle_counter,
    _read_throttle_counter_sliding as _read_throttle_counter_sliding,
    _throttle_settings as _throttle_settings,
    _window_start_for as _window_start_for,
    admin_unlock_user as admin_unlock_user,
    check_forgot_password_throttle as check_forgot_password_throttle,
    check_login_throttle as check_login_throttle,
    check_mfa_resend_throttle as check_mfa_resend_throttle,
    maybe_permanently_lock as maybe_permanently_lock,
    record_login_failure as record_login_failure,
)

# User domain (CRUD + serialize + avatars + password/email change for self + account deletion)
# — services/user.py (PC-1 step 8, 2026-06-30).
from .user import (
    ROLE_GROUPS as ROLE_GROUPS,
    _validate_password_value as _validate_password_value,
    bootstrap_superadmin as bootstrap_superadmin,
    change_email_for_self as change_email_for_self,
    change_password_for_user as change_password_for_user,
    create_public_user as create_public_user,
    create_user_account as create_user_account,
    delete_avatar as delete_avatar,
    delete_my_account as delete_my_account,
    delete_user_account as delete_user_account,
    ensure_role_groups as ensure_role_groups,
    filtered_users_queryset as filtered_users_queryset,
    list_users as list_users,
    paginate_users_for_admin as paginate_users_for_admin,
    purge_inactive_users as purge_inactive_users,
    replace_avatar as replace_avatar,
    reset_user_password as reset_user_password,
    send_profile_test_email as send_profile_test_email,
    serialize_user as serialize_user,
    sync_user_groups as sync_user_groups,
    update_user_account as update_user_account,
)
