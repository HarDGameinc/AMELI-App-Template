"""Profile MFA enrolment/disable/regenerate endpoints.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from ..services import (
    confirm_mfa_email_enrollment,
    confirm_mfa_enrollment,
    disable_mfa_email_for_self,
    disable_mfa_for_self,
    disable_mfa_totp_for_self,
    record_audit,
    regenerate_recovery_codes,
    start_mfa_email_enrollment,
    start_mfa_enrollment,
)
from ._common import (
    _json_body,
    _json_error,
    logger,
)


@login_required
@require_POST
def mfa_start_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = start_mfa_enrollment(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    # Expose the freshly generated QR svg and provisioning URI to the
    # caller. The plaintext secret is also returned so the user can copy
    # it into authenticator apps that do not accept QR.
    return JsonResponse(result)


@login_required
@require_POST
def mfa_confirm_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    code = str(payload.get("code") or "").strip()
    try:
        result = confirm_mfa_enrollment(request.user.username, code)
    except ValueError as exc:
        record_audit(
            "mfa_enrollment_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": str(exc)},
        )
        return _json_error(str(exc))
    # Enabling MFA is a privilege change. Rotate the session key so any
    # parallel cookie (stolen via XSS, copied from a shared machine) is
    # invalidated and the legitimate user keeps going on a fresh one.
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_disable_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = disable_mfa_for_self(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_totp_disable_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = disable_mfa_totp_for_self(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_disable_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = disable_mfa_email_for_self(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_regenerate_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = regenerate_recovery_codes(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_start_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    current_password = str(payload.get("current_password") or "").strip()
    try:
        result = start_mfa_email_enrollment(request.user.username, current_password=current_password)
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        logger.exception("email mfa enrollment delivery failed for %s", request.user.username)
        return _json_error(f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502)
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_confirm_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    code = str(payload.get("code") or "").strip()
    try:
        result = confirm_mfa_email_enrollment(request.user.username, code)
    except ValueError as exc:
        record_audit(
            "mfa_email_enrollment_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": str(exc)},
        )
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)
