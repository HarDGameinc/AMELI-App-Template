from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ameli_app import __version__
from ameli_web.utils import format_timestamp_ui

from . import mfa as mfa_lib
from .forms import (
    AvatarUploadForm,
    ProfilePasswordForm,
    ProfilePreferencesForm,
    TemplateAuthenticationForm,
)
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
    paginate_user_sessions,
    record_audit,
    regenerate_recovery_codes,
    replace_avatar,
    request_password_reset,
    revoke_other_sessions,
    revoke_session_record,
    send_mfa_email_login_code,
    send_profile_test_email,
    serialize_mfa_status,
    serialize_user,
    start_mfa_email_enrollment,
    start_mfa_enrollment,
)

logger = logging.getLogger(__name__)

PENDING_MFA_SESSION_KEY = "pending_mfa_user_id"
PENDING_MFA_STARTED_KEY = "pending_mfa_started_at"
PENDING_MFA_NEXT_KEY = "pending_mfa_next"
PENDING_MFA_METHOD_KEY = "pending_mfa_method"
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
        # When the user must change their password (admin-forced reset,
        # superadmin bootstrap), drop them straight onto the Security tab
        # of the profile page. The middleware will block any other URL
        # anyway, but doing the redirect here gives a smoother UX than
        # making the user land on the General tab and discover the banner.
        user = getattr(self.request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            return "/profile/#profile-tab-security"
        return self.get_redirect_url() or "/profile/"

    def post(self, request, *args, **kwargs):
        from .services import AccountLocked, LoginThrottled, check_login_throttle, client_ip

        username = (request.POST.get("username") or "").strip()
        ip = client_ip(request)
        # Honeypot: the login form ships a hidden ``hp_company`` field
        # that legitimate users never fill in (it's display:none + tab-
        # index=-1 + autocomplete=off). Automated scrapers happily fill
        # every input, so a non-empty value here is a near-certain bot.
        # Refuse with the SAME 200 + bland error the wrong-password
        # branch returns so the bot cannot learn the trap exists.
        if (request.POST.get("hp_company") or "").strip():
            record_audit(
                "login_bot_detected",
                target_username=username or None,
                payload={"ip": ip, "user_agent": request.META.get("HTTP_USER_AGENT", "")[:256]},
            )
            messages.error(
                request,
                "Por favor, introduzca un nombre de usuario y clave correctos. "
                "Observe que ambos campos pueden ser sensibles a mayúsculas.",
            )
            return self.render_to_response(self.get_context_data(form=self.get_form()))
        try:
            check_login_throttle(username=username, ip=ip)
        except (LoginThrottled, AccountLocked) as exc:
            from .services import maybe_permanently_lock

            record_audit(
                "login_throttled" if isinstance(exc, LoginThrottled) else "login_locked_out",
                target_username=username,
                payload={"ip": ip, "retry_after": exc.retry_after},
            )
            # An account that has just been locked-out one more time
            # may have crossed the consecutive-windows threshold; flip
            # ``locked_at`` if it has so the next attempt gets the
            # hard-lock message instead of waiting out the window.
            if isinstance(exc, AccountLocked):
                maybe_permanently_lock(username)
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data(form=self.get_form()))
        return super().post(request, *args, **kwargs)

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
    from .services import revoke_sudo

    revoke_sudo(request.session)
    auth_logout(request)
    messages.success(request, _("Sesion cerrada."))
    return redirect("dashboard-home")


_SESSIONS_PER_PAGE_COOKIE = "ps_sessions_per_page"


def _pending_email_change(user):
    from .services import pending_email_change_for

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
        "can_access_admin": request.user.is_staff,
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
        # Email rotates through the double-opt-in flow exposed at
        # ``/profile/email-change/``; this form is only for display_name
        # and theme. Quietly discard any email value the user may have
        # typed here so a stale UI never bypasses the confirmation flow.
        request.user.display_name = form.cleaned_data["display_name"]
        request.user.theme_preference = form.cleaned_data["theme_preference"]
        request.user.save(update_fields=["display_name", "theme_preference", "updated_at"])
        record_audit(
            "update_my_preferences",
            actor=request.user,
            target_username=request.user.username,
            payload={"theme_preference": request.user.theme_preference},
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
        # SMTP/socket/auth errors land here. Surface them so the operator
        # can debug the email backend without having to dig into the journal.
        logger.exception("test email delivery failed for %s", request.user.username)
        return _json_error(f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502)
    request.session[PROFILE_TEST_EMAIL_SESSION_KEY] = result["sent_at"]
    return JsonResponse(result)


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
        messages.success(request, _("Imagen de perfil actualizada."))
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
    messages.success(request, _("Imagen de perfil eliminada."))
    return redirect("accounts:profile")


@login_required
@require_http_methods(["GET", "POST"])
def change_password_view(request: HttpRequest) -> HttpResponse:
    # ``/profile/password/`` is the submit target of the change form, but
    # any flow that lands here with a GET (a stale bookmark, a ``?next=``
    # bounce after login, the must-change-password middleware) deserves
    # to see the form rather than a bare 405. Send GETs to the profile
    # page with the Security tab focused so the user can complete the
    # change.
    if request.method == "GET":
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
            from .services import revoke_sudo

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
        messages.error(request, _("No se pudo actualizar la contrasena."))
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


@login_required
@require_GET
def admin_session_json(request: HttpRequest) -> JsonResponse:
    payload = {
        "ok": True,
        "enabled": True,
        "authenticated": True,
        "auth_mode": "session",
        "csrf_token": get_token(request),
        "user": serialize_user(request.user),
        "can_access_admin": request.user.is_staff,
    }
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
        result = regenerate_recovery_codes(request.user.username)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session.cycle_key()
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_start_view(request: HttpRequest) -> JsonResponse:
    try:
        result = start_mfa_email_enrollment(request.user.username)
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


def _clear_pending_mfa(request: HttpRequest) -> None:
    for key in (PENDING_MFA_SESSION_KEY, PENDING_MFA_STARTED_KEY, PENDING_MFA_NEXT_KEY, PENDING_MFA_METHOD_KEY):
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
    available_methods = []
    if user.mfa_totp_enabled:
        available_methods.append("totp")
    if user.mfa_email_enabled:
        available_methods.append("email")

    chosen = request.session.get(PENDING_MFA_METHOD_KEY)
    if chosen not in available_methods:
        chosen = None

    if request.method == "POST" and (request.POST.get("choose_method") or "") in available_methods:
        chosen = request.POST["choose_method"]
        request.session[PENDING_MFA_METHOD_KEY] = chosen
        if chosen == "email":
            # The SMTP path can fail for reasons outside the user's
            # control (Errno 101 "Network is unreachable" was observed
            # in dev on a transient connectivity blip to office365).
            # ``verify_mfa_resend_view`` already catches the broad
            # exception and returns 502; this view used to only catch
            # ValueError and 500'd. Mirror the resend handling so the
            # operator sees the audit row and the user still gets a
            # usable page (they can try TOTP or hit "Reenviar codigo").
            try:
                send_mfa_email_login_code(user)
            except ValueError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "login mfa email send failed during choose for %s", user.username,
                )
                record_audit(
                    "mfa_email_login_send_failed",
                    target_username=user.username,
                    payload={"error_class": exc.__class__.__name__, "phase": "choose"},
                )
                messages.error(
                    request,
                    "No pudimos enviar el codigo por email ahora mismo. "
                    "Probá con tu app de autenticacion o tocá 'Reenviar codigo' en unos segundos.",
                )
        return redirect("accounts:verify-mfa")

    if chosen is None and len(available_methods) >= 2:
        return render(
            request,
            "accounts/verify_mfa.html",
            {
                "version": __version__,
                "next_url": next_url,
                "pending_username": user.username,
                "available_methods": available_methods,
                "email_hint": user.email,
                "show_selector": True,
            },
        )

    if chosen is None:
        chosen = available_methods[0] if available_methods else "totp"
    method = chosen
    context = {
        "version": __version__,
        "next_url": next_url,
        "pending_username": user.username,
        "method": method,
        "email_hint": user.email if method == "email" else "",
        "available_methods": available_methods,
        "show_selector": False,
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
                except Exception as exc:  # noqa: BLE001
                    # Same reasoning as the choose-method handler
                    # above: a transient SMTP/network error must not
                    # 500 the page. Audit + flash and keep rendering
                    # so the user can switch to TOTP or retry.
                    logger.exception(
                        "login mfa email send failed on GET for %s", user.username,
                    )
                    record_audit(
                        "mfa_email_login_send_failed",
                        target_username=user.username,
                        payload={"error_class": exc.__class__.__name__, "phase": "render"},
                    )
                    messages.error(
                        request,
                        "No pudimos enviar el codigo por email ahora mismo. "
                        "Probá con tu app de autenticacion o tocá 'Reenviar codigo' en unos segundos.",
                    )
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
    from .services import LoginThrottled, check_mfa_resend_throttle, client_ip

    user = _pending_mfa_user(request)
    if user is None:
        return _json_error("la sesion de ingreso expiro; vuelve a /login/", status=401)
    if not user.mfa_email_enabled:
        return _json_error("el reenvio por email solo aplica al metodo email", status=400)
    ip = client_ip(request)
    try:
        check_mfa_resend_throttle(ip=ip)
    except LoginThrottled as exc:
        record_audit(
            "mfa_email_resend_throttled",
            target_username=user.username,
            payload={"ip": ip, "retry_after": exc.retry_after},
        )
        return _json_error(str(exc), status=429)
    # Audit BEFORE attempting delivery so the throttle counts the attempt
    # even when SMTP errors out: an attacker should not be able to retry
    # for free just because the SMTP path is broken.
    record_audit(
        "mfa_email_resend_requested",
        target_username=user.username,
        payload={"ip": ip},
    )
    try:
        result = send_mfa_email_login_code(user)
    except ValueError as exc:
        return _json_error(str(exc), status=429)
    except Exception as exc:
        logger.exception("login mfa resend delivery failed for %s", user.username)
        return _json_error(f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502)
    return JsonResponse(result)


def _build_public_base_url(request: HttpRequest) -> str:
    """Shim that keeps the existing import sites working; the canonical
    implementation lives in :mod:`accounts.services` so the email-change
    flow can reuse the same guard without a circular import."""
    from .services import _build_public_base_url as _impl

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

        from .services import LoginThrottled, check_forgot_password_throttle, client_ip

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
        except Exception:  # noqa: BLE001 - never leak sending errors to the form
            pass

        from django.conf import settings as django_settings

        target_ms = int(getattr(django_settings, "FORGOT_PASSWORD_MIN_RESPONSE_MS", 1000))
        if target_ms > 0:
            target = target_ms / 1000.0 + random.uniform(0, 0.08)
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


@login_required
@require_POST
def email_change_request_view(request: HttpRequest) -> JsonResponse:
    from .services import client_ip, request_email_change

    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    try:
        result = request_email_change(
            request.user,
            new_email=str(payload.get("new_email") or "").strip(),
            current_password=str(payload.get("current_password") or ""),
            request=request,
            ip=client_ip(request),
        )
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - SMTP layer
        logger.exception("email change request delivery failed for %s", request.user.username)
        return _json_error(
            f"el SMTP rechazo el envio: {exc.__class__.__name__}: {exc}", status=502
        )
    return JsonResponse(result)


@login_required
@require_POST
def email_change_cancel_self_view(request: HttpRequest) -> JsonResponse:
    """Cancel a pending request from inside ``/profile/`` without a token
    (e.g. the user changed their mind in the same browser session)."""
    from .services import EmailChangeRequest, record_audit

    pending = (
        EmailChangeRequest.objects.filter(
            user=request.user, confirmed_at__isnull=True, cancelled_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if pending is None:
        return _json_error("no hay un cambio pendiente", status=404)
    pending.cancelled_at = timezone.now()
    pending.cancel_reason = "user_cancel_in_app"
    pending.save(update_fields=["cancelled_at", "cancel_reason"])
    record_audit(
        "email_change_cancelled",
        actor=request.user,
        target_username=request.user.username,
        payload={"request_id": pending.id, "new_email": pending.new_email, "reason": "in_app"},
    )
    return JsonResponse({"ok": True, "status": "cancelled"})


@require_http_methods(["GET"])
def email_change_confirm_view(request: HttpRequest, request_id: int, token: str) -> HttpResponse:
    """Public endpoint reached from the new-address email. Confirms the
    change and renders a friendly outcome page."""
    from .services import confirm_email_change

    try:
        result = confirm_email_change(request_id=int(request_id), token_plaintext=token)
    except ValueError as exc:
        return render(
            request,
            "accounts/email_change_outcome.html",
            {"ok": False, "message": str(exc), "version": __version__},
            status=400,
        )
    return render(
        request,
        "accounts/email_change_outcome.html",
        {
            "ok": True,
            "title": "Email actualizado",
            "message": f"Tu email ahora es {result['new_email']}.",
            "version": __version__,
        },
    )


@require_http_methods(["GET"])
def email_change_cancel_view(request: HttpRequest, request_id: int, token: str) -> HttpResponse:
    """Public endpoint reached from the OLD-address alert email. Lets the
    legitimate user revert a request they didn't make."""
    from .services import cancel_email_change

    try:
        result = cancel_email_change(
            request_id=int(request_id),
            token_plaintext=token,
            reason="alert_link",
        )
    except ValueError as exc:
        return render(
            request,
            "accounts/email_change_outcome.html",
            {"ok": False, "message": str(exc), "version": __version__},
            status=400,
        )
    return render(
        request,
        "accounts/email_change_outcome.html",
        {
            "ok": True,
            "title": "Pedido cancelado",
            "message": f"El cambio a {result['new_email']} no se aplico. Si vos no pediste el cambio, considera cambiar tu contrasena.",
            "version": __version__,
        },
    )
