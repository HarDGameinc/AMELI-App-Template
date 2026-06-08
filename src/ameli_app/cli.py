from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import load_settings, settings_summary
from .database import database_status
from .logging_utils import configure_logging
from .version import __version__
from .workers.capture import run_once as run_worker_once
from .workers.maintenance import run_once as run_maintenance_once
from .workers.notify import run_once as run_notify_once


def _json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def _autodetect_env_file(etc_root: str | Path = "/etc") -> str | None:
    """Guess the system env file when launched from a packaged install.

    The install script puts each environment at ``/opt/<slug>-<env>/`` with
    its venv binary at ``.venv/bin/ameli-app``. The matching env file lives at
    ``<etc_root>/<slug>-<env>/app.env``. If we can resolve that layout, fall
    back to that env file so ``ameli-app config-check`` and ``db-status`` see
    the real configuration without the operator passing ``--env-file``.

    ``etc_root`` is parameterised mostly to make the helper testable; production
    callers always use the default ``/etc``.
    """
    # Use sys.executable as-is. ``.resolve()`` would follow the venv python
    # symlink to ``/usr/bin/python3.x`` on Debian and lose the ``/opt/<slug>``
    # layout we need to detect.
    try:
        venv_python = Path(sys.executable)
        install_dir = venv_python.parent.parent.parent
    except OSError:
        return None
    if install_dir.parent.name != "opt":
        return None
    candidate = Path(etc_root) / install_dir.name / "app.env"
    return str(candidate) if candidate.is_file() else None


def _effective_env_file(args) -> str | None:
    if args.env_file:
        return args.env_file
    if os.getenv("AMELI_APP_ENV_FILE"):
        return None  # load_settings will pick it up itself
    return _autodetect_env_file()


def _bootstrap_django(args):
    settings = load_settings(config_path=args.config, env_file=_effective_env_file(args))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    project_root = Path(__file__).resolve().parents[2]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import django

    django.setup()
    return settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ameli-app")
    parser.add_argument("--config", help="Path to app YAML config.")
    parser.add_argument("--env-file", help="Optional env file to load before config.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="Print application version.")
    sub.add_parser("config-check", help="Validate and summarize configuration.")
    sub.add_parser("db-status", help="Check database configuration/connectivity.")
    sub.add_parser("worker-once", help="Run one worker/capture cycle.")
    sub.add_parser("notify-once", help="Run one notifier/dispatch cycle.")
    sub.add_parser("maintenance", help="Run one maintenance cycle.")

    bootstrap = sub.add_parser("bootstrap-admin", help="Create the initial superadmin.")
    bootstrap.add_argument("--username", required=True, help="Superadmin username.")
    bootstrap.add_argument("--password", required=True, help="Superadmin password.")
    bootstrap.add_argument(
        "--must-change-password",
        action="store_true",
        help="Force password change at first login.",
    )

    create_user = sub.add_parser("create-user", help="Create a managed user account.")
    create_user.add_argument("--username", required=True, help="User username.")
    create_user.add_argument("--password", required=True, help="User password.")
    create_user.add_argument(
        "--role",
        choices=("public", "superadmin"),
        default="public",
        help="Role to assign.",
    )
    create_user.add_argument(
        "--actor",
        default="cli",
        help="Audit actor label used for this creation.",
    )
    create_user.add_argument(
        "--must-change-password",
        action="store_true",
        help="Force password change at first login.",
    )

    sub.add_parser("list-users", help="List managed user accounts.")

    token = sub.add_parser(
        "create-token",
        help="Create an API bearer token for a user and print the plaintext.",
    )
    token.add_argument("--user", required=True, help="Username that owns the token.")
    token.add_argument("--name", required=True, help="Human-readable token name.")
    token.add_argument(
        "--expires-in-days",
        type=int,
        default=None,
        help="Optional expiry, in days from now.",
    )
    token.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        default=None,
        help=(
            "Capability scope (repeatable). Allowed: read, write, admin. "
            "Default is read-only when omitted."
        ),
    )

    revoke = sub.add_parser(
        "revoke-token",
        help="Revoke an API token by id (find ids via list-tokens).",
    )
    revoke.add_argument("--user", required=True, help="Username that owns the token.")
    revoke.add_argument("--id", required=True, type=int, dest="token_id", help="Token id.")

    list_tokens = sub.add_parser(
        "list-tokens",
        help="List API tokens (metadata only, never the plaintext).",
    )
    list_tokens.add_argument("--user", required=True, help="Username whose tokens to list.")

    shell = sub.add_parser(
        "shell",
        help="Open a Django-ready Python shell or run a snippet/script.",
    )
    shell.add_argument(
        "-c", "--snippet",
        dest="shell_snippet",
        help="Execute the given Python snippet instead of starting an interactive shell.",
    )
    shell.add_argument(
        "script",
        nargs="?",
        help="Optional path to a Python file to execute.",
    )

    return parser


def _handle_create_user(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import create_user_account

    _json(
        create_user_account(
            args.actor,
            args.username,
            args.password,
            role=args.role,
            must_change_password=args.must_change_password,
        )
    )
    return 0


def _handle_list_users(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import list_users

    _json({"ok": True, "users": list_users()})
    return 0


def _resolve_user_or_exit(username: str):
    """Look up a user by username, printing a helpful error if missing.

    Centralised so the token CLI subcommands give consistent feedback.
    """
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        print(f"user not found: {username}", file=sys.stderr)
    return user


def _handle_create_token(args) -> int:
    _bootstrap_django(args)
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.services import create_api_token

    user = _resolve_user_or_exit(args.user)
    if user is None:
        return 2

    expires_at = None
    if args.expires_in_days is not None:
        if args.expires_in_days <= 0:
            print("expires-in-days must be a positive integer", file=sys.stderr)
            return 2
        expires_at = timezone.now() + timedelta(days=args.expires_in_days)

    try:
        result = create_api_token(
            user, name=args.name, expires_at=expires_at, scopes=args.scopes,
        )
    except ValueError as exc:
        print(f"create-token failed: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def _handle_revoke_token(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import revoke_api_token

    user = _resolve_user_or_exit(args.user)
    if user is None:
        return 2
    try:
        result = revoke_api_token(user, token_id=args.token_id)
    except ValueError as exc:
        print(f"revoke-token failed: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def _handle_list_tokens(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import list_api_tokens

    user = _resolve_user_or_exit(args.user)
    if user is None:
        return 2
    _json({"ok": True, "tokens": list_api_tokens(user)})
    return 0


def _shell_namespace() -> dict:
    """Pre-populate the shell namespace with the things you usually reach for.

    Imports are local so the cost is only paid when ``shell`` runs.
    """
    from django.contrib.auth import get_user_model
    from django.conf import settings as django_settings
    from django.db import connection

    namespace = {
        "User": get_user_model(),
        "settings": django_settings,
        "connection": connection,
    }
    try:
        from ameli_web.accounts.models import MFAEmailChallenge, MFARecoveryCode, UserSession
        from ameli_web.audit.models import AuditEvent

        namespace.update({
            "MFAEmailChallenge": MFAEmailChallenge,
            "MFARecoveryCode": MFARecoveryCode,
            "UserSession": UserSession,
            "AuditEvent": AuditEvent,
        })
    except ImportError:
        # Apps may evolve; keep the shell usable even if a model relocates.
        pass
    return namespace


def _handle_shell(args) -> int:
    _bootstrap_django(args)
    namespace = _shell_namespace()

    if args.shell_snippet:
        exec(compile(args.shell_snippet, "<ameli-app shell -c>", "exec"), namespace)
        return 0

    if args.script:
        script_path = Path(args.script)
        if not script_path.is_file():
            print(f"shell: script not found: {script_path}", file=sys.stderr)
            return 2
        source = script_path.read_text(encoding="utf-8")
        exec(compile(source, str(script_path), "exec"), namespace)
        return 0

    import code

    banner = (
        "AMELI App Template shell. Django is set up.\n"
        f"Available: {', '.join(sorted(k for k in namespace if not k.startswith('_')))}"
    )
    code.interact(banner=banner, local=namespace)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(config_path=args.config, env_file=_effective_env_file(args))
    configure_logging(settings.log_level)

    if args.command == "version":
        print(f"{settings.app_name} {__version__}")
        return 0
    if args.command == "config-check":
        _json({"ok": True, "config": settings_summary(settings)})
        return 0
    if args.command == "db-status":
        _json(database_status(settings))
        return 0
    if args.command == "worker-once":
        _json(run_worker_once(settings))
        return 0
    if args.command == "notify-once":
        _json(run_notify_once(settings))
        return 0
    if args.command == "maintenance":
        _json(run_maintenance_once(settings))
        return 0
    if args.command == "bootstrap-admin":
        _bootstrap_django(args)
        from ameli_web.accounts.services import bootstrap_superadmin

        _json(
            bootstrap_superadmin(
                args.username,
                args.password,
                must_change_password=args.must_change_password,
            )
        )
        return 0
    if args.command == "create-user":
        return _handle_create_user(args)
    if args.command == "list-users":
        return _handle_list_users(args)
    if args.command == "create-token":
        return _handle_create_token(args)
    if args.command == "revoke-token":
        return _handle_revoke_token(args)
    if args.command == "list-tokens":
        return _handle_list_tokens(args)
    if args.command == "shell":
        return _handle_shell(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
