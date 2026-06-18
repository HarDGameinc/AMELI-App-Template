#!/usr/bin/env python
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


def _candidate_slugs(project_root: Path) -> list[str]:
    """Return the slugs we should probe under ``/etc/<slug>/``, in
    priority order.

    The deploy convention puts code at ``/opt/<slug>/`` and config
    at ``/etc/<slug>/`` — both share the same slug. A multi-instance
    host (``ameli-app-template-dev``, ``ameli-app-template-prod``)
    sets the slug per-instance via the directory name. The pyproject
    ``[project].name`` is the source slug (no instance suffix), used
    as a fallback for fresh clones that mirror the canonical name.

    Order: directory name first (matches the live deploy 1:1),
    pyproject name second (catches the un-suffixed dev checkout).
    Duplicates collapsed.
    """
    out: list[str] = []
    out.append(project_root.name)

    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            name = data.get("project", {}).get("name")
            if name and name not in out:
                out.append(str(name))
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return out


def _load_env_file_safe(env_path: Path) -> None:
    """Subset of ``ameli_app.config.load_env_file`` good enough to
    bootstrap APP_CONFIG before Django imports. Keep this here (no
    package import) so a misconfigured deploy still surfaces the
    Django error rather than an ImportError chain.

    Parsing rules:
    * Comments (``#`` prefix) and blank lines skipped.
    * ``KEY=VALUE`` split on the FIRST ``=`` only — trailing ``=``
      in Fernet keys is preserved.
    * Outer matching quotes stripped.
    * Existing env vars NEVER overridden — explicit beats file.
    """
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _autodetect_app_config(project_root: Path) -> None:
    """Discover APP_CONFIG and the matching app.env so wire-test
    invocations of ``python manage.py shell`` do not require the
    operator to manually export them.

    Lookup order (first hit wins, in keeping with the project
    pattern of "explicit beats implicit"):

    1. ``APP_CONFIG`` / ``AMELI_APP_CONFIG`` env var already set
       (e.g. by systemd unit). Honored as-is; nothing else runs.
    2. ``/etc/<slug>/app.yaml`` where ``<slug>`` is the project
       name from pyproject.toml. Matches the install.sh deploy
       layout.
    3. ``<project_root>/config/app.yaml`` — dev override.
    4. ``<project_root>/config/app.yaml.example`` — template
       default; lets a freshly-cloned repo boot without setup.

    The matching ``app.env`` (``/etc/<slug>/app.env`` or
    ``<project_root>/app.env``) is loaded via ``_load_env_file_safe``
    so the IFS bug that plagues ``set -a; . app.env; set +a`` (values
    with ``(`` / ``)`` / ``!`` etc.) does not apply here — we parse
    in Python, not bash.
    """
    if os.environ.get("APP_CONFIG") or os.environ.get("AMELI_APP_CONFIG"):
        # Operator (or systemd) already pointed us at a config. Still
        # try to load an env file co-located with it so the wire test
        # gets ``AMELI_APP_DJANGO_SECRET_KEY`` and friends.
        explicit = os.environ.get("APP_CONFIG") or os.environ.get("AMELI_APP_CONFIG")
        explicit_path = Path(explicit) if explicit else None
        if explicit_path is not None:
            _load_env_file_safe(explicit_path.parent / "app.env")
        return

    candidates: list[Path] = []
    for slug in _candidate_slugs(project_root):
        candidates.append(Path(f"/etc/{slug}/app.yaml"))
    candidates.extend([
        project_root / "config" / "app.yaml",
        project_root / "config" / "app.yaml.example",
    ])
    for candidate in candidates:
        if candidate.is_file():
            os.environ["APP_CONFIG"] = str(candidate)
            # Try the env file in the SAME directory as the chosen
            # config, then the project root as a fallback so a dev
            # checkout with a top-level app.env still loads.
            _load_env_file_safe(candidate.parent / "app.env")
            _load_env_file_safe(project_root / "app.env")
            return


def main() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    _autodetect_app_config(project_root)
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

