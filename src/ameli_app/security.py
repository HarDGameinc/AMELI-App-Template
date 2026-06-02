from __future__ import annotations

import base64
import hmac

from fastapi import HTTPException, Request, status

from .access_store import authenticate_access
from .config import Settings


def token_required(settings: Settings) -> bool:
    return settings.require_token and bool(settings.api_token)


def verify_token(candidate: str | None, settings: Settings) -> bool:
    if not token_required(settings):
        return True
    if not candidate:
        return False
    return hmac.compare_digest(candidate, settings.api_token)


def token_from_request(request: Request) -> str | None:
    header_token = request.headers.get("x-api-token")
    if header_token:
        return header_token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def basic_auth_from_request(request: Request) -> tuple[str, str] | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("basic "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:  # noqa: BLE001
        return None
    return username, password


def require_request_token(request: Request, settings: Settings) -> None:
    if verify_token(token_from_request(request), settings):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API token required",
    )


def require_admin_access(request: Request, settings: Settings) -> None:
    if settings.auth_enabled:
        credentials = basic_auth_from_request(request)
        if credentials is not None:
            username, password = credentials
            if authenticate_access(
                settings,
                username=username,
                password=password,
                required_role="admin",
            ):
                return
        if token_required(settings) and verify_token(token_from_request(request), settings):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin credentials required",
            headers={"WWW-Authenticate": 'Basic realm="AMELI Admin"'},
        )

    require_request_token(request, settings)
