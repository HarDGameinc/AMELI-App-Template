from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

from .services import record_audit, sync_request_session


class SecurityHeadersMiddleware:
    """Attach the project-wide CSP and a couple of supporting headers.

    Django already sets ``X-Content-Type-Options`` and
    ``Referrer-Policy`` from ``SECURE_*`` settings; CSP needs a custom
    middleware. We keep this in-app to avoid adding ``django-csp``.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._policy = getattr(settings, "CONTENT_SECURITY_POLICY", "")

    def __call__(self, request):
        response = self.get_response(request)
        if self._policy and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = self._policy
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
