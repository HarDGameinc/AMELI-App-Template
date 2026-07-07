"""Sudo grant + email code + status + Django admin gate.

Moved from ameli_web/admin_views.py (PC-3, 2026-07-01).
Public symbols re-exported via ameli_web/admin_views/__init__.py;
urls.py imports the package via ``from ameli_web import admin_views``
and uses ``admin_views.X``.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from ._common import (
    _json_body,
    _json_error,
    sudo_required,
    superadmin_required,
)


@require_POST
@superadmin_required
def admin_sudo(request: HttpRequest) -> JsonResponse:
    """Re-authenticate the operator and stamp the session as ``sudo``.

    The UI calls this when a privileged action returns 401 with
    ``need_sudo: true``. On success the session carries a short-lived
    grace window during which subsequent sensitive actions skip the
    prompt.
    """
    from ameli_web.accounts.services import grant_sudo, verify_sudo_credentials

    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    password = str(payload.get("password") or "")
    mfa_code = str(payload.get("mfa_code") or "")
    try:
        verify_sudo_credentials(
            request.user, password=password, mfa_code=mfa_code
        )
    except ValueError as exc:
        from ameli_web.accounts.services import record_audit

        record_audit(
            "sudo_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": str(exc)},
        )
        return _json_error(str(exc), status=403)
    grace = grant_sudo(request.session)
    from ameli_web.accounts.services import record_audit

    record_audit(
        "sudo_granted",
        actor=request.user,
        target_username=request.user.username,
        payload={"grace_seconds": grace},
    )
    return JsonResponse(
        {"ok": True, "expires_in_seconds": grace, "mfa_required": request.user.mfa_enabled}
    )


@require_POST
@superadmin_required
def admin_sudo_email_code(request: HttpRequest) -> JsonResponse:
    """Dispatch a single-use email code so the operator can complete a
    sudo prompt without their authenticator app. Throttled per-user by
    the existing email MFA rate limit so spamming is bounded."""
    from ameli_web.accounts.services import (
        LoginThrottled,
        check_mfa_resend_throttle,
        client_ip,
        record_audit,
        send_sudo_email_code,
    )

    ip = client_ip(request)
    try:
        check_mfa_resend_throttle(ip=ip)
    except LoginThrottled as exc:
        return _json_error(str(exc), status=429)
    record_audit(
        "sudo_email_code_requested",
        actor=request.user,
        target_username=request.user.username,
        payload={"ip": ip},
    )
    try:
        result = send_sudo_email_code(request.user)
    except ValueError as exc:
        return _json_error(str(exc), status=400)
    except Exception as exc:  # noqa: BLE001
        return _json_error(
            f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502
        )
    return JsonResponse(result)


@require_GET
@superadmin_required
def admin_sudo_status(request: HttpRequest) -> JsonResponse:
    """Surface the operator's MFA enrollment so the sudo modal can render
    the right inputs (TOTP, email button, recovery codes hint)."""
    from ameli_web.accounts.services import session_in_sudo

    user = request.user
    return JsonResponse(
        {
            "ok": True,
            "in_sudo": session_in_sudo(request.session),
            "mfa": {
                "enabled": bool(user.mfa_enabled),
                "totp": bool(user.mfa_totp_enabled),
                "email": bool(user.mfa_email_enabled),
                "email_address": user.email if user.mfa_email_enabled else "",
            },
        }
    )


@require_POST
@superadmin_required
@sudo_required
def admin_django_admin_enter(request: HttpRequest) -> JsonResponse:
    """Sudo-gated jump-off point for the native ``/django-admin/``.

    The panel button posts here; the sudo decorator above produces the
    standard ``need_sudo`` 401 when the session is not in grace, so the
    existing modal opens. On success the response carries the
    redirect URL the frontend uses to navigate, and we audit who jumped
    in so an attacker who steals a sudo'd session leaves a trace.
    """
    from ameli_web.accounts.services import record_audit

    record_audit(
        "django_admin_entered",
        actor=request.user,
        target_username=request.user.username,
        payload={},
    )
    return JsonResponse({"ok": True, "redirect": "/django-admin/"})
