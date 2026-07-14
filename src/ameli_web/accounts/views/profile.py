"""Profile page + preferences + avatars + test email.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ameli_app import __version__
from ameli_web.utils import format_timestamp_ui

from ..forms import (
    AvatarUploadForm,
    ProfilePasswordForm,
    ProfilePreferencesForm,
)
from ..permissions import can_access_admin_panel, is_superadmin
from ..services import (
    delete_avatar,
    paginate_user_sessions,
    record_audit,
    replace_avatar,
    send_profile_test_email,
    serialize_mfa_status,
    serialize_user,
)
from ._common import (
    _expects_json,
    _json_body,
    _json_error,
    logger,
)

_SESSIONS_PER_PAGE_COOKIE = "ps_sessions_per_page"


def _pending_email_change(user):
    from ..services import pending_email_change_for

    return pending_email_change_for(user)


def _security_alerts_for(user) -> list[dict]:
    """Build the per-user list of security todos shown at the top of
    ``/profile/``. The intent is a checklist — not a deep audit — so
    each item points at the tab where the user can fix it.

    Today: MFA not enrolled, no email on file (no password recovery
    possible), and a password older than 90 days (default; configurable).
    """
    from django.conf import settings as django_settings

    alerts: list[dict] = []
    if not getattr(user, "mfa_enabled", False):
        alerts.append({
            "icon": "shield_lock",
            "title": "2FA no activado",
            "detail": (
                "Tu cuenta solo necesita la contrasena para entrar. Activa "
                "la app de autenticacion o el codigo por email para una "
                "segunda capa de seguridad."
            ),
            "action_label": "Activar",
            "action_tab": "profile-tab-security",
        })
    if not (user.email or "").strip():
        alerts.append({
            "icon": "alternate_email",
            "title": "Sin email registrado",
            "detail": (
                "Si olvidas tu contrasena no podemos enviarte el enlace de "
                "recuperacion. Registra una direccion en la tarjeta de email."
            ),
            "action_label": "Agregar",
            "action_tab": "profile-tab-security",
        })
    # Password age — defaults to 90 days; operator can extend via the
    # PROFILE_PASSWORD_MAX_AGE_DAYS setting.
    max_age = int(getattr(django_settings, "PROFILE_PASSWORD_MAX_AGE_DAYS", 90))
    last_change = getattr(user, "password_changed_at", None) or user.date_joined
    if max_age > 0 and last_change is not None:
        age_days = (timezone.now() - last_change).days
        if age_days > max_age:
            alerts.append({
                "icon": "schedule",
                "title": f"Tu contrasena tiene {age_days} dias",
                "detail": (
                    f"Recomendamos rotarla cada {max_age} dias. Las claves "
                    "muy viejas tienen mas chance de haber sido filtradas."
                ),
                "action_label": "Cambiar",
                "action_tab": "profile-tab-security",
            })
    return alerts


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    from ameli_web.pagination import coerce_page, persist_per_page_cookie, resolve_per_page

    current_session_key = str(request.session.session_key or "")
    user_payload = serialize_user(request.user)
    per_page = resolve_per_page(request, _SESSIONS_PER_PAGE_COOKIE, default=20, query_param="sessions_per_page")
    sessions_page = paginate_user_sessions(
        request.user,
        page=coerce_page(request.GET.get("sessions_page")),
        per_page=per_page,
        current_session_key=current_session_key,
    )
    current_session = next(
        (item for item in sessions_page.items if item.get("session_key") == current_session_key),
        {"session_id": current_session_key, "session_key": current_session_key},
    )
    context = {
        "version": __version__,
        "current_user": user_payload,
        "can_access_admin": can_access_admin_panel(request.user),
        "current_session": current_session,
        "user_sessions": sessions_page.items,
        "session_pagination": sessions_page.as_context(
            page_param="sessions_page",
            anchor="profile-tab-sessions",
            per_page_param="sessions_per_page",
        ),
        "preferences_form": ProfilePreferencesForm(instance=request.user),
        "avatar_form": AvatarUploadForm(),
        "password_form": ProfilePasswordForm(request.user),
        "security_alerts": _security_alerts_for(request.user),
        "mfa_status": serialize_mfa_status(request.user),
        "pending_email_change": _pending_email_change(request.user),
        "display_last_login_at": format_timestamp_ui(request.user.last_login),
        "csrf_token": get_token(request),
    }
    # Only honor ``?partial=`` for real fetch requests; on a refresh the
    # browser does not send our ``X-Requested-With`` marker, so we fall
    # back to the full page and the user does not see the partial without
    # layout or css.
    is_fetch = request.headers.get("X-Requested-With", "").lower() in {"fetch", "xmlhttprequest"}
    partial = (request.GET.get("partial") or "").strip() if is_fetch else ""
    if partial == "sessions":
        response = render(request, "accounts/_sessions_panel.html", context)
    else:
        response = render(request, "accounts/profile.html", context)
    persist_per_page_cookie(response, request, _SESSIONS_PER_PAGE_COOKIE, query_param="sessions_per_page")
    return response


@login_required
def update_preferences(request: HttpRequest) -> HttpResponse:
    if request.method not in {"POST", "PATCH"}:
        return _json_error("method not allowed", status=405)
    if request.method == "PATCH" or _expects_json(request):
        try:
            payload = _json_body(request)
        except ValueError as exc:
            return _json_error(str(exc))
        # Length cap mirrors the ``CharField(max_length=80)`` on the User
        # model. Without it the JSON branch bypassed the form layer's
        # validation and let arbitrarily large strings hit the ORM —
        # Postgres rejects with 500, SQLite truncates silently.
        request.user.display_name = str(payload.get("display_name") or "").strip()[:80]
        theme_preference = str(payload.get("theme_preference") or request.user.theme_preference).strip()
        if theme_preference in {"auto", "light", "dark"}:
            request.user.theme_preference = theme_preference
        color_theme = str(payload.get("color_theme") or request.user.color_theme).strip()
        if color_theme in {"teal", "indigo", "amber", "violet"}:
            request.user.color_theme = color_theme
        request.user.save(
            update_fields=["display_name", "theme_preference", "color_theme", "updated_at"]
        )
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={
                "theme_preference": request.user.theme_preference,
                "color_theme": request.user.color_theme,
            },
        )
        return JsonResponse({"ok": True, "status": "updated", "user": serialize_user(request.user)})

    form = ProfilePreferencesForm(request.POST, instance=request.user)
    if form.is_valid():
        request.user.display_name = form.cleaned_data["display_name"]
        request.user.theme_preference = form.cleaned_data["theme_preference"]
        request.user.color_theme = form.cleaned_data["color_theme"]
        request.user.save(
            update_fields=["display_name", "theme_preference", "color_theme", "updated_at"]
        )
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={
                "theme_preference": request.user.theme_preference,
                "color_theme": request.user.color_theme,
            },
        )
        messages.success(request, _("Perfil actualizado."))
    else:
        messages.error(request, _("No se pudo guardar el perfil."))
    return redirect("accounts:profile")


PROFILE_TEST_EMAIL_SESSION_KEY = "profile_test_email_last_sent"


@login_required
@require_POST
def send_profile_test_email_view(request: HttpRequest) -> JsonResponse:
    raw = request.session.get(PROFILE_TEST_EMAIL_SESSION_KEY)
    last_sent_at = None
    if raw:
        try:
            last_sent_at = datetime.fromisoformat(str(raw))
        except ValueError:
            last_sent_at = None
    try:
        result = send_profile_test_email(request.user, last_sent_at=last_sent_at)
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        # SMTP/socket/auth errors land here. Surfacing the backend detail is a
        # deliberate operator affordance (debug the mail backend without
        # digging into the journal) — but this view is only ``@login_required``,
        # NOT superadmin-gated, so echoing it to everyone leaked mail-host
        # names and auth/TLS failures to any authenticated user. Keep the
        # affordance for superadmins (who already hold full access) and give
        # everyone else a generic message; the traceback is in the journal
        # either way. (CodeQL py/stack-trace-exposure, 2026-07-14.)
        logger.exception("test email delivery failed for %s", request.user.username)
        if is_superadmin(request.user):
            return _json_error(
                f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502
            )
        return _json_error(
            "no pudimos enviar el email de prueba; reintenta en unos minutos",
            status=502,
        )
    request.session[PROFILE_TEST_EMAIL_SESSION_KEY] = result["sent_at"]
    return JsonResponse(result)


@login_required
@require_POST
def update_avatar(request: HttpRequest) -> HttpResponse:
    form = AvatarUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = [error for group in form.errors.values() for error in group]
        if _expects_json(request):
            return _json_error("; ".join(errors) if errors else "No se pudo actualizar la imagen.")
        for error in errors:
            messages.error(request, error)
        return redirect("accounts:profile")

    avatar_file = form.cleaned_data["avatar"]

    # ASVS V12.4.1 — antivirus scan when the operator has configured
    # ``AMELI_APP_AV_ENDPOINT``. Unset → "disabled" → skip. INFECTED
    # → reject + audit. ``check_failed`` (endpoint unreachable / bad
    # response / timeout) → audit ``avatar_upload_av_check_failed``
    # but PROCEED with the upload (fail-open policy, mirrors HIBP
    # validator behaviour). Reading file.read() consumes the cursor,
    # so we seek back to 0 before handing the file off to
    # ``replace_avatar``.
    from django.conf import settings as django_settings

    from ameli_web.accounts import av

    av_endpoint = getattr(django_settings, "AV_ENDPOINT", "") or ""
    if av_endpoint:
        try:
            avatar_file.file.seek(0)
        except Exception:  # noqa: BLE001, S110 — best-effort, some streams aren't seekable
            pass
        scan_data = avatar_file.file.read()
        try:
            avatar_file.file.seek(0)
        except Exception:  # noqa: BLE001, S110
            pass
        verdict, detail = av.scan_bytes(scan_data, av_endpoint)
        if verdict == "infected":
            record_audit(
                "avatar_upload_av_rejected",
                actor=request.user,
                target_username=request.user.username,
                payload={"signature": detail, "endpoint_scheme": av_endpoint.split("://")[0]},
            )
            error_msg = "La imagen fue rechazada por el escaner antivirus."
            if _expects_json(request):
                return _json_error(error_msg)
            messages.error(request, error_msg)
            return redirect("accounts:profile")
        if verdict == "check_failed":
            # Fail-open with audit visibility: the upload proceeds, but
            # the operator sees the scan outage in the audit chain.
            record_audit(
                "avatar_upload_av_check_failed",
                actor=request.user,
                target_username=request.user.username,
                payload={"reason": detail, "endpoint_scheme": av_endpoint.split("://")[0]},
            )

    replace_avatar(request.user, avatar_file)
    record_audit(
        "update_my_preferences",
        actor=request.user,
        target_username=request.user.username,
        payload={"avatar_updated": True},
    )
    if _expects_json(request):
        return JsonResponse({"ok": True, "status": "updated", "user": serialize_user(request.user)})
    messages.success(request, _("Imagen de perfil actualizada."))
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
    messages.success(request, _("Imagen de perfil eliminada."))
    return redirect("accounts:profile")
