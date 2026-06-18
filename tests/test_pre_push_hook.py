"""Regression coverage for the pre-push hook + main-push-audit
workflow that substitute for branch protection on a private +
Free-plan repo.

Context (roadmap #23 follow-up): GitHub's server-side branch
protection (both classic Rules and new Rulesets) does NOT enforce
on private repos under the Free plan. The repo `main` branch is
guarded client-side by ``deploy/git-hooks/pre-push`` and
server-side-but-detection-only by
``.github/workflows/main-push-audit.yml``.

These tests pin the contract by static analysis — no actual git
push, no actual workflow run.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _is_executable(path: str) -> bool:
    return os.access(ROOT / path, os.X_OK)


# ---------------------------------------------------------------------------
# Hook file exists, executable, refuses main
# ---------------------------------------------------------------------------

def test_pre_push_hook_exists():
    assert (ROOT / "deploy" / "git-hooks" / "pre-push").is_file()


def test_pre_push_hook_is_executable():
    assert _is_executable("deploy/git-hooks/pre-push"), \
        "pre-push hook must be executable; chmod +x deploy/git-hooks/pre-push"


def test_pre_push_hook_blocks_main():
    body = _read("deploy/git-hooks/pre-push")
    assert "PROTECTED_BRANCHES=" in body
    assert '"main"' in body
    assert "Direct push to '${protected}' refused" in body


def test_pre_push_hook_documents_bypass():
    """The hook MUST expose an env-var bypass so a legit emergency
    push (rollback, etc.) is possible without editing the hook
    file. The audit workflow records the override.
    """
    body = _read("deploy/git-hooks/pre-push")
    assert "ALLOW_DIRECT_PUSH" in body


# ---------------------------------------------------------------------------
# Install script
# ---------------------------------------------------------------------------

def test_install_script_exists_and_executable():
    assert (ROOT / "scripts" / "install-pre-push-hook.sh").is_file()
    assert _is_executable("scripts/install-pre-push-hook.sh")


def test_install_script_does_not_clobber_unknown_hook():
    """If a developer already has a custom pre-push hook, the
    installer must NOT overwrite it blindly. Pin via the
    diff-then-grep gate in the script.
    """
    body = _read("scripts/install-pre-push-hook.sh")
    assert "diff -q" in body
    assert "WARN: ${DEST} exists and is not the template hook" in body


# ---------------------------------------------------------------------------
# Audit workflow
# ---------------------------------------------------------------------------

def test_main_push_audit_workflow_exists():
    assert (ROOT / ".github" / "workflows" / "main-push-audit.yml").is_file()


def test_audit_workflow_only_runs_on_main():
    body = _read(".github/workflows/main-push-audit.yml")
    assert "branches: [main]" in body


def test_audit_workflow_distinguishes_merge_from_direct_push():
    body = _read(".github/workflows/main-push-audit.yml")
    # Heuristic: HEAD with 2+ parents = merge commit.
    assert "rev-list --parents -n 1 HEAD" in body
    assert "Direct push to main detected" in body
