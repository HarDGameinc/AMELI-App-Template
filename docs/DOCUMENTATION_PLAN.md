# Documentation plan (to integrate before next dev cycle)

Date: `2026-07-03`
Status: **DONE (2026-07-06)** — Core 3 created: [`CONTRIBUTING.md`](../CONTRIBUTING.md)
(root), [`RELEASE.md`](RELEASE.md), [`DECISIONS.md`](DECISIONS.md), all
registered in the `AGENTS.md` documentation index. Optional `SBOM.md` /
`PRIVACY.md` deferred (create when going productive/critical). This plan
is kept as the record of what was scoped and why.
Context: an external recommendation proposed a ~35-file "industry
standard" doc set. This is the tailored plan: adopt only the genuine
gaps, consolidate instead of proliferating. Full reasoning in the
2026-07-03 handoff (§ conversation) and `TECH_EVOLUTION.md`.

## Guiding principle

Few rich, maintained docs > many thin ones. Every `X.md` is a doc-rot
surface an agent will trust. **Before creating a doc, ask "does this
already live in `OPERATIONS.md` or `AGENTS.md`?"** — usually yes, and the
right move is a section there, not a new file. The repo already covers
~70% of the proposed set, consolidated into fewer, denser docs.

## Do NOT create (already covered or N/A)

- **Covered elsewhere** — QUICKSTART/INSTALL (`FIRST_INSTALL_DJANGO.md`),
  DEPLOYMENT (`OPERATIONS.md` + `TLS_WITH_CADDY.md`), OBSERVABILITY /
  BACKUP_RESTORE / TROUBLESHOOTING / RUNBOOK / MAINTENANCE (sections in
  `OPERATIONS.md`), COMPLIANCE (`COMPLIANCE_ASVS_L2_*`), USAGE
  (`README.md`), API (self-documented via `/openapi.json` + `/docs` +
  `/redoc`), DATABASE (models in `AGENTS.md`), INTEGRATIONS
  (`OPERATIONS.md` + `settings/integrations.py`), DESIGN
  (`FRONTEND_DESIGN_REVIEW.md`).
- **Redundant with `AGENTS.md`** — AI_CONTEXT.md, AGENT_WORKFLOWS.md.
  `AGENTS.md` IS the AI entry point; duplicating fragments the source of
  truth.
- **N/A for a single-operator template** — SUPPORT.md, GOVERNANCE.md,
  PROMPTS.md (marginal), SLSA.md (overkill unless a client mandates it),
  DATA_HANDLING.md (fold into PRIVACY).

## Create — the genuine gaps (ranked)

### 1. `CONTRIBUTING.md`  *(highest value)*

Operating conventions currently live only in dated handoffs (§8.2), which
are historical logs — a future agent reading `AGENTS.md` alone does not
get them reliably. Seed with:

- **Commits**: Conventional Commits; footer
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. No
  `--no-verify` / hook skipping.
- **Branches**: work on `dev`; the server always pulls `dev`; `main` is the
  release branch (promoted to `v0.5.0-django` on 2026-07-07) and advances
  only by PR from `dev` with green CI, by explicit operator instruction.
- **Pre-push checks**: `ruff check .` · `mypy src` · `pytest` ·
  `node --test tests/js/*.test.js`.
- **Windows dev notes** (pointer): install from the ranges (not the
  hash-locked `requirements.lock` — `uvloop` won't compile on Windows);
  reinstall mypy with `--no-binary mypy` (App-Control blocks the DLL);
  local run env vars (`AMELI_APP_DJANGO_SECRET_KEY`, `DATABASE_URL=""`,
  `AMELI_APP_SQLITE_PATH`, `APP_CONFIG`, `DJANGO_SETTINGS_MODULE`).

Consider making this a **section in `AGENTS.md`** instead of a separate
file (put it where agents already read first) — decide at execution time.

### 2. `RELEASE.md`  (folds in VERSIONING)

- **Scheme**: `vMAJOR.MINOR.PATCH-django` in the `VERSION` file, mirrored
  as `MAJOR.MINOR.PATCH` in `pyproject.toml`. Runtime reads it via
  `src/ameli_app/version.py`.
- **Bump ritual — all four**: `VERSION` + `pyproject.toml [project].version`
  + a `CHANGELOG.md` entry + the `AGENTS.md` "State of the project" line.
- **Policy**: bump only after a phase / roadmap item is validated on the
  dev server (`ha-report2`). A behaviour-neutral refactor that ships new
  browser-served assets may still get a marker bump (precedent: v0.4.9).

### 3. `DECISIONS.md`  (ADR-lite)

Consolidate the "why" that is scattered across handoffs. Format: one
lightweight ADR per entry (Context / Decision / Consequences); point to
`TECH_EVOLUTION.md` for the fuller narrative. Seed entries:

- Django (not FastAPI); Django **5.2 LTS** (Django 6 non-LTS declined
  2026-07-02).
- Server-rendered + vanilla JS, **no build step**; HTMX/Alpine if
  interactivity grows (not a SPA).
- PostgreSQL (prod) / SQLite (dev fallback); **SQLAlchemy/Alembic
  configured-but-unused** → candidate for removal.
- Dependency minimalism: hand-rolled Prometheus exposition + CSP.
- Security posture: per-request CSP nonces + Trusted Types + SRI;
  hash-pinned locks (`--require-hashes`).
- Static-asset config injection via `data-*` on a hidden element (not
  `json_script` / view context) — from the 2026-07-03 JS split.

## Create only if going "productive / critical"

- ~~**`SBOM.md`**~~ **DONE (2026-07-12)** — consolidated, not a new file:
  [`OPERATIONS.md`](OPERATIONS.md) → "Lockfile / supply chain" now has an
  "### SBOM (CycloneDX)" subsection. Generated with `pip-audit -f
  cyclonedx-json` (no new dep — already a dev dep + CI job); refresh on lock
  change / per release; artifact attached to the GitHub release, not
  committed (`*.cdx.json` gitignored).
- ~~**`PRIVACY.md`**~~ **DONE (2026-07-17)** — [`docs/PRIVACY.md`](PRIVACY.md).
  Data inventory (User/UserSession/MFA*/OutboundEmail/EmailChange/audit),
  retention windows (from `services/retention.py`), confidentiality controls
  (argon2/Fernet/salted_hmac/HMAC-chain/EXIF-strip), user rights (access,
  rectification, self-service erasure via `/profile/delete-account/`), and
  the deploy-specific gaps (legal basis, DPO, portability). Trigger: the
  Starlink child app handling real user + telemetry data.

## Execution notes for the next session

- Do this **before** the next feature work (operator's instruction).
- Register any new files in the `AGENTS.md` documentation index.
- Keep each doc concise and **link to existing docs instead of copying**
  (e.g. RELEASE points at CHANGELOG; CONTRIBUTING points at OPERATIONS
  "Local validation"). Duplicated content is the failure mode to avoid.
- When done, delete this plan or mark it `Status: DONE`.
