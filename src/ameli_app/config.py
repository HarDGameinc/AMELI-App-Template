from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml.example"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_env_file(path: str | Path | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_slug: str
    environment: str
    timezone: str
    host: str
    api_port: int
    web_port: int
    require_token: bool
    api_token: str
    auth_enabled: bool
    auth_store_path: Path
    database_url: str
    log_level: str
    config_path: Path
    data_dir: Path
    log_dir: Path
    backup_dir: Path
    docs_enabled: bool
    redoc_enabled: bool
    admin_enabled: bool
    session_cookie_name: str
    session_cookie_secure: bool
    session_max_age_seconds: int
    django_secret_key: str
    django_debug: bool
    profile_uploads_dir: Path
    features: dict[str, Any] = field(default_factory=dict)
    worker: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def load_settings(
    config_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> Settings:
    load_env_file(env_file or os.getenv("AMELI_APP_ENV_FILE"))

    selected_config = Path(
        config_path
        or os.getenv("APP_CONFIG")
        or os.getenv("AMELI_APP_CONFIG")
        or DEFAULT_CONFIG_PATH
    )
    if not selected_config.is_absolute():
        selected_config = Path.cwd() / selected_config
    selected_config = selected_config.resolve()

    raw = _load_yaml(selected_config)
    app = raw.get("app", {})
    api = raw.get("api", {})
    paths = raw.get("paths", {})
    database = raw.get("database", {})
    auth = raw.get("auth", {})
    docs = raw.get("docs", {})

    environment = os.getenv("APP_ENV") or str(app.get("environment", "dev"))
    token_env = str(api.get("token_env", "AMELI_APP_API_TOKEN"))
    database_url_env = str(database.get("url_env", "DATABASE_URL"))

    def path_from_config(key: str, default: str) -> Path:
        value = Path(str(paths.get(key, default)))
        return value if value.is_absolute() else PROJECT_ROOT / value

    def path_from_value(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    return Settings(
        app_name=str(app.get("name", "AMELI App")),
        app_slug=str(app.get("slug", "ameli-app")),
        environment=environment,
        timezone=str(app.get("timezone", "America/Santiago")),
        host=os.getenv("AMELI_APP_HOST", str(api.get("host", "127.0.0.1"))),
        api_port=_as_int(os.getenv("AMELI_APP_API_PORT", api.get("port")), 18080),
        web_port=_as_int(
            os.getenv("AMELI_APP_WEB_PORT", raw.get("dashboard", {}).get("port")), 18081
        ),
        require_token=_as_bool(
            os.getenv("AMELI_APP_REQUIRE_TOKEN", api.get("require_token")),
            default=False,
        ),
        api_token=os.getenv(token_env, ""),
        auth_enabled=_as_bool(
            os.getenv("AMELI_APP_AUTH_ENABLED", auth.get("enabled")),
            default=False,
        ),
        auth_store_path=path_from_value(str(auth.get("store_path", "data/access.json"))),
        database_url=os.getenv(database_url_env, ""),
        log_level=os.getenv("APP_LOG_LEVEL", "INFO"),
        config_path=selected_config,
        data_dir=path_from_config("data_dir", "data"),
        log_dir=path_from_config("log_dir", "logs"),
        backup_dir=path_from_config("backup_dir", "backups"),
        docs_enabled=_as_bool(os.getenv("AMELI_APP_DOCS_ENABLED", docs.get("enabled")), default=True),
        redoc_enabled=_as_bool(os.getenv("AMELI_APP_REDOC_ENABLED", docs.get("redoc_enabled")), default=True),
        admin_enabled=_as_bool(os.getenv("AMELI_APP_ADMIN_ENABLED", raw.get("features", {}).get("admin")), default=True),
        session_cookie_name=os.getenv("AMELI_APP_SESSION_COOKIE_NAME", str(auth.get("session_cookie_name", "ameli_app_session"))),
        session_cookie_secure=_as_bool(
            os.getenv("AMELI_APP_SESSION_COOKIE_SECURE", auth.get("session_cookie_secure")),
            default=False,
        ),
        session_max_age_seconds=_as_int(
            os.getenv("AMELI_APP_SESSION_MAX_AGE_SECONDS", auth.get("session_max_age_seconds")),
            43200,
        ),
        django_secret_key=os.getenv("AMELI_APP_DJANGO_SECRET_KEY", "ameli-app-dev-secret-key"),
        django_debug=_as_bool(os.getenv("AMELI_APP_DJANGO_DEBUG"), default=environment == "dev"),
        profile_uploads_dir=path_from_value(
            str(auth.get("profile_uploads_dir", f"data/uploads/{environment}"))
        ),
        features=dict(raw.get("features", {})),
        worker=dict(raw.get("worker", {})),
        raw=raw,
    )


def settings_summary(settings: Settings) -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "app_slug": settings.app_slug,
        "environment": settings.environment,
        "host": settings.host,
        "api_port": settings.api_port,
        "web_port": settings.web_port,
        "require_token": settings.require_token,
        "auth_enabled": settings.auth_enabled,
        "auth_store_path": str(settings.auth_store_path),
        "database_configured": bool(settings.database_url),
        "docs_enabled": settings.docs_enabled,
        "redoc_enabled": settings.redoc_enabled,
        "admin_enabled": settings.admin_enabled,
        "session_cookie_name": settings.session_cookie_name,
        "config_path": str(settings.config_path),
    }
