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


def _bootstrap_django(args):
    settings = load_settings(config_path=args.config, env_file=args.env_file)
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(config_path=args.config, env_file=args.env_file)
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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
