# Releasing

How versions are numbered and bumped. Consolidates the ritual that was
scattered across session handoffs.

## Version scheme

- **`VERSION`** file holds the canonical string: `vMAJOR.MINOR.PATCH-django`
  (e.g. `v0.4.9-django`).
- **`pyproject.toml`** `[project].version` mirrors it without the `v`
  prefix or `-django` suffix: `MAJOR.MINOR.PATCH` (e.g. `0.4.9`).
- **Runtime** reads the string via
  [`src/ameli_app/version.py`](../src/ameli_app/version.py)
  (`get_version()` reads the `VERSION` file; falls back to `v0.0.0-dev`).
  Exposed as `ameli_app.__version__` and surfaced at `/health`.

The `-django` suffix marks the current Django-first generation of the
template (there was a pre-Django lineage).

## Bump ritual — update all four

A release bump touches exactly these, in one `chore(release):` commit:

1. **`VERSION`** — the new `vX.Y.Z-django` string.
2. **`pyproject.toml`** — `[project].version = "X.Y.Z"`.
3. **`CHANGELOG.md`** — a new top section for the version, dated, listing
   the commits/changes it ships.
4. **`AGENTS.md`** — the "State of the project (vX.Y.Z-django, DATE)"
   heading + one-line summary.

Keeping these four in sync is a hard rule enforced by discipline, not
tests: nothing currently asserts `VERSION` == `pyproject.toml` version, so
a mismatch ships silently. Update all four in the same commit. (A tiny
consistency test would be a cheap future safeguard.)

## When to bump

- **Bump only after the change is validated on the dev server**
  (`ha-report2`) — not on green local tests alone. The handoff records the
  server validation (smoke, `validate_installation.sh`, `verify-audit`).
- One bump per **phase / roadmap item**, not per commit. A cluster of
  commits that close one item share a single bump.
- A **behaviour-neutral refactor may still get a marker bump** when it
  ships new browser-served assets or changes the deploy surface — e.g.
  `v0.4.9` for the inline-JS → `static/js/*.js` split. The marker lets the
  server's `/health` version confirm the deploy landed.

## Changelog

`CHANGELOG.md` is the human-facing history; keep entries in Spanish (team
language) with English code/commit references. Each version section links
back to the commits it bundles. See the existing entries for the shape.

## Promotion to `main`

`main` is the release branch. It was promoted to **`v0.5.0-django`** on
2026-07-07 (the first release; previously frozen until this milestone) and
advances only by PR from `dev` with green CI, by explicit operator
instruction (see [`CONTRIBUTING.md`](../CONTRIBUTING.md) and the promotion
checklist in [`docs/HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) §S-08).

Reference promotion (v0.5.0, 2026-07-07): bump on `dev` → PR `dev → main`
→ wait for green CI (`gh pr checks <n> --watch`) → **merge commit** (not
squash, to preserve history) → tag + GitHub release `vX.Y.Z-django` on
`main`.
