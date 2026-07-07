"""Login + logout + MFA challenge (post-password verification).

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from ameli_app import __version__

from .. import mfa as mfa_lib
from ..forms import (
    TemplateAuthenticationForm,
)
from ..models import MFAEmailChallenge
from ..services import (
    consume_email_mfa_code,
    consume_recovery_code,
    record_audit,
    send_mfa_email_login_code,
)
from ._common import (
    PENDING_MFA_METHOD_KEY,
    PENDING_MFA_NEXT_KEY,
    PENDING_MFA_SESSION_KEY,
    PENDING_MFA_STARTED_KEY,
    PENDING_MFA_TTL,
    User,
    _json_error,
    logger,
)


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
        # superadmin bootstrap), drop them on the standalone
        # ``/profile/password/`` page so the rest of the profile (MFA
        # enrolment, sessions, audit log) stays hidden until the temp
        # credential is rotated.
        user = getattr(self.request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            return "/profile/password/"
        return self.get_redirect_url() or "/profile/"

    def post(self, request, *args, **kwargs):
        from ..services import AccountLocked, LoginThrottled, check_login_throttle, client_ip

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
            from ..services import maybe_permanently_lock

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
    from ..services import revoke_sudo

    revoke_sudo(request.session)
    auth_logout(request)
    messages.success(request, _("Sesion cerrada."))
    return redirect("dashboard-home")


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

    # Throttle the MFA verification: an attacker with a leaked password
    # holds the pending-MFA session and could otherwise brute-force the
    # 6-digit space (TOTP ~3·10^5 effective with valid_window=1) without
    # any fail-counter consequence. Same sliding-window infra the
    # password step uses — failures on either step share the counter.
    from ..services import (
        AccountLocked,
        LoginThrottled,
        check_login_throttle,
        client_ip,
        record_login_failure,
    )

    ip = client_ip(request)
    try:
        check_login_throttle(username=user.username, ip=ip)
    except (LoginThrottled, AccountLocked) as exc:
        from ..services import maybe_permanently_lock

        record_audit(
            "login_mfa_throttled" if isinstance(exc, LoginThrottled) else "login_mfa_locked_out",
            target_username=user.username,
            payload={"ip": ip, "retry_after": exc.retry_after, "method": method},
        )
        if isinstance(exc, AccountLocked):
            maybe_permanently_lock(user.username)
        context["form_error"] = str(exc)
        return render(request, "accounts/verify_mfa.html", context, status=429)

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
            success = mfa_lib.verify_totp(mfa_lib.decrypt_secret(user.mfa_secret), digits_only)
    if not success:
        if consume_recovery_code(user, candidate):
            success = True
            auth_mode = "recovery"

    if not success:
        record_login_failure(username=user.username, ip=ip)
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
    from ..services import LoginThrottled, check_mfa_resend_throttle, client_ip

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
