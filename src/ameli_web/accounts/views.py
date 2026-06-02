from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ameli_app import __version__
from ameli_web.utils import format_timestamp_ui

from .forms import AvatarUploadForm, ProfilePasswordForm, ProfilePreferencesForm, TemplateAuthenticationForm
from .models import UserSession
from .services import (
    change_password_for_user,
    delete_avatar,
    list_user_sessions,
    record_audit,
    replace_avatar,
    revoke_other_sessions,
    revoke_session_record,
    serialize_user,
)

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
