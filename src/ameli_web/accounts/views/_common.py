"""Cross-view helpers, session keys, logger, User = get_user_model()."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse

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
