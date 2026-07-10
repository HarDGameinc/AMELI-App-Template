"""Double-opt-in email change endpoints.

Moved from accounts/views.py (PC-2, 2026-07-01).
Public symbols re-exported via accounts/views/__init__.py; urls.py
imports the package via `from . import views` and uses `views.X`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ameli_app import __version__

from ._common import (
    _json_body,
    _json_error,
    logger,
)


@login_required
@require_POST
def email_change_request_view(request: HttpRequest) -> JsonResponse:
    from ..services import client_ip, request_email_change

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
    from ..services import EmailChangeRequest, record_audit

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


@require_http_methods(["GET", "POST"])
def email_change_confirm_view(request: HttpRequest, request_id: int, token: str) -> HttpResponse:
    """Public endpoint reached from the new-address email.

    Two-step to defeat mail-scanner auto-click (Microsoft Safe Links,
    Proofpoint URL Defense, Outlook link preview) that would otherwise
    burn the single-use token before the user clicks: GET renders an
    intersticial page with a confirm button; POST (CSRF-protected by
    Django middleware) applies the change. The token + request_id flow
    through both methods as URL params so the page is self-contained
    even when reloaded.

    PHASE_B_SECURITY_REVIEW B5.
    """
    from ..services import confirm_email_change

    if request.method == "GET":
        return render(
            request,
            "accounts/email_change_confirm.html",
            {
                "request_id": int(request_id),
                "token": token,
                "version": __version__,
            },
        )
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


@require_http_methods(["GET", "POST"])
def email_change_cancel_view(request: HttpRequest, request_id: int, token: str) -> HttpResponse:
    """Public endpoint reached from the OLD-address alert email. Lets the
    legitimate user revert a request they didn't make.

    Two-step to defeat mail-scanner auto-click (Safe Links / Proofpoint /
    Outlook preview) that GETs every link in the alert email: a prefetch of
    this URL would otherwise auto-cancel a legitimate pending change. GET
    renders an intersticial page; POST (CSRF-protected) applies the cancel.
    Mirrors the confirm two-step (PHASE_B_SECURITY_REVIEW B5); L4 review.
    """
    from ..services import cancel_email_change

    if request.method == "GET":
        return render(
            request,
            "accounts/email_change_cancel.html",
            {"request_id": int(request_id), "token": token, "version": __version__},
        )
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
