# Architecture decisions (ADR-lite)

The durable "why" behind the template's shape, consolidated from session
handoffs. Each entry is lightweight: **Context / Decision / Consequences**.
For the fuller narrative and forward-looking assessment see
[`TECH_EVOLUTION.md`](TECH_EVOLUTION.md).

Add a new entry when a choice would otherwise only be recoverable by
reading a dated handoff. Do not rewrite history — supersede with a new
entry and note it.

---

## 1. Django, not FastAPI — and Django 5.2 LTS

- **Context**: the template targets real-user apps (auth, MFA, admin,
  audit) that value a batteries-included framework and long security
  support. A pre-Django FastAPI lineage existed.
- **Decision**: Django-first, ASGI via Uvicorn, no FastAPI runtime. Pin to
  **Django 5.2 LTS** (security support to ~2028). **Django 6.0 declined
  2026-07-02** — non-LTS, and it would force dropping Python 3.11 for no
  offsetting benefit.
- **Consequences**: CI matrix runs Python 3.11–3.14 on 5.2 LTS. Revisit at
  the next Django LTS (6.2, ~Dec 2026). The `-django` version suffix marks
  this generation.

## 2. Server-rendered HTML + vanilla JS, no build step

- **Context**: interactivity is modest (profile, admin panel, MFA, avatar
  cropper). A SPA/bundler would add a toolchain and a doc-rot surface.
- **Decision**: Django templates + hand-written vanilla JS in
  `static/js/*.js`, served from `'self'` with SRI. **No build step.** If
  interactivity grows, reach for HTMX/Alpine before a SPA.
- **Consequences**: `node` is used only to run the `node:test` unit tests,
  not to build. JS ships as-is; `{% sri_for %}` hashes at render time.

## 3. Static-asset config via `data-*` on a hidden element

- **Context**: the 2026-07-03 inline-JS split moved ~1130 lines out of
  templates into external `.js`. External scripts can't read Django
  template context or inline nonced config directly.
- **Decision**: inject per-page config (URLs, CSRF token) as `data-*`
  attributes on a hidden `#*-js-config` element the script reads on load —
  not `json_script` and not a nonced inline blob.
- **Consequences**: CSP stays `script-src 'self'` (no per-page nonce for
  app JS); the script is cacheable and SRI-pinned.

## 4. PostgreSQL (prod) / SQLite (dev); Django ORM is the only ORM

- **Context**: production needs a real RDBMS; local dev benefits from a
  zero-setup fallback. An early lineage used a thin SQLAlchemy engine for
  a `SELECT 1` health probe.
- **Decision**: PostgreSQL in production, SQLite for local/dev and e2e,
  with the **Django ORM as the single schema owner**. SQLAlchemy was
  removed (its ~5 MB bought one 7-line health probe with no other
  consumer) in favour of Django's `connection.cursor()` — see
  `ameli_app/database.py`. The DSN parser tolerates SQLAlchemy-style
  schemes (`postgresql+psycopg://`) so operators can reuse such URLs.
- **Consequences**: migrations are Django's; there is no Alembic. The CI
  `test-postgres` job (2026-07-06) validates the suite on real Postgres.
  `*.sqlite3` is gitignored.

## 5. Dependency minimalism

- **Context**: every dependency is a supply-chain and maintenance surface.
- **Decision**: prefer hand-rolled over a library when the surface is
  small and well-understood — e.g. the Prometheus exposition and the CSP
  header are built in-repo rather than pulling `django-prometheus` /
  `django-csp`.
- **Consequences**: fewer transitive deps in the hash-pinned lock; the
  logic is ours to test (and it is).

## 6. Security posture

- **Context**: internet-exposed, real-user app; ASVS L2 target.
- **Decision**: per-request **CSP nonces** + **Trusted Types**
  (`ameli-template` policy) + **SRI** on own assets; hash-pinned
  dependency locks installed with `--require-hashes` (ASVS V14.2.3);
  hash-chained audit log with HMAC. Avatar uploads are AV-scanned and
  **EXIF/GPS-stripped** (D-5).
- **Consequences**: adding third-party JS/CSS requires an SRI hash and a
  CSP allowance. See [`SECURITY.md`](SECURITY.md),
  [`THREAT_MODEL.md`](THREAT_MODEL.md) and the ASVS snapshot.

## 7. Template update propagation — git upstream + releases (not a package, yet)

- **Context**: this repo is a **Core template**; new AMELI apps are born
  by copying it and then diverging. When the Core improves — above all
  **security fixes** (e.g. the Django 5.2.16 CVE patch, v0.5.2) — those
  child apps need a way to (a) *know* an update exists and (b) *pull* it.
  Three models were weighed: **A** git upstream remote (cherry-pick /
  merge), **B** a Copier template (`copier update`, 3-way merge), **C**
  extracting the shared Core into a versioned `ameli-core` pip package
  (updates via `pip install -U` + Dependabot).
- **Decision**: adopt **model A** for now. Child apps add this repo as a
  `template` remote and **cherry-pick** security fixes (surgical) or
  **merge** `template/main` for a broad catch-up; each records its
  *template lineage* (the `vX.Y.Z-django` release it last synced to). The
  **query channel** is the per-promotion **GitHub Release + tag** (already
  published) — checkable via `gh release view` / the `releases.atom` feed.
  Model B (Copier) and **model C (`ameli-core` package) are explicitly
  deferred**, not rejected: C is the strongest channel (semver + auto-PRs)
  but a large refactor that turns the "copy-and-customize template" into a
  "install-and-extend library". The how-to lives in
  [`BUILDING_NEW_APP.md`](BUILDING_NEW_APP.md) §6.
- **Consequences**: propagation is **manual** and conflict-prone in
  proportion to how much a child app touched the Core — which is *why*
  `BUILDING_NEW_APP.md` §4 ("what you MUST NOT touch") matters: the less a
  fork edits the Core, the cheaper every future upstream pull. Security
  fixes must ship as **tagged releases with a security note** so a child
  operator can triage fast. Revisit → **model C** once the fleet is large
  enough that manual merges cost more than the packaging refactor.
