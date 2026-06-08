from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect

from .services import record_audit, sync_request_session


class UserSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
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


class ApiTokenAuthMiddleware:
    """Authenticate ``Authorization: Bearer ameli_<token>`` requests.

    Runs before ``AuthenticationMiddleware`` would set the session-based
    user. When a valid token is present we set ``request.user`` directly,
    bypassing the session machinery. We do NOT call ``login(request, ...)``
    because we don't want a cookie session to be created for an API call —
    each API call must carry its own bearer token.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer "):
            plaintext = header[len("Bearer "):].strip()
            from .services import authenticate_api_token

            user = authenticate_api_token(plaintext)
            if user is not None:
                # Tag the request so views can tell session auth from token auth.
                request.api_token_user = user
                if not getattr(request.user, "is_authenticated", False):
                    request.user = user
        return self.get_response(request)
