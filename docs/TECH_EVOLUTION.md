# Technical evolution assessment

Date: `2026-07-03`
Scope: whether the template's tooling/stack choices are sound, what to
keep, and where (and where NOT) to evolve. Written as a reference for the
operator and future agents — a companion to `ARCHITECTURE.md` and the
roadmap in the latest `CLAUDE_HANDOFF_*`.

## TL;DR

The stack is **well-chosen and internally coherent**. There is no
"you're doing it wrong, migrate to X." The template's philosophy —
*minimal dependencies, boring/stable tech, security-first, LTS, no build
step* — is the right fit for a security-sensitive, single-operator,
internal operational app that **other apps inherit**. The valuable
evolution here is **surgical, not a rewrite**. The single highest-value
change is running the test suite against **PostgreSQL in CI** (today CI
and local run on SQLite while prod is Postgres).

## Design philosophy (why the stack is what it is)

The choices below are deliberate, not accidental, and mutually
reinforcing:

- **Django 5.2 LTS + PostgreSQL + ASGI (Uvicorn)** — a responsible floor
  with support through 2028. FastAPI was intentionally excluded (Django
  ASGI covers the need).
- **Server-rendered templates + vanilla JS, no build step** — no npm /
  bundler / `node_modules` in the runtime path, which keeps the CVE
  surface small and the CSP posture simple.
- **Dependency minimalism** — Prometheus exposition and CSP are
  hand-rolled to avoid `prometheus_client` / `django-csp`; the lockfiles
  are hash-pinned (`--require-hashes`, ASVS V14.2.3).
- **Security-first** — per-request CSP nonces + Trusted Types + SRI,
  argon2, MFA (TOTP + email), hash-chained audit log, atomic throttling,
  ASVS L2 mapping, ruff `S` + bandit + pip-audit in CI.

This posture is **more rigorous than most production apps**. The tooling
is current (ruff, mypy, pytest, Playwright, OpenTelemetry).

## Keep — genuine strengths, do not touch

- The Django LTS + Postgres + server-rendered core.
- The whole security stack (CSP/Trusted Types/SRI, argon2, MFA, audit
  chain, hash-pinned locks). This is the template's differentiator.
- The modern lint/type/test toolchain.

## Where a framework would be a regression

- **Frontend SPA (React / Vue / Svelte)** — a step backwards *for this
  project*. It would add a build step (bundler + `node_modules` = large
  CVE surface), fight or complicate the CSP-nonce / Trusted-Types / SRI
  posture, and add ceremony for a mostly-CRUD UI (profile + admin panel).
  The server-rendered + vanilla-JS approach (now split into external
  SRI-protected `static/js/*.js`, 2026-07-03) is the correct shape.
  - **If interactivity grows**, the evolution that fits the philosophy is
    **HTMX** or **Alpine.js**: server-rendered HTML, no build step, tiny
    footprint, and friendlier to the CSP model than a SPA. That is the
    sane "framework upgrade" path — not a SPA.
- **FastAPI** — already excluded on purpose; Django ASGI is enough.
- **Django 6 (non-LTS)** — explicitly declined 2026-07-02. A template
  that other apps inherit should sit on LTS. Do not chase it.

## Targeted opportunities (ranked by value / cost)

| Priority | Item | Rationale |
|---|---|---|
| **High** | **PostgreSQL in CI** | CI + local run on **SQLite**; prod is **Postgres**. Behaviours diverge — e.g. `select_for_update()` (the throttling gate) is a real row lock on Postgres and a near-no-op on SQLite; transaction / constraint / isolation semantics differ. A GitHub Actions job with a `services: postgres` container closes the gap. Low cost, high value. |
| **Medium** | **Remove unused SQLAlchemy / Alembic** | Configured but with no active models; `AGENTS.md` already lists it under "what not to port." Django ORM + Django migrations are the real system. Dead weight that confuses new readers and adds dependency surface — remove it, or document explicitly why it stays. |
| **Low / optional** | `django-csp` + `prometheus_client` | The hand-rolled versions are deliberate (dependency-free) and fine today. If maintaining them becomes a burden as the app grows, these mature libraries reduce upkeep. A trade-off, not urgent. |
| **Low / optional** | **Ansible** for provisioning | The bash + systemd scripts work and are auditable, but bash is fragile (this project hit a Windows `tar` path issue and the `validate_installation.sh` `APP_ENV=prod` default gotcha). For single-operator internal deploys, bash is defensible; if deploys scale, Ansible adds idempotence and testability at the cost of a new toolchain. |
| **Low** | **Frontend JS unit tests beyond pure helpers** | `node:test` covers the pure helpers (D-4); DOM-wiring paths are e2e-only. A jsdom layer could unit-test wiring, but the Playwright e2e coverage is arguably sufficient. Low priority. |

## Recommendation

If only one thing is done next: **PostgreSQL in CI**. It is the one real
quality gap (the suite is validated against a different backend than
production), it is cheap, and it matches the rigor the project already
has. Second would be the SQLAlchemy/Alembic cleanup.

## Explicitly do NOT

- Add a SPA / frontend build pipeline.
- Migrate to Django 6 (non-LTS) or add FastAPI.
- Replace the hand-rolled security primitives with heavier frameworks
  "because they're standard" — the current posture is a feature.

The template is not behind on tooling; it is **ahead on the tooling that
matters** (security, reproducibility). The next step is closing the two
or three targeted gaps above, not changing the stack.
