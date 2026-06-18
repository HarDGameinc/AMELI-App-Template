"""Regression coverage for ASVS V14.2.3 — third-party
signature/integrity verified at install time.

Closes roadmap item #14. Before: the deploy installed deps from
``requirements.txt`` with range pins (``>=X.Y,<N``); a rotated
wheel on PyPI or a typosquat satisfying the range would install
silently. After: the deploy and CI install from
``requirements.lock`` / ``requirements-dev.lock`` with
``pip install --require-hashes``; any archive whose sha256 does
not match the lockfile is refused.

These tests are static-analysis only — they do NOT run pip. The
goal is to pin the contract:

* the lockfiles exist;
* every top-level requirement from the source ``.txt`` files is
  present in the corresponding ``.lock`` with at least one
  ``--hash=`` line;
* the CI workflow installs with ``--require-hashes`` from the
  lockfiles;
* the deploy script (``scripts/_common.sh``) does the same.

A package missing from the lock means the install would either
fail (good) or be picked up from PyPI without hash verification
(silently bad in a hypothetical migration path). Pinning the
existence here catches that drift in CI.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _toplevel_packages(req_text: str) -> set[str]:
    """Extract top-level package names from a ``requirements*.txt``
    file (the source-of-truth file with range pins). Strips comments
    and version specifiers, lowercases, normalises ``_`` -> ``-``.
    """
    names: set[str] = set()
    for line in req_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Drop extras (``[binary]``) and version-spec / comment chars —
        # ``psycopg[binary]>=3.1`` normalises to ``psycopg`` so it
        # matches the lockfile entry name (extras are not part of the
        # package identity for purposes of "is this top-level locked?").
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", stripped)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]*\])?==")


def _locked_packages(lock_text: str) -> set[str]:
    """Extract package names from a pip-compile lockfile. A pinned
    entry looks like ``alembic==1.18.4 \\`` or
    ``psycopg[binary]==3.3.4 \\`` (extras land between name and ``==``).
    """
    names: set[str] = set()
    for line in lock_text.splitlines():
        match = _PIN_RE.match(line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


# ---------------------------------------------------------------------------
# Lockfiles exist
# ---------------------------------------------------------------------------

def test_runtime_lockfile_exists():
    assert (ROOT / "requirements.lock").is_file(), \
        "requirements.lock missing; regenerate with " \
        "`pip-compile --generate-hashes --output-file=requirements.lock requirements.txt`"


def test_dev_lockfile_exists():
    assert (ROOT / "requirements-dev.lock").is_file(), \
        "requirements-dev.lock missing; regenerate with " \
        "`pip-compile --generate-hashes --allow-unsafe " \
        "--output-file=requirements-dev.lock requirements-dev.txt`"


# ---------------------------------------------------------------------------
# Every top-level dep is locked
# ---------------------------------------------------------------------------

def test_every_runtime_toplevel_is_locked():
    declared = _toplevel_packages(_read("requirements.txt"))
    locked = _locked_packages(_read("requirements.lock"))
    missing = declared - locked
    assert not missing, (
        f"top-level runtime packages missing from requirements.lock: "
        f"{sorted(missing)}. Regenerate the lock."
    )


def test_every_dev_toplevel_is_locked():
    declared = _toplevel_packages(_read("requirements-dev.txt"))
    locked = _locked_packages(_read("requirements-dev.lock"))
    missing = declared - locked
    assert not missing, (
        f"top-level dev packages missing from requirements-dev.lock: "
        f"{sorted(missing)}. Regenerate the lock."
    )


# ---------------------------------------------------------------------------
# Every locked package carries at least one --hash
# ---------------------------------------------------------------------------

def _hash_lines_by_package(lock_text: str) -> dict[str, int]:
    """Count ``--hash=sha256:...`` lines attributable to each
    ``foo==X.Y`` entry. We tally hashes appearing AFTER the pinned
    line and BEFORE the next pinned line.
    """
    counts: dict[str, int] = {}
    current: str | None = None
    for line in lock_text.splitlines():
        pin = _PIN_RE.match(line)
        if pin:
            current = pin.group(1).lower().replace("_", "-")
            counts[current] = 0
            # The pin line itself often ends with ``\`` and carries the
            # first hash on the next line; count only --hash= occurrences.
            if "--hash=" in line:
                counts[current] += line.count("--hash=")
            continue
        if current and "--hash=" in line:
            counts[current] += line.count("--hash=")
    return counts


def test_every_runtime_lock_entry_has_at_least_one_hash():
    counts = _hash_lines_by_package(_read("requirements.lock"))
    unhashed = sorted(name for name, n in counts.items() if n == 0)
    assert not unhashed, (
        f"runtime lockfile entries without a --hash= line: {unhashed}. "
        f"This breaks --require-hashes. Regenerate the lock with --generate-hashes."
    )


def test_every_dev_lock_entry_has_at_least_one_hash():
    counts = _hash_lines_by_package(_read("requirements-dev.lock"))
    unhashed = sorted(name for name, n in counts.items() if n == 0)
    assert not unhashed, (
        f"dev lockfile entries without a --hash= line: {unhashed}. "
        f"Regenerate the lock with --generate-hashes."
    )


# ---------------------------------------------------------------------------
# CI + deploy install with --require-hashes from the lockfiles
# ---------------------------------------------------------------------------

def test_ci_workflow_installs_with_require_hashes():
    ci = _read(".github/workflows/ci.yml")
    assert "--require-hashes" in ci, \
        "CI workflow does not pass --require-hashes; supply-chain check is off"
    assert "requirements.lock" in ci, \
        "CI workflow does not reference requirements.lock"
    assert "requirements-dev.lock" in ci, \
        "CI workflow does not reference requirements-dev.lock"


def test_deploy_script_installs_with_require_hashes():
    deploy = _read("scripts/_common.sh")
    assert "--require-hashes" in deploy, \
        "deploy install_python_deps() does not pass --require-hashes"
    assert "requirements.lock" in deploy, \
        "deploy install_python_deps() does not reference requirements.lock"


# ---------------------------------------------------------------------------
# pip-tools is in dev deps so contributors can refresh
# ---------------------------------------------------------------------------

def test_pip_tools_in_dev_deps():
    dev = _read("requirements-dev.txt")
    assert re.search(r"^pip-tools\b", dev, re.MULTILINE), \
        "pip-tools not in requirements-dev.txt; contributors cannot refresh the lock"
