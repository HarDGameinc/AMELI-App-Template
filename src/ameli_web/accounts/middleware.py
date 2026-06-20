from __future__ import annotations

import secrets

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

from .permissions import can_access_admin_panel, is_authenticated, is_superadmin
from .services import record_audit, sync_request_session


def _generate_csp_nonce() -> str:
    """16 random bytes, url-safe base64. ~22 chars, enough entropy that
    an attacker cannot guess it inside a single request lifetime."""
    return secrets.token_urlsafe(16)


def build_csp(nonce: str) -> str:
    """Render the project-wide CSP with a per-request nonce baked in.

    The nonce replaces ``'unsafe-inline'`` in **script-src** so a future
    XSS reflected into one of our templates cannot execute — an attacker
    can inject the markup but not the matching nonce only known to the
    server for this response.

    ``style-src`` keeps ``'unsafe-inline'`` because every layout
    template still relies on inline ``style=""`` attributes; rewriting
    them all would be a giant refactor for marginal value. Inline
    styles cannot execute JavaScript, so the residual risk is cosmetic
    (an attacker could rewrite layout, never run code).
    """
    return (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def _django_admin_csp() -> str:
    """Looser CSP applied only to ``/django-admin/*``.

    The Django admin ships inline scripts that we cannot stamp with our
    nonce (it's framework code). Without the relaxation theme toggles,
    autocompletes and sortables silently break. The admin is already
    behind sudo + MFA + audit, and only the operator ever visits it,
    so the marginal XSS risk here is the small price for keeping the
    rest of the site under the strict nonce-based policy.
    """
    return (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


# Modern browsers honour a small fleet of process-isolation headers that
# defend against speculative execution side-channels (Spectre, Meltdown
# variants) and against being grouped in the same browsing context group
# as an attacker page. The values below are safe for an internal app
# that never embeds third-party iframes and never wants to be embedded.
#
# Permissions-Policy turns off feature interfaces we never use, so a
# future XSS-injected snippet cannot probe the user's microphone,
# geolocation, etc.

_PERMISSIONS_POLICY = (
    "accelerometer=(),"
    "camera=(),"
    "geolocation=(),"
    "gyroscope=(),"
    "magnetometer=(),"
    "microphone=(),"
    "payment=(),"
    "usb=(),"
    "interest-cohort=()"
)


class SecurityHeadersMiddleware:
    """Attach the project-wide CSP and a couple of supporting headers.

    Django already sets ``X-Content-Type-Options`` and
    ``Referrer-Policy`` from ``SECURE_*`` settings; CSP needs a custom
    middleware. We keep this in-app to avoid adding ``django-csp``.

    We mint a fresh ``csp_nonce`` per request, stash it on the request
    object so the context processor can hand it to every template, and
    bake it into the CSP header before the response leaves. The same
    middleware also adds the modern cross-origin isolation trio
    (COOP/CORP) and a strict ``Permissions-Policy``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = _generate_csp_nonce()
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            if request.path.startswith("/django-admin/"):
                response["Content-Security-Policy"] = _django_admin_csp()
            else:
                response["Content-Security-Policy"] = build_csp(request.csp_nonce)
        # Best-effort: if the response already declares one of these, do
        # not overwrite (some specialised endpoints — e.g. docs — may
        # need their own value).
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = _PERMISSIONS_POLICY
        if "Cross-Origin-Opener-Policy" not in response:
            response["Cross-Origin-Opener-Policy"] = "same-origin"
        if "Cross-Origin-Resource-Policy" not in response:
            response["Cross-Origin-Resource-Policy"] = "same-origin"
        # ASVS V8.2: authenticated responses must not be cached on shared
        # intermediaries (CDN, corporate proxy, browser back-button after
        # logout). We only stamp the header when the response did not
        # already declare an explicit Cache-Control, so cacheable assets
        # served behind login (e.g. an export the operator marked public)
        # can still opt in.
        user = getattr(request, "user", None)
        if (
            user is not None
            and getattr(user, "is_authenticated", False)
            and "Cache-Control" not in response
        ):
            response["Cache-Control"] = "no-store, max-age=0"
            if "Pragma" not in response:
                response["Pragma"] = "no-cache"
        return response


class UserSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            # An admin can disable a user while their session is still
            # active. Force a logout the moment a disabled user comes back.
            if not request.user.is_active:
                from django.contrib.auth import logout as auth_logout

                auth_logout(request)
                messages.warning(
                    request,
                    "Tu cuenta esta deshabilitada. Contacta al administrador.",
                )
                return redirect("accounts:login")
            session_record = sync_request_session(request)
            if session_record is not None and session_record.revoked_at is not None:
                messages.warning(request, "Tu sesión fue revocada y necesitas iniciar sesión de nuevo.")
                return redirect("accounts:login")
            # ASVS V3.3.3 absolute session ceiling: a session that has
            # lived past ``SESSION_ABSOLUTE_MAX_AGE_SECONDS`` (measured
            # from ``UserSession.created_at``, the original login moment)
            # is forced to re-authenticate even with continuous activity.
            # ``SESSION_COOKIE_AGE`` covers idle timeout — this covers
            # absolute timeout.
            #
            # The ceiling check runs after ``sync_request_session`` so we
            # are guaranteed a session_record. Settings = 0 disables the
            # ceiling for back-compat with deploys that have never
            # enforced this.
            if session_record is not None:
                from django.conf import settings as django_settings

                max_age = int(getattr(django_settings, "SESSION_ABSOLUTE_MAX_AGE_SECONDS", 0) or 0)
                if max_age > 0:
                    from django.utils import timezone

                    age = (timezone.now() - session_record.created_at).total_seconds()
                    if age >= max_age:
                        from django.contrib.auth import logout as auth_logout

                        # Audit BEFORE logout so the row is attributed to
                        # the user whose session we're about to terminate.
                        username = request.user.username
                        record_audit(
                            "session_expired_absolute",
                            actor=request.user,
                            target_username=username,
                            payload={
                                "session_key": session_record.session_key,
                                "session_age_seconds": int(age),
                                "max_age_seconds": max_age,
                            },
                        )
                        auth_logout(request)
                        messages.warning(
                            request,
                            "Tu sesión expiró por política de seguridad. "
                            "Vuelve a iniciar sesión.",
                        )
                        return redirect("accounts:login")
        return self.get_response(request)


class MustChangePasswordMiddleware:
    """Force a password change before the user can interact with the app.

    The ``must_change_password`` flag is set by the admin reset flow and by
    the superadmin bootstrap. Without this middleware the flag is only a UI
    hint: the user keeps full access (profile edits, MFA enrollment, admin
    actions) while still holding the temporary password the admin chose.

    Any request from a flagged user is redirected to the password change
    page, except for the routes needed to actually change the password,
    sign out, fetch static/media assets, or hit the public health endpoints.
    """

    # Path prefixes (or exact paths) that must stay reachable while the
    # flag is on. The password change endpoint is here so the user can
    # actually clear the flag; everything else is closed.
    # ``/profile/`` itself is allowed so the user can land on a page that
    # contains the password change form. Other POSTs (preferences, avatar,
    # MFA, sessions) live under distinct paths and stay closed.
    _ALLOWED_EXACT = {
        "/profile/",
        "/profile",
        "/profile/password/",
        "/profile/password",
        "/profile/change-password",
        "/logout/",
        "/logout",
        "/health",
        "/api/health",
    }
    _ALLOWED_PREFIXES = ("/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not self._path_is_allowed(request.path)
        ):
            messages.warning(
                request,
                "Debes cambiar tu contrasena antes de continuar usando la aplicacion.",
            )
            # ``/profile/password/`` is the POST-only submit endpoint; the
            # form itself lives inside the Security tab of ``/profile/``,
            # so we send the user there and use the URL fragment to focus
            # the right tab on arrival.
            return redirect("/profile/#profile-tab-security")
        return self.get_response(request)

    @classmethod
    def _path_is_allowed(cls, path: str) -> bool:
        if path in cls._ALLOWED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in cls._ALLOWED_PREFIXES)


class AdminAccessAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/admin") and is_authenticated(request.user) and not can_access_admin_panel(request.user):
            record_audit(
                "admin_access_denied",
                actor=request.user,
                target_username="admin",
                payload={"path": path, "auth_mode": "session"},
            )
            messages.warning(request, "Tu cuenta no tiene permisos para acceder al panel de administración.")
            return redirect("accounts:profile")
        return self.get_response(request)


class DjangoAdminSudoGateMiddleware:
    """Require an active sudo grant to reach Django's native ``/django-admin/``.

    The native admin is extremely powerful: a stolen superadmin cookie
    bypasses every business-logic check there. Our own ``/admin/`` panel
    already runs every write behind ``@sudo_required``; this middleware
    extends that protection to the framework's admin, which we expose
    so operators can use the rich filtering and inline editing it
    provides without giving up the re-auth gate.

    Unauthenticated users fall through so Django's own login wall keeps
    firing. Non-staff users fall through and the admin returns a 403 by
    itself. Only the staff-without-sudo case is short-circuited here.
    """

    _PREFIX = "/django-admin/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self._PREFIX):
            return self.get_response(request)
        user = getattr(request, "user", None)
        if not is_superadmin(user):
            return self.get_response(request)
        # ``is_superadmin`` returned True ⇒ user is a real authenticated
        # User row (not None, not AnonymousUser). mypy doesn't see this
        # narrowing because is_superadmin returns bool, not TypeGuard.
        assert user is not None  # noqa: S101 - type narrowing after is_superadmin gate
        from .services import session_in_sudo

        if session_in_sudo(request.session):
            return self.get_response(request)
        record_audit(
            "django_admin_blocked_no_sudo",
            actor=user,
            target_username=user.username,
            payload={"path": request.path},
        )
        messages.warning(
            request,
            "Para entrar al admin nativo necesitas re-autenticarte. Usa el boton 'Admin nativo Django' del panel.",
        )
        return redirect("/admin/")


class MaintenanceModeMiddleware:
    """Surface the maintenance flag to templates; 503 writes when active.

    GET/HEAD requests pass through so visitors can still read the app
    during a planned window. Writes (POST/PUT/PATCH/DELETE) are blocked
    with HTTP 503 unless the requesting user is staff — operators need
    to stay able to flip the flag back off and to keep using the admin.

    Paths under the operational allowlist (``/health``, ``/admin/``,
    ``/login/``, ``/logout/``) are never blocked so the loadbalancer
    health probe and the operator's own login don't get tarpit'd.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    # ``/profile/password/`` stays open during read-only maintenance: a
    # user forced into a rotation (``must_change_password=True``) would
    # otherwise be bounced between the must-change redirect and a 503,
    # with no way out until the operator disables the window. The
    # email-change confirm/cancel endpoints are the legitimate way to
    # back out of a pending change started before the window and are
    # safe to keep reachable too.
    BYPASS_PREFIXES = (
        "/health", "/api/health", "/admin/", "/django-admin/",
        "/login/", "/logout/", "/static/", "/media/",
        "/profile/password/", "/profile/email-change/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def _state(self):
        # Lazy import + swallow errors so a broken DB / unmigrated
        # install never bricks the request pipeline. Without this
        # guard the very first migrate would fail because the
        # middleware tries to read a table that doesn't exist yet.
        try:
            from .services import get_maintenance_state

            return get_maintenance_state()
        except Exception:  # noqa: BLE001
            return {"active": False, "read_only": True, "message": ""}

    def __call__(self, request):
        state = self._state()
        request.maintenance_state = state
        if not state.get("active"):
            return self.get_response(request)
        if request.method in self.SAFE_METHODS:
            return self.get_response(request)
        if not state.get("read_only"):
            return self.get_response(request)
        if any(request.path.startswith(p) for p in self.BYPASS_PREFIXES):
            return self.get_response(request)
        user = getattr(request, "user", None)
        if is_superadmin(user):
            return self.get_response(request)
        payload = {
            "ok": False,
            "error": "service in maintenance",
            "message": state.get("message") or "Servicio en mantenimiento, intenta nuevamente en unos minutos.",
        }
        wants_json = "application/json" in (request.headers.get("Accept", "") or "")
        if wants_json:
            return JsonResponse(payload, status=503)
        return HttpResponse(payload["message"], status=503, content_type="text/plain; charset=utf-8")
