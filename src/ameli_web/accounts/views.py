from __future__ import annotations

import json

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ameli_app import __version__
from ameli_web.utils import format_timestamp_ui

from . import mfa as mfa_lib
from .forms import AvatarUploadForm, ProfilePasswordForm, ProfilePreferencesForm, TemplateAuthenticationForm
from .models import MFAEmailChallenge, UserSession
from .services import (
    change_password_for_user,
    complete_password_reset,
    confirm_mfa_email_enrollment,
    confirm_mfa_enrollment,
    consume_email_mfa_code,
    consume_recovery_code,
    delete_avatar,
    disable_mfa_email_for_self,
    disable_mfa_for_self,
    disable_mfa_totp_for_self,
    get_user_for_reset_token,
    list_user_sessions,
    record_audit,
    regenerate_recovery_codes,
    replace_avatar,
    request_password_reset,
    revoke_other_sessions,
    revoke_session_record,
    send_mfa_email_login_code,
    serialize_mfa_status,
    serialize_user,
    start_mfa_email_enrollment,
    start_mfa_enrollment,
)

PENDING_MFA_SESSION_KEY = "pending_mfa_user_id"
PENDING_MFA_STARTED_KEY = "pending_mfa_started_at"
PENDING_MFA_NEXT_KEY = "pending_mfa_next"
PENDING_MFA_TTL = timedelta(minutes=10)

User = get_user_model()


def _expects_json(request: HttpRequest) -> bool:
    content_type = request.headers.get("Content-Type", "")
    accept = request.headers.get("Accept", "")
    return (
        "application/json" in content_type
        or "application/json" in accept
        or bool(request.headers.get("X-CSRF-Token"))
    )


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json body") from exc


class TemplateLoginView(LoginView):
    authentication_form = TemplateAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["version"] = __version__
        return context

    def get_success_url(self):
        return self.get_redirect_url() or "/profile/"

    def form_valid(self, form):
        user = form.get_user()
        if getattr(user, "mfa_enabled", False):
            # Hold off on auth_login. The login is only completed once the
            # second factor is verified at /login/verify-mfa/.
            self.request.session[PENDING_MFA_SESSION_KEY] = user.pk
            self.request.session[PENDING_MFA_STARTED_KEY] = timezone.now().isoformat()
            self.request.session[PENDING_MFA_NEXT_KEY] = self.get_success_url()
            record_audit(
                "login_mfa_required",
                actor=user,
                target_username=user.username,
                payload={"path": "/login/"},
            )
            return redirect("accounts:verify-mfa")
        return super().form_valid(form)


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    messages.success(request, "Sesion cerrada.")
    return redirect("dashboard-home")


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    current_session_key = str(request.session.session_key or "")
    user_payload = serialize_user(request.user)
    user_sessions = list_user_sessions(request.user, current_session_key=current_session_key)
    context = {
        "version": __version__,
        "current_user": user_payload,
        "can_access_admin": request.user.is_staff,
        "current_session": next(
            (item for item in user_sessions if item.get("session_key") == current_session_key),
            {"session_id": current_session_key, "session_key": current_session_key},
        ),
        "user_sessions": user_sessions,
        "preferences_form": ProfilePreferencesForm(instance=request.user),
        "avatar_form": AvatarUploadForm(),
        "password_form": ProfilePasswordForm(request.user),
        "mfa_status": serialize_mfa_status(request.user),
        "display_last_login_at": format_timestamp_ui(request.user.last_login),
        "csrf_token": get_token(request),
    }
    return render(request, "accounts/profile.html", context)


@login_required
def update_preferences(request: HttpRequest) -> HttpResponse:
    if request.method not in {"POST", "PATCH"}:
        return _json_error("method not allowed", status=405)
    if request.method == "PATCH" or _expects_json(request):
        try:
            payload = _json_body(request)
        except ValueError as exc:
            return _json_error(str(exc))
        request.user.display_name = str(payload.get("display_name") or "").strip()
        theme_preference = str(payload.get("theme_preference") or request.user.theme_preference).strip()
        if theme_preference in {"auto", "light", "dark"}:
            request.user.theme_preference = theme_preference
        request.user.save(update_fields=["display_name", "theme_preference", "updated_at"])
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={"theme_preference": request.user.theme_preference},
        )
        return JsonResponse({"ok": True, "status": "updated", "user": serialize_user(request.user)})

    form = ProfilePreferencesForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={"theme_preference": request.user.theme_preference},
        )
        messages.success(request, "Perfil actualizado.")
    else:
        messages.error(request, "No se pudo guardar el perfil.")
    return redirect("accounts:profile")


@login_required
@require_POST
def update_avatar(request: HttpRequest) -> HttpResponse:
    form = AvatarUploadForm(request.POST, request.FILES)
    if form.is_valid():
        replace_avatar(request.user, form.cleaned_data["avatar"])
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={"avatar_updated": True},
        )
        if _expects_json(request):
            return JsonResponse({"ok": True, "status": "updated", "user": serialize_user(request.user)})
        messages.success(request, "Imagen de perfil actualizada.")
    else:
        errors = [error for group in form.errors.values() for error in group]
        if _expects_json(request):
            return _json_error("; ".join(errors) if errors else "No se pudo actualizar la imagen.")
        for error in errors:
            messages.error(request, error)
    return redirect("accounts:profile")


@login_required
@require_POST
def delete_avatar_view(request: HttpRequest) -> HttpResponse:
    delete_avatar(request.user)
    record_audit(
        "update_my_preferences",
        actor=request.user,
        target_username=request.user.username,
        payload={"avatar_updated": False},
    )
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "user": serialize_user(request.user)})
    messages.success(request, "Imagen de perfil eliminada.")
    return redirect("accounts:profile")


@login_required
@require_POST
def change_password_view(request: HttpRequest) -> HttpResponse:
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
            result = change_password_for_user(
                request.user.username,
                current_password,
                new_password,
                current_session_key=str(request.session.session_key or ""),
            )
            user = User.objects.get(pk=request.user.pk)
            update_session_auth_hash(request, user)
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
        result = change_password_for_user(
            request.user.username,
            form.cleaned_data["old_password"],
            form.cleaned_data["new_password1"],
            current_session_key=str(request.session.session_key or ""),
        )
        user = User.objects.get(pk=request.user.pk)
        update_session_auth_hash(request, user)
        revoked = int(result["revoked_sessions"])
        messages.success(request, f"Contrasena actualizada. Otras sesiones revocadas: {revoked}.")
    else:
        record_audit(
            "change_my_password_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": "validation-error"},
        )
        messages.error(request, "No se pudo actualizar la contrasena.")
    return redirect("accounts:profile")


@login_required
@require_POST
def revoke_other_sessions_view(request: HttpRequest) -> HttpResponse:
    revoked = revoke_other_sessions(request.user, current_session_key=str(request.session.session_key or ""))
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "revoked_sessions": revoked})
    messages.success(request, f"Se revocaron {revoked} sesiones.")
    return redirect("accounts:profile")


@login_required
@require_POST
def revoke_session_view(request: HttpRequest, session_key: str) -> HttpResponse:
    session_record = get_object_or_404(UserSession, user=request.user, session_key=session_key)
    if session_record.session_key == str(request.session.session_key or ""):
        if _expects_json(request):
            return _json_error("cannot revoke current session")
        messages.error(request, "No puedes revocar la sesion que estas usando ahora.")
        return redirect("accounts:profile")
    revoke_session_record(session_record, actor=request.user, reason="manual-revoke")
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "session_key": session_key})
    messages.success(request, "Sesion revocada.")
    return redirect("accounts:profile")


def admin_session_json(request: HttpRequest) -> JsonResponse:
    payload = {
        "ok": True,
        "enabled": True,
        "authenticated": request.user.is_authenticated,
        "auth_mode": "session" if request.user.is_authenticated else None,
        "csrf_token": get_token(request),
    }
    if request.user.is_authenticated:
        payload["user"] = serialize_user(request.user)
        payload["can_access_admin"] = request.user.is_staff
    return JsonResponse(payload)


@login_required
@require_POST
def mfa_start_view(request: HttpRequest) -> JsonResponse:
    try:
        result = start_mfa_enrollment(request.user.username)
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
    return JsonResponse(result)


@login_required
@require_POST
def mfa_regenerate_view(request: HttpRequest) -> JsonResponse:
    try:
        result = regenerate_recovery_codes(request.user.username)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_start_view(request: HttpRequest) -> JsonResponse:
    try:
        result = start_mfa_email_enrollment(request.user.username)
    except ValueError as exc:
        return _json_error(str(exc))
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
    return JsonResponse(result)


def _clear_pending_mfa(request: HttpRequest) -> None:
    for key in (PENDING_MFA_SESSION_KEY, PENDING_MFA_STARTED_KEY, PENDING_MFA_NEXT_KEY):
        request.session.pop(key, None)


def _pending_mfa_user(request: HttpRequest):
    user_id = request.session.get(PENDING_MFA_SESSION_KEY)
    started = request.session.get(PENDING_MFA_STARTED_KEY)
    if not user_id or not started:
        return None
    try:
        started_at = datetime.fromisoformat(str(started))
    except ValueError:
        return None
    if timezone.now() - started_at > PENDING_MFA_TTL:
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


@require_http_methods(["GET", "POST"])
def verify_mfa_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        # Already fully signed in. Drop any stale pending state and send
        # them on their way so this view never short-circuits an existing
        # session into someone else's account.
        _clear_pending_mfa(request)
        return redirect("/profile/")

    user = _pending_mfa_user(request)
    if user is None:
        _clear_pending_mfa(request)
        messages.error(request, "La sesion de ingreso expiro. Vuelve a tipear usuario y contrasena.")
        return redirect("accounts:login")

    next_url = request.session.get(PENDING_MFA_NEXT_KEY) or "/profile/"
    # Commit 4 of the stacked refactor will let the user pick between
    # available methods. For now, prefer TOTP when present (industry
    # primary) and fall back to email.
    if user.mfa_totp_enabled:
        method = "totp"
    elif user.mfa_email_enabled:
        method = "email"
    else:
        method = "totp"
    context = {
        "version": __version__,
        "next_url": next_url,
        "pending_username": user.username,
        "method": method,
        "email_hint": user.email if method == "email" else "",
    }

    if request.method == "GET":
        if method == "email":
            has_pending = MFAEmailChallenge.objects.filter(
                user=user,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).exists()
            if not has_pending:
                try:
                    send_mfa_email_login_code(user)
                except ValueError:
                    # Rate-limited at this very moment; user can hit
                    # "Reenviar codigo" once the cooldown expires.
                    pass
        return render(request, "accounts/verify_mfa.html", context)

    candidate = str(request.POST.get("code") or "").strip()
    if not candidate:
        context["form_error"] = "Tipea el codigo o un codigo de recuperacion."
        return render(request, "accounts/verify_mfa.html", context, status=400)

    digits_only = candidate.replace(" ", "")
    success = False
    auth_mode = method

    if digits_only.isdigit() and len(digits_only) == 6:
        if method == "email":
            success = consume_email_mfa_code(user, digits_only)
        else:
            success = mfa_lib.verify_totp(user.mfa_secret, digits_only)
    if not success:
        if consume_recovery_code(user, candidate):
            success = True
            auth_mode = "recovery"

    if not success:
        record_audit(
            "login_mfa_failed",
            actor=user,
            target_username=user.username,
            payload={"reason": "invalid-code", "method": method},
        )
        context["form_error"] = "Codigo invalido. Intenta de nuevo."
        return render(request, "accounts/verify_mfa.html", context, status=400)

    _clear_pending_mfa(request)
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    record_audit(
        "login_mfa_success",
        actor=user,
        target_username=user.username,
        payload={"auth_mode": auth_mode},
    )
    return redirect(next_url)


@require_POST
def verify_mfa_resend_view(request: HttpRequest) -> JsonResponse:
    user = _pending_mfa_user(request)
    if user is None:
        return _json_error("la sesion de ingreso expiro; vuelve a /login/", status=401)
    if not user.mfa_email_enabled:
        return _json_error("el reenvio por email solo aplica al metodo email", status=400)
    try:
        result = send_mfa_email_login_code(user)
    except ValueError as exc:
        return _json_error(str(exc), status=429)
    return JsonResponse(result)


def _build_public_base_url(request: HttpRequest) -> str:
    configured = getattr(getattr(settings, "CFG", None), "public_url_base", "")
    if configured:
        return configured.rstrip("/")
    absolute = request.build_absolute_uri("/")
    return absolute.rstrip("/")


@require_http_methods(["GET", "POST"])
def forgot_password_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("/profile/")

    context = {
        "version": __version__,
        "submitted": False,
    }

    if request.method == "POST":
        identifier = str(request.POST.get("identifier") or "").strip()
        if not identifier:
            context["form_error"] = "Tipea tu usuario o tu email para pedir el reset."
            return render(request, "accounts/forgot_password.html", context, status=400)
        try:
            request_password_reset(identifier, base_url=_build_public_base_url(request))
        except Exception:  # noqa: BLE001 - never leak sending errors to the form
            pass
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
