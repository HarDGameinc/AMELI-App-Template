from __future__ import annotations

import logging
import secrets

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

from .permissions import can_access_admin_panel, is_authenticated, is_superadmin
from .services import record_audit, sync_request_session

logger = logging.getLogger(__name__)


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

    ``style-src`` no longer needs ``'unsafe-inline'``: every template
    inline ``style=""`` attribute was moved to a utility/semantic class
    in ``static/css/app.css`` (2026-07-12), so a reflected-markup XSS
    can no longer smuggle in styles either. ``https://fonts.googleapis.
    com`` stays whitelisted for the Google Fonts stylesheet ``<link>``.
    (The ``/django-admin`` and ``/docs`` per-page CSPs still carry
    ``'unsafe-inline'`` for framework/CDN-owned inline styles we do not
    control — see ``_django_admin_csp`` and the docs view.)

    ``require-trusted-types-for 'script'`` + ``trusted-types
    ameli-template`` enforce that every DOM-XSS sink assignment
    (``innerHTML``, ``outerHTML``, ``document.write`` …) routes
    through the single ``ameli-template`` policy created in
    ``base.html``. A future XSS that survives ``script-src`` (e.g. a
    nonce reuse bug) would still be unable to inject HTML through
    these sinks unless it ALSO names our policy. Firefox / Safari
    historically ignore the directive — the same code still works
    there via the identity fallback.
    """
    return (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "require-trusted-types-for 'script'; "
        "trusted-types ameli-template"
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
            # ``/profile/password/`` renders a standalone password-change
            # form when ``must_change_password=True`` so the user does
            # NOT see the rest of the profile (MFA enrolment, sessions,
            # audit log) until the temp password is rotated. Previously
            # ``/profile/`` itself was on the allow-list, leaking that
            # data to anyone holding the temp credentials.
            return redirect("/profile/password/")
        return self.get_response(request)

    @classmethod
    def _path_is_allowed(cls, path: str) -> bool:
        if path in cls._ALLOWED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in cls._ALLOWED_PREFIXES)


class MfaRequiredMiddleware:
    """Force an admin-mandated user to enroll MFA before using the app.

    When an admin sets ``mfa_required=True`` the flag used to be a pure UI
    hint (M2 security review): nothing forced enrollment and nothing stopped
    the user from ignoring it. This mirrors ``MustChangePasswordMiddleware``:
    a flagged user with no active MFA (``mfa_required and not mfa_enabled``)
    is redirected to the profile MFA section until they enroll. Enrolling
    sets ``mfa_enabled=True`` (the flag itself stays set), which lets this
    gate pass; self-disable is separately refused while ``mfa_required`` is
    on (see ``services/mfa.py``), so the mandate cannot be shed.

    Runs AFTER ``MustChangePasswordMiddleware`` so a temp-password rotation
    (a harder block) takes priority; once the password is cleared this gate
    engages.
    """

    _ALLOWED_EXACT = {
        "/profile/",
        "/profile",
        "/logout/",
        "/logout",
        "/health",
        "/api/health",
        # Reachable so a user under BOTH mandates can still rotate the
        # temp password before enrolling.
        "/profile/password/",
        "/profile/password",
        "/profile/change-password",
    }
    _ALLOWED_PREFIXES = ("/static/", "/media/", "/profile/mfa/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "mfa_required", False)
            and not getattr(user, "mfa_enabled", False)
            and not self._path_is_allowed(request.path)
        ):
            messages.warning(
                request,
                "Un administrador exige activar 2FA en tu cuenta antes de continuar.",
            )
            return redirect("/profile/")
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
        # PHASE_B_SECURITY_REVIEW B7: gate by ``is_staff`` instead of
        # ``is_superadmin``. The model's ``User.save`` enforces the
        # lockstep (is_staff is mirrored from role==SUPERADMIN), but a
        # bypass via ``.update()`` / bulk_create / shell / data
        # migration could leave a non-superadmin with is_staff=True;
        # that user would then reach Django's native admin (which gates
        # by is_staff) without our sudo grant. Use the same predicate
        # the framework uses so the defenses cannot drift apart.
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
            return self.get_response(request)
        assert user is not None  # noqa: S101 - narrowed by is_authenticated above
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
        # Lazy import + narrow exception swallow so an unmigrated install
        # (first migrate, fresh checkout) doesn't brick the pipeline.
        # PHASE_B_SECURITY_REVIEW B6: was ``except Exception`` which
        # fail-opens the read-only gate on ANY transient error (pool
        # exhaustion, query timeout) — an attacker could induce that
        # mid-window to bypass the freeze. Now only the schema-not-yet-
        # there cases swallow silently; any other failure is logged AND
        # the safe default is to ASSUME maintenance is ACTIVE+read_only,
        # so a hung DB does not silently open writes.
        from django.db.utils import OperationalError, ProgrammingError

        try:
            from .services import get_maintenance_state

            return get_maintenance_state()
        except ProgrammingError:
            # Table doesn't exist yet — first migrate or fresh DB.
            return {"active": False, "read_only": True, "message": ""}
        except OperationalError as exc:
            # Connection / pool / timeout. Fail closed: presume the
            # operator intended writes to be paused if the DB cannot
            # confirm otherwise. Logs surface for ops triage.
            logger.error("maintenance state query failed (OperationalError): %s", exc)
            return {"active": True, "read_only": True, "message": "Servicio en mantenimiento."}

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
