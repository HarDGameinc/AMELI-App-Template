"""User-initiated account deletion.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ._common import (
    _expects_json,
    _json_body,
    _json_error,
)


@login_required
@require_POST
def delete_my_account_view(request: HttpRequest) -> HttpResponse:
    """Self-service account deletion. Requires the current password
    so a stolen cookie alone cannot wipe the account; superadmins
    cannot self-delete (they must promote another superadmin first
    and use the CLI prune).
    """

    from ..services import delete_my_account

    if _expects_json(request):
        try:
            payload = _json_body(request)
        except ValueError as exc:
            return _json_error(str(exc))
        password = str(payload.get("password") or "").strip()
    else:
        password = str(request.POST.get("password") or "").strip()
    if not password:
        if _expects_json(request):
            return _json_error("password is required")
        messages.error(request, _("Ingresa tu contrasena para confirmar."))
        return redirect("accounts:profile")
    try:
        result = delete_my_account(user=request.user, password=password)
    except ValueError as exc:
        if _expects_json(request):
            return _json_error(str(exc))
        messages.error(request, str(exc))
        return redirect("accounts:profile")
    # The user row is gone; tear down the session so the next request
    # behaves like a fresh visitor.
    auth_logout(request)
    if _expects_json(request):
        return JsonResponse(result)
    messages.success(request, _("Cuenta eliminada."))
    return redirect("/login/")
