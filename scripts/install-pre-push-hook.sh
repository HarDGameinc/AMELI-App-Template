#!/usr/bin/env bash
# Install the pre-push hook that refuses direct push to main.
#
# Idempotent: re-running over an existing hook is fine; the file
# is overwritten with the latest template version. If the operator
# has a custom local hook, we DO NOT clobber it -- they must
# resolve manually.
#
# Run once after cloning. The hook does NOT travel with the repo
# (git refuses to install hooks for security reasons), so every
# checkout needs this step. CONTRIBUTING-style docs point at this
# script.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/deploy/git-hooks/pre-push"
DEST_DIR="${ROOT}/.git/hooks"
DEST="${DEST_DIR}/pre-push"

if [[ ! -d "${DEST_DIR}" ]]; then
    echo "ERROR: ${DEST_DIR} not found. Run from a git checkout." >&2
    exit 1
fi

if [[ -f "${DEST}" ]] && ! diff -q "${SRC}" "${DEST}" >/dev/null 2>&1; then
    # Existing file differs from the template. Preserve it.
    if ! grep -q "deploy/git-hooks/pre-push" "${DEST}" 2>/dev/null; then
        echo "WARN: ${DEST} exists and is not the template hook." >&2
        echo "      Existing content preserved; merge manually if needed." >&2
        exit 1
    fi
fi

install -m 0755 "${SRC}" "${DEST}"
echo "[install-pre-push-hook] installed ${DEST}"
