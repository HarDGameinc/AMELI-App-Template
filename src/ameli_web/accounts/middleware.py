from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

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


class SecurityHeadersMiddleware:
    """Attach the project-wide CSP and a couple of supporting headers.

    Django already sets ``X-Content-Type-Options`` and
    ``Referrer-Policy`` from ``SECURE_*`` settings; CSP needs a custom
    middleware. We keep this in-app to avoid adding ``django-csp``.

    We mint a fresh ``csp_nonce`` per request, stash it on the request
    object so the context processor can hand it to every template, and
    bake it into the CSP header before the response leaves.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = _generate_csp_nonce()
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = build_csp(request.csp_nonce)
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
        if path.startswith("/admin") and request.user.is_authenticated and not request.user.is_staff:
            record_audit(
                "admin_access_denied",
                actor=request.user,
                target_username="admin",
                payload={"path": path, "auth_mode": "session"},
            )
            messages.warning(request, "Tu cuenta no tiene permisos para acceder al panel de administración.")
            return redirect("accounts:profile")
        return self.get_response(request)
