"""Password change + forgot + reset flows.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from ameli_app import __version__

from ..forms import (
    ProfilePasswordForm,
)
from ..services import (
    change_password_for_user,
    complete_password_reset,
    get_user_for_reset_token,
    record_audit,
    request_password_reset,
    serialize_user,
)
from ._common import (
    User,
    _expects_json,
    _json_body,
    _json_error,
)


@login_required
@require_http_methods(["GET", "POST"])
def change_password_view(request: HttpRequest) -> HttpResponse:
    # ``/profile/password/`` is the submit target of the change form, but
    # any flow that lands here with a GET deserves to see the form.
    # When ``must_change_password=True`` we render a STANDALONE form
    # template (no other profile data) — the legacy redirect to
    # ``/profile/#profile-tab-security`` leaked MFA enrolment, session
    # list, and audit log to anyone holding a temp password from an
    # admin reset. Users not in the must-change state get the normal
    # tabbed profile view.
    if request.method == "GET":
        if getattr(request.user, "must_change_password", False):
            return render(
                request,
                "accounts/force_password_change.html",
                {
                    "current_user": serialize_user(request.user),
                    "password_form": ProfilePasswordForm(request.user),
                    "csrf_token": get_token(request),
                    "version": __version__,
                },
            )
        return redirect("/profile/#profile-tab-security")
    if _expects_json(request):
        try:
            payload = _json_body(request)
        except ValueError as exc:
            return _json_error(str(exc))
        current_password = str(payload.get("current_password") or payload.get("old_password") or "").strip()
        new_password = str(payload.get("new_password") or payload.get("new_password1") or "").strip()
        if not current_password or not new_password:
            return _json_error("current_password and new_password are required")
        try:
            from ..services import revoke_sudo

            result = change_password_for_user(
                request.user.username,
                current_password,
                new_password,
                current_session_key=str(request.session.session_key or ""),
            )
            user = User.objects.get(pk=request.user.pk)
            update_session_auth_hash(request, user)
            # A password change should invalidate any open sudo grant:
            # an attacker that grabbed a sudo'd session must lose it the
            # moment the legitimate user rotates their credentials.
            revoke_sudo(request.session)
            return JsonResponse(result)
        except ValueError as exc:
            record_audit(
                "change_my_password_failed",
                actor=request.user,
                target_username=request.user.username,
                payload={"reason": str(exc)},
            )
            return _json_error(str(exc))

    form = ProfilePasswordForm(request.user, request.POST)
    if form.is_valid():
        from ..services import revoke_sudo

        result = change_password_for_user(
            request.user.username,
            form.cleaned_data["old_password"],
            form.cleaned_data["new_password1"],
            current_session_key=str(request.session.session_key or ""),
        )
        user = User.objects.get(pk=request.user.pk)
        update_session_auth_hash(request, user)
        # Same invariant as the JSON branch above: a password rotation
        # must drop any open sudo grant so a stolen sudo'd session does
        # not survive the legitimate user's credential change.
        revoke_sudo(request.session)
        revoked = int(result["revoked_sessions"])
        messages.success(request, f"Contrasena actualizada. Otras sesiones revocadas: {revoked}.")
    else:
        record_audit(
            "change_my_password_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": "validation-error"},
        )
        messages.error(request, _("No se pudo actualizar la contrasena."))
    return redirect("accounts:profile")


def _build_public_base_url(request: HttpRequest) -> str:
    """Shim that keeps the existing import sites working; the canonical
    implementation lives in :mod:`accounts.services` so the email-change
    flow can reuse the same guard without a circular import."""
    from ..services import _build_public_base_url as _impl

    return _impl(request)


@require_http_methods(["GET", "POST"])
def forgot_password_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("/profile/")

    context = {
        "version": __version__,
        "submitted": False,
    }

    if request.method == "POST":
        import random
        import time

        from ..services import LoginThrottled, check_forgot_password_throttle, client_ip

        # Timing-pad: the response body is already identical for found vs
        # not-found, but the SMTP send (when the user exists) takes
        # appreciably longer than the no-op "user not found" branch.
        # That gap is enough to enumerate registered accounts from
        # offsite. Hold every response to at least
        # ``FORGOT_PASSWORD_MIN_RESPONSE_MS`` so the timing channel
        # collapses. Default 1000ms with a tiny jitter to avoid pinning
        # to a single value (which itself would be a fingerprint).
        start = time.monotonic()

        identifier = str(request.POST.get("identifier") or "").strip()
        if not identifier:
            context["form_error"] = "Tipea tu usuario o tu email para pedir el reset."
            return render(request, "accounts/forgot_password.html", context, status=400)
        ip = client_ip(request)
        try:
            check_forgot_password_throttle(ip=ip)
        except LoginThrottled as exc:
            record_audit(
                "password_reset_throttled",
                payload={"ip": ip, "identifier": identifier, "retry_after": exc.retry_after},
            )
            context["form_error"] = str(exc)
            return render(request, "accounts/forgot_password.html", context, status=429)
        # Audit BEFORE delivery so the throttle counts the request even
        # when the user does not exist or SMTP errors out. Without this
        # the IP could spray invalid identifiers for free.
        record_audit(
            "password_reset_requested",
            payload={"ip": ip, "identifier": identifier},
        )
        try:
            request_password_reset(identifier, base_url=_build_public_base_url(request))
        except Exception:  # noqa: BLE001, S110 - never leak sending errors to the form
            pass

        from django.conf import settings as django_settings

        target_ms = int(getattr(django_settings, "FORGOT_PASSWORD_MIN_RESPONSE_MS", 1000))
        if target_ms > 0:
            target = target_ms / 1000.0 + random.uniform(0, 0.08)  # noqa: S311 - timing jitter, not crypto
            elapsed = time.monotonic() - start
            remaining = target - elapsed
            if remaining > 0:
                time.sleep(remaining)

        context["submitted"] = True
        context["identifier_echo"] = identifier
        return render(request, "accounts/forgot_password.html", context)

    return render(request, "accounts/forgot_password.html", context)


@require_http_methods(["GET", "POST"])
def reset_password_view(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("/profile/")

    user = get_user_for_reset_token(uidb64, token)
    context = {
        "version": __version__,
        "uidb64": uidb64,
        "token": token,
        "token_valid": user is not None,
        "target_username": user.username if user else "",
    }

    if user is None:
        return render(request, "accounts/reset_password.html", context, status=400)

    if request.method == "GET":
        return render(request, "accounts/reset_password.html", context)

    new_password = str(request.POST.get("new_password") or "")
    confirm_password = str(request.POST.get("confirm_password") or "")
    if not new_password or new_password != confirm_password:
        context["form_error"] = "La confirmacion no coincide con la nueva contrasena."
        return render(request, "accounts/reset_password.html", context, status=400)

    try:
        complete_password_reset(uidb64, token, new_password)
    except ValueError as exc:
        context["form_error"] = str(exc)
        return render(request, "accounts/reset_password.html", context, status=400)

    messages.success(request, "Contrasena actualizada. Ya podes ingresar con la nueva clave.")
    return redirect("accounts:login")




# ============================ Email change (double-opt-in) ============================
