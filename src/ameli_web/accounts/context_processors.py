from __future__ import annotations

from django.conf import settings

from .permissions import can_access_admin_panel
from .services import serialize_user


def account_navigation(request):
    user = request.user
    current_user = serialize_user(user) if getattr(user, "is_authenticated", False) else None
    active_theme = (
        str(current_user.get("theme_preference") or "")
        if current_user and current_user.get("theme_preference") in {"light", "dark"}
        else ""
    )
    return {
        "current_user": current_user,
        "active_theme": active_theme,
        "can_access_admin": can_access_admin_panel(user),
        "app_name": settings.CFG.app_name,
        "docs_enabled": settings.CFG.docs_enabled,
        "redoc_enabled": settings.CFG.redoc_enabled,
        # Per-request CSP nonce produced by SecurityHeadersMiddleware.
        # Templates use this in every inline <script nonce="..."> /
        # <style nonce="..."> so the browser executes them under the
        # nonce-based policy.
        "csp_nonce": getattr(request, "csp_nonce", ""),
    }
