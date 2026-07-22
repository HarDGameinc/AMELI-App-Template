from __future__ import annotations

import argparse
import json
import os
import re
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

# Exit codes for the audit-key subcommands. Documented in
# docs/OPERATIONS.md so a pipeline can branch on them deterministically.
EXIT_OK = 0
EXIT_GENERIC_ERROR = 1
EXIT_ROTATION_REFUSED = 2
EXIT_CHAIN_BROKEN_STRICT = 3
EXIT_ENV_WRITE_FAILED = 4


def _json(data: object) -> None:
    # ``print`` writes through the console encoding (cp1252 on a default
    # Windows console), which raises ``UnicodeEncodeError`` on non-ASCII
    # output — e.g. the emoji in a release note surfaced by ``template-check``.
    # That crashed the very channel a child app uses to learn about a security
    # release. Force UTF-8 on a real console; captured / piped streams (tests)
    # have no ``reconfigure`` and are already text-safe.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
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

    template_check = sub.add_parser(
        "template-check",
        help="Compare this app's template lineage against the latest "
        "AMELI App Template release on GitHub.",
    )
    template_check.add_argument(
        "--repo",
        default=os.environ.get("AMELI_APP_TEMPLATE_REPO", "HarDGameinc/AMELI-App-Template"),
        help="owner/name of the template repo (env AMELI_APP_TEMPLATE_REPO).",
    )
    template_check.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds (default 10).",
    )

    purge_users = sub.add_parser(
        "purge-inactive-users",
        help="Delete users disabled longer than --days (PII purge).",
    )
    purge_users.add_argument(
        "--days",
        type=int,
        default=365,
        help="Disabled (is_active=False) AND updated_at older than this many days.",
    )
    purge_users.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which users would be deleted without touching the DB.",
    )

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

    verify_audit = sub.add_parser(
        "verify-audit",
        help="Walk the audit-log hash chain and report tampering.",
    )
    verify_audit.add_argument(
        "--from-id", type=int, default=None,
        help="Start verification at this row id (inclusive).",
    )
    verify_audit.add_argument(
        "--to-id", type=int, default=None,
        help="Stop verification at this row id (inclusive).",
    )
    verify_audit.add_argument(
        "--strict-precondition", action="store_true",
        help=(
            "Use a distinct exit code (3) when the chain is broken so an "
            "automated pipeline can refuse to chain into rotate-audit-key."
        ),
    )

    rotate_audit_key = sub.add_parser(
        "rotate-audit-key",
        help=(
            "Re-stamp the audit hash chain with a fresh HMAC key. "
            "Refuses to run if the chain under --from-key is already broken."
        ),
    )
    from_group = rotate_audit_key.add_mutually_exclusive_group(required=True)
    from_group.add_argument(
        "--from-key",
        help=(
            "Current AMELI_APP_AUDIT_HMAC_KEY (insecure: visible in "
            "`ps`/shell history). Prefer --from-key-env or --from-key-stdin."
        ),
    )
    from_group.add_argument(
        "--from-key-env", metavar="VARNAME",
        help="Read the current key from environment variable VARNAME.",
    )
    from_group.add_argument(
        "--from-key-stdin", action="store_true",
        help=(
            "Read the current key from stdin (first line). If "
            "--to-key-stdin is also set, the from-key is read first."
        ),
    )
    to_group = rotate_audit_key.add_mutually_exclusive_group(required=True)
    to_group.add_argument(
        "--to-key",
        help=(
            "New key (insecure: visible in `ps`/shell history). "
            "Prefer --to-key-env or --to-key-stdin."
        ),
    )
    to_group.add_argument(
        "--to-key-env", metavar="VARNAME",
        help="Read the new key from environment variable VARNAME.",
    )
    to_group.add_argument(
        "--to-key-stdin", action="store_true",
        help=(
            "Read the new key from stdin. When both --from-key-stdin "
            "and --to-key-stdin are set, the from-key is read first."
        ),
    )
    rotate_audit_key.add_argument(
        "--apply-env",
        dest="apply_env",
        default=None,
        help=(
            "After a successful rotation, atomically rewrite "
            "AMELI_APP_AUDIT_HMAC_KEY=<to_key> in the given env file. "
            "Avoids the manual sed step (and the empty-variable footgun). "
            "You still need to restart the service afterwards."
        ),
    )

    configure = sub.add_parser(
        "configure",
        help="Wizard for the runtime env file (ALLOWED_HOSTS, TRUSTED_PROXIES, "
        "SMTP, superadmin). Interactive when stdin is a TTY; use --yes for "
        "non-interactive with AMELI_APP_CONFIGURE_* env vars.",
    )
    configure.add_argument(
        "--section",
        choices=("hosts", "proxies", "smtp", "admin", "all"),
        default="all",
        help="Configure only the given section (default: all).",
    )
    configure.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive: read values from AMELI_APP_CONFIGURE_* env "
        "vars; fail if required ones are missing.",
    )
    configure.add_argument(
        "--check",
        action="store_true",
        help="Report what would change without writing the env file.",
    )

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


def _handle_verify_audit(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import verify_audit_chain

    result = verify_audit_chain(start_id=args.from_id, stop_id=args.to_id)
    _json(result)
    if result.get("ok"):
        return EXIT_OK
    # Non-zero exit when the chain is broken so an operator running this
    # from cron / systemd timer can hook an alert. With
    # --strict-precondition we return a distinct code so a pipeline
    # like `verify-audit --strict-precondition && rotate-audit-key`
    # can detect "you can't rotate yet" specifically.
    return EXIT_CHAIN_BROKEN_STRICT if args.strict_precondition else EXIT_GENERIC_ERROR


def _resolve_rotation_keys(args) -> tuple[str | None, str | None, str | None]:
    """Resolve from_key/to_key from argv/env/stdin sources.

    Returns ``(from_key, to_key, error)``. When ``error`` is set, the
    caller surfaces it as ``{ok: false, error}`` and aborts with
    EXIT_ROTATION_REFUSED — same shape the service layer uses on
    refusal so the CLI behavior stays consistent.

    Stdin reads consume one line each. When both ``--from-key-stdin``
    and ``--to-key-stdin`` are set, the from-key is read first so the
    operator can pipe ``{ echo "$OLD"; echo "$NEW"; }`` deterministically.
    """
    stdin_lines: list[str] = []
    want_stdin = bool(args.from_key_stdin) + bool(args.to_key_stdin)
    if want_stdin:
        for _ in range(want_stdin):
            line = sys.stdin.readline()
            if line == "":
                return None, None, "stdin closed before all keys were provided"
            stdin_lines.append(line.rstrip("\n").rstrip("\r"))

    if args.from_key is not None:
        from_key = args.from_key
    elif args.from_key_env:
        from_key = os.environ.get(args.from_key_env, "")
        if not from_key:
            return None, None, f"env var {args.from_key_env!r} is empty or unset"
    else:
        from_key = stdin_lines.pop(0)

    if args.to_key is not None:
        to_key = args.to_key
    elif args.to_key_env:
        to_key = os.environ.get(args.to_key_env, "")
        if not to_key:
            return None, None, f"env var {args.to_key_env!r} is empty or unset"
    else:
        to_key = stdin_lines.pop(0)

    return from_key, to_key, None


def _handle_rotate_audit_key(args) -> int:
    _bootstrap_django(args)
    from ameli_web.accounts.services import (
        apply_audit_key_to_env_file,
        rotate_audit_key,
    )

    from_key, to_key, err = _resolve_rotation_keys(args)
    if err is not None:
        _json({"ok": False, "error": err})
        return EXIT_ROTATION_REFUSED
    # _resolve_rotation_keys returns (None, None, err) OR (str, str, None);
    # after the err-not-None gate above, both keys are str. Narrow for mypy.
    assert from_key is not None and to_key is not None  # noqa: S101 - type narrowing

    result = rotate_audit_key(from_key=from_key, to_key=to_key)
    if result.get("ok") and args.apply_env:
        env_result = apply_audit_key_to_env_file(args.apply_env, to_key)
        result["env_file"] = env_result
        if not env_result.get("ok"):
            # The DB was rotated successfully but we failed to update the
            # env file. Surface the failure loudly with a distinct exit
            # code so the operator knows the in-memory key still mismatches.
            _json(result)
            return EXIT_ENV_WRITE_FAILED
    _json(result)
    return EXIT_OK if result.get("ok") else EXIT_ROTATION_REFUSED


def _shell_namespace() -> dict:
    """Pre-populate the shell namespace with the things you usually reach for.

    Imports are local so the cost is only paid when ``shell`` runs.
    """
    from django.conf import settings as django_settings
    from django.contrib.auth import get_user_model
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
        # ``ameli-app shell -c "<snippet>"`` is the operator's interactive
        # Python — equivalent to ``django-admin shell -c``. Input comes
        # from the local shell that already has full process privileges;
        # ``exec`` here is by design. Annotated to silence bandit B102 /
        # ruff S102 without disabling them globally.
        exec(compile(args.shell_snippet, "<ameli-app shell -c>", "exec"), namespace)  # noqa: S102  # nosec B102
        return 0

    if args.script:
        script_path = Path(args.script)
        if not script_path.is_file():
            print(f"shell: script not found: {script_path}", file=sys.stderr)
            return 2
        source = script_path.read_text(encoding="utf-8")
        # Same rationale as the -c branch above: operator-supplied script
        # in a local privileged shell. Annotated to silence bandit B102 /
        # ruff S102.
        exec(compile(source, str(script_path), "exec"), namespace)  # noqa: S102  # nosec B102
        return 0

    import code

    banner = (
        "AMELI App Template shell. Django is set up.\n"
        f"Available: {', '.join(sorted(k for k in namespace if not k.startswith('_')))}"
    )
    code.interact(banner=banner, local=namespace)
    return 0


_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parse_semver(tag: str) -> tuple[int, int, int] | None:
    """Extract ``(major, minor, patch)`` from a ``vX.Y.Z-django`` tag."""
    match = _SEMVER_RE.search(tag or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _lineage_status(current: str, latest: str) -> str:
    """``behind`` / ``ahead`` / ``up-to-date`` / ``unknown`` comparing two tags."""
    cur, lat = _parse_semver(current), _parse_semver(latest)
    if cur is None or lat is None:
        return "unknown"
    if cur < lat:
        return "behind"
    if cur > lat:
        return "ahead"
    return "up-to-date"


def _template_lineage() -> str:
    """The template release this app is synced to. Precedence:
    ``AMELI_APP_TEMPLATE_LINEAGE`` env → a root ``TEMPLATE_LINEAGE`` file →
    the app's own ``VERSION`` (correct for the template repo itself and a
    freshly-forked app that has not diverged yet)."""
    env = os.environ.get("AMELI_APP_TEMPLATE_LINEAGE", "").strip()
    if env:
        return env
    lineage_file = Path(__file__).resolve().parents[2] / "TEMPLATE_LINEAGE"
    try:
        text = lineage_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        text = ""
    return text or __version__


def _handle_template_check(args: argparse.Namespace) -> int:
    """Query the latest GitHub release of the template and compare. Exit 0
    when up-to-date/ahead/unknown, 1 when behind (actionable), 2 on error."""
    import urllib.error
    import urllib.request

    repo = str(args.repo).strip()
    if not _REPO_RE.match(repo):
        _json({"ok": False, "error": f"invalid --repo {repo!r}; expected 'owner/name'"})
        return 2

    current = _template_lineage()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ameli-app-template-check",
    }
    # Private template repos return 404 unauthenticated — pass a token if set.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("AMELI_APP_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Fixed https host (api.github.com); repo validated by _REPO_RE above.
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as resp:  # noqa: S310  # nosec B310
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # 403 with the rate-limit header exhausted is the common failure for an
        # UNauthenticated caller: GitHub allows only 60 req/hour per IP, so a
        # cron — or several child apps behind one NAT — hits it fast. Say so,
        # and point at the fix, instead of an opaque "github api 403".
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code in (403, 429) and remaining == "0":
            hint = " rate-limited (anonymous GitHub API is 60/hour per IP); set GITHUB_TOKEN to raise the limit"
        elif exc.code == 404:
            hint = " (private repo or no release yet? set GITHUB_TOKEN)"
        else:
            hint = ""
        _json(
            {"ok": False, "error": f"github api {exc.code}{hint}", "repo": repo, "current": current}
        )
        return 2
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        _json({"ok": False, "error": f"fetch failed: {exc}", "repo": repo, "current": current})
        return 2

    latest = str(data.get("tag_name", "")).strip()
    status = _lineage_status(current, latest)
    _json(
        {
            "ok": True,
            "repo": repo,
            "current": current,
            "latest": latest,
            "status": status,
            "release_url": data.get("html_url"),
            "published_at": data.get("published_at"),
            "notes_excerpt": str(data.get("body") or "")[:800],
        }
    )
    return 1 if status == "behind" else 0


# ---------------------------------------------------------------------------
# `ameli-app configure` — wizard to fill the runtime env file
# ---------------------------------------------------------------------------
# The three crypto keys the prod fail-closed guards require are already
# auto-generated by ``scripts/install.sh`` (see DECISIONS #10). What
# ``configure`` closes is the rest of the DX gap: values that cannot be
# generated blindly and today are documented as manual — ALLOWED_HOSTS,
# TRUSTED_PROXIES, SMTP relay, and the superadmin bootstrap.
#
# Non-interactive (``--yes`` OR stdin is not a TTY): every value comes
# from ``AMELI_APP_CONFIGURE_<KEY>`` env vars, and any missing required
# value exits non-zero with the list of what to set. No half-configured
# deploys.


def _read_env_file(path: str | Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file. Comment/blank lines are ignored."""
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _write_env_updates(path: str | Path, updates: dict[str, str]) -> None:
    """Rewrite the env file, updating in-place and appending new keys.

    Preserves comments and unrelated lines. Idempotent — writing the same
    updates twice produces the same file.
    """
    p = Path(path)
    existing = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    written: set[str] = set()
    out: list[str] = []
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _, _ = stripped.partition("=")
        key = key.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in written:
            out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def _prompt_value(
    label: str,
    default: str,
    *,
    interactive: bool,
    env_key: str,
    secret: bool = False,
) -> str:
    """Interactive: prompt showing default; empty input keeps default.
    Non-interactive: read AMELI_APP_CONFIGURE_<env_key>, fall back to default."""
    if not interactive:
        return os.environ.get(f"AMELI_APP_CONFIGURE_{env_key}", default)
    hint = " (input hidden)" if secret else ""
    prompt = f"  {label}{hint} [{default or '<none>'}]: "
    if secret:
        import getpass

        value = getpass.getpass(prompt)
    else:
        value = input(prompt)
    return value.strip() or default


def _autodetect_allowed_hosts() -> str:
    import socket

    hn = socket.gethostname()
    parts = [hn]
    if hn and "." not in hn:
        parts.append(f"{hn}.lan")
    parts.extend(["localhost", "127.0.0.1"])
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            out.append(p)
            seen.add(p)
    return ",".join(out)


def _handle_configure(args: argparse.Namespace) -> int:
    env_file = _effective_env_file(args) or _autodetect_env_file()
    if env_file is None:
        print(
            "configure: cannot locate the runtime env file. Pass --env-file "
            "/path/to/app.env (or run this on a server where install.sh has "
            "written /etc/<slug>/app.env).",
            file=sys.stderr,
        )
        return 2

    current = _read_env_file(env_file)
    sections = (
        ["hosts", "proxies", "smtp", "admin"]
        if args.section == "all"
        else [args.section]
    )
    interactive = sys.stdin.isatty() and not args.yes

    if not interactive:
        # In non-interactive mode, list every required var that has no
        # AMELI_APP_CONFIGURE_* override AND no current value. Fail fast.
        missing: list[str] = []
        required = {
            "hosts": ["ALLOWED_HOSTS"],
            "proxies": ["TRUSTED_PROXIES"],
            "smtp": [],  # SMTP is optional (console backend stays valid)
            "admin": ["ADMIN_USER", "ADMIN_PASSWORD"],
        }
        for section in sections:
            for k in required.get(section, []):
                if not os.environ.get(f"AMELI_APP_CONFIGURE_{k}"):
                    missing.append(f"AMELI_APP_CONFIGURE_{k}")
        if missing:
            print(
                "configure: non-interactive but required env vars are missing: "
                + ", ".join(missing),
                file=sys.stderr,
            )
            return 2

    updates: dict[str, str] = {}
    bootstrap_admin_params: dict[str, str] | None = None

    if "hosts" in sections:
        if interactive:
            print("Hosts (Django ALLOWED_HOSTS):")
        default = current.get(
            "AMELI_APP_DJANGO_ALLOWED_HOSTS", ""
        ) or _autodetect_allowed_hosts()
        value = _prompt_value(
            "ALLOWED_HOSTS (comma-separated)",
            default,
            interactive=interactive,
            env_key="ALLOWED_HOSTS",
        )
        updates["AMELI_APP_DJANGO_ALLOWED_HOSTS"] = value

    if "proxies" in sections:
        if interactive:
            print("Trusted proxies (REMOTE_ADDR values of reverse proxies):")
        default = current.get("AMELI_APP_TRUSTED_PROXIES", "127.0.0.1")
        value = _prompt_value(
            "TRUSTED_PROXIES (comma-separated; empty = disable proxy trust)",
            default,
            interactive=interactive,
            env_key="TRUSTED_PROXIES",
        )
        updates["AMELI_APP_TRUSTED_PROXIES"] = value

    if "smtp" in sections:
        if interactive:
            print("SMTP relay (leave HOST empty to keep the console backend):")
        host = _prompt_value(
            "EMAIL_HOST",
            current.get("AMELI_APP_EMAIL_HOST", ""),
            interactive=interactive,
            env_key="EMAIL_HOST",
        )
        if host:
            updates["AMELI_APP_EMAIL_HOST"] = host
            updates["AMELI_APP_EMAIL_PORT"] = _prompt_value(
                "EMAIL_PORT",
                current.get("AMELI_APP_EMAIL_PORT", "587"),
                interactive=interactive,
                env_key="EMAIL_PORT",
            )
            updates["AMELI_APP_EMAIL_USERNAME"] = _prompt_value(
                "EMAIL_USERNAME",
                current.get("AMELI_APP_EMAIL_USERNAME", ""),
                interactive=interactive,
                env_key="EMAIL_USERNAME",
            )
            updates["AMELI_APP_EMAIL_PASSWORD"] = _prompt_value(
                "EMAIL_PASSWORD",
                current.get("AMELI_APP_EMAIL_PASSWORD", ""),
                interactive=interactive,
                env_key="EMAIL_PASSWORD",
                secret=True,
            )
            updates["AMELI_APP_EMAIL_USE_TLS"] = _prompt_value(
                "EMAIL_USE_TLS (true/false)",
                current.get("AMELI_APP_EMAIL_USE_TLS", "true"),
                interactive=interactive,
                env_key="EMAIL_USE_TLS",
            )
            updates["AMELI_APP_EMAIL_FROM_ADDRESS"] = _prompt_value(
                "EMAIL_FROM_ADDRESS",
                current.get(
                    "AMELI_APP_EMAIL_FROM_ADDRESS",
                    updates["AMELI_APP_EMAIL_USERNAME"] or "",
                ),
                interactive=interactive,
                env_key="EMAIL_FROM_ADDRESS",
            )
            updates["AMELI_APP_EMAIL_BACKEND"] = "smtp"

    if "admin" in sections:
        if interactive:
            print("Superadmin bootstrap (leave USER empty to skip):")
        user = _prompt_value(
            "USER",
            "",
            interactive=interactive,
            env_key="ADMIN_USER",
        )
        if user:
            password = _prompt_value(
                "PASSWORD",
                "",
                interactive=interactive,
                env_key="ADMIN_PASSWORD",
                secret=True,
            )
            if password:
                bootstrap_admin_params = {
                    "username": user,
                    "password": password,
                }

    if args.check:
        _json(
            {
                "env_file": env_file,
                "would_set": {k: ("<hidden>" if "PASSWORD" in k else v)
                              for k, v in updates.items()},
                "bootstrap_admin": bool(bootstrap_admin_params),
            }
        )
        return 0

    _write_env_updates(env_file, updates)
    admin_result = None
    admin_error = None
    if bootstrap_admin_params:
        # Creating the superadmin needs a bootable Django, which needs a
        # valid config -- the very thing this wizard exists to write. When
        # the deploy is not there yet (unreachable database, a guard still
        # unsatisfied), a raw traceback reads as "configure failed" and
        # hides the fact that the env file was already written above. Fail
        # legibly instead, and tell the operator exactly how to finish.
        try:
            _bootstrap_django(args)
            from ameli_web.accounts.services import bootstrap_superadmin

            admin_result = bootstrap_superadmin(
                bootstrap_admin_params["username"],
                bootstrap_admin_params["password"],
                must_change_password=True,
            )
        except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
            admin_error = f"{type(exc).__name__}: {exc}"

    payload: dict[str, object] = {
        "env_file": env_file,
        "written": sorted(updates.keys()),
        "bootstrap_admin": admin_result,
    }
    if admin_error is not None:
        payload["bootstrap_admin_error"] = admin_error
        payload["hint"] = (
            "The env file was written. Django could not boot yet, so the "
            "superadmin is still pending. Fix the reported error (usually "
            "the database is unreachable or a required setting is still "
            "unset), then run: ameli-app --env-file "
            f"{env_file} bootstrap-admin --username ... --password ..."
        )
        _json(payload)
        return 1

    _json(payload)
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
    if args.command == "purge-inactive-users":
        _bootstrap_django(args)
        from ameli_web.accounts.services import purge_inactive_users

        _json(purge_inactive_users(days=args.days, dry_run=args.dry_run))
        return 0
    if args.command == "create-user":
        return _handle_create_user(args)
    if args.command == "list-users":
        return _handle_list_users(args)
    if args.command == "verify-audit":
        return _handle_verify_audit(args)
    if args.command == "rotate-audit-key":
        return _handle_rotate_audit_key(args)
    if args.command == "shell":
        return _handle_shell(args)
    if args.command == "template-check":
        return _handle_template_check(args)
    if args.command == "configure":
        return _handle_configure(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
