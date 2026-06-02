from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings

PBKDF2_ITERATIONS = 600_000


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"users": []}


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt, raw_hash = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        iterations = int(raw_iterations)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    candidate = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(candidate, raw_hash)


def load_store(settings: Settings) -> dict[str, Any]:
    path = settings.auth_store_path
    if not path.exists():
        return _empty_store()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("users", []), list):
        raise ValueError(f"Invalid access store: {path}")
    return data


def save_store(settings: Settings, store: dict[str, Any]) -> None:
    _ensure_parent(settings.auth_store_path)
    settings.auth_store_path.write_text(
        json.dumps(store, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def list_accesses(settings: Settings) -> list[dict[str, Any]]:
    store = load_store(settings)
    return [
        {
            "username": user["username"],
            "role": user["role"],
            "enabled": bool(user.get("enabled", True)),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
        }
        for user in store.get("users", [])
    ]


def _find_user(store: dict[str, Any], username: str) -> dict[str, Any] | None:
    wanted = username.strip().lower()
    for user in store.get("users", []):
        if str(user.get("username", "")).strip().lower() == wanted:
            return user
    return None


def _role_allows(actual_role: str, required_role: str) -> bool:
    if actual_role == "admin":
        return True
    return actual_role == required_role


def create_or_update_access(
    settings: Settings,
    *,
    username: str,
    password: str,
    role: str,
    enabled: bool = True,
) -> dict[str, Any]:
    if role not in {"admin", "public"}:
        raise ValueError("role must be admin or public")
    if not username.strip():
        raise ValueError("username is required")
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")

    store = load_store(settings)
    current = _find_user(store, username)
    timestamp = _utcnow()
    payload = {
        "username": username.strip(),
        "role": role,
        "enabled": enabled,
        "password_hash": _hash_password(password),
        "updated_at": timestamp,
    }

    if current is None:
        payload["created_at"] = timestamp
        store["users"].append(payload)
        status = "created"
    else:
        payload["created_at"] = current.get("created_at", timestamp)
        current.clear()
        current.update(payload)
        status = "updated"

    save_store(settings, store)
    return {
        "ok": True,
        "status": status,
        "username": payload["username"],
        "role": payload["role"],
        "enabled": payload["enabled"],
        "store_path": str(settings.auth_store_path),
    }


def bootstrap_admin(settings: Settings, *, username: str, password: str) -> dict[str, Any]:
    store = load_store(settings)
    existing_admin = next(
        (
            user
            for user in store.get("users", [])
            if user.get("role") == "admin" and user.get("enabled", True)
        ),
        None,
    )
    if existing_admin is not None:
        return {
            "ok": True,
            "status": "skipped",
            "reason": "admin-already-exists",
            "username": existing_admin.get("username"),
            "store_path": str(settings.auth_store_path),
        }
    return create_or_update_access(
        settings,
        username=username,
        password=password,
        role="admin",
        enabled=True,
    )


def authenticate_access(
    settings: Settings,
    *,
    username: str,
    password: str,
    required_role: str,
) -> dict[str, Any] | None:
    if not settings.auth_enabled:
        return None

    store = load_store(settings)
    user = _find_user(store, username)
    if user is None or not bool(user.get("enabled", True)):
        return None
    if not _role_allows(str(user.get("role", "")), required_role):
        return None
    if not verify_password(password, str(user.get("password_hash", ""))):
        return None
    return {
        "username": user["username"],
        "role": user["role"],
        "enabled": bool(user.get("enabled", True)),
    }
