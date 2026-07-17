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

## 8. Dev-environment tiers — Windows daily, WSL2 for parity, Docker out of the loop

> **Superseded by #9 (2026-07-17, same day).** #8 framed a tiered
> Windows/WSL2 model that forces double work (two venvs, two locks,
> two suites kept in manual sync) — the opposite of the intent. Kept
> here for the audit trail; the current strategy is in **#9**.

- **Context**: the dev workstation is **native Windows**, which has only
  partial Linux parity: `uvloop` is POSIX-only (so the local venv installs
  from the *ranges*, pulling Django 6 / Pillow 12 locally vs the pinned
  `5.2.16` that ships), ~18 shell/systemd/backup tests `skipif(win32)`, and
  mypy's compiled DLL is blocked by Windows App Control. Docker Desktop was
  weighed for full parity but is **expensive in an agent-driven loop**: on
  Windows it already runs a WSL2 VM *plus* an image layer, C-extension
  wheels rebuild on image changes, and cross-filesystem bind mounts
  (Windows ↔ container, the `:cached` hint) are slow — rebuilds burn
  time/plan budget the moment Docker enters the inner loop.
- **Decision**: a **tiered** dev environment, not one tool for everything.
  1. **Windows direct = the default daily loop** (app `src/` code + tests).
     Cheapest and fastest; the Linux CI (full matrix + e2e + `test-postgres`)
     is authoritative for the win32-skipped tests and lock/`uvloop` parity.
  2. **WSL2 (native Linux) = Linux parity on demand** — run the shell/systemd
     tests, install the hash-pinned lock with `uvloop`, or build Docker far
     faster than Docker Desktop's Windows path. **Clone into the Linux
     filesystem (`~/…`), never `/mnt/c/…`** (the cross-fs I/O is the same
     slowdown as a bind mount); keep it in sync via plain `git pull`.
  3. **Docker stays OUT of the routine/agent loop** — it validates the
     *Docker artifacts themselves*, not day-to-day app work.
     `test_docker_stack.py` (parses the manifests, no build) + CI are the
     routine guard; the Dockerfile/compose get an end-to-end build only
     occasionally/manually (e.g. the v0.5.7 §5 fixes were validated this way,
     without a local build).
- **Consequences**: the Windows dep/skip drift is **accepted** — the suite is
  green on both stacks and CI is the source of truth for Linux-only paths.
  Agent sessions should **not** spin up Docker in the inner loop; reserve
  builds for artifact validation. WSL2 is the recommended second environment
  when parity is needed (setup: `wsl --install -d Ubuntu-24.04`, a Linux-fs
  clone, then a venv from **both** locks — `requirements.lock` (runtime:
  `uvicorn[standard]`, `uvloop`, …) **and** `requirements-dev.lock` (tooling:
  pytest, ruff, mypy, …). They are **complementary, not superset/subset**;
  `django` appears in both only because `pytest-django` pulls it). Verified
  2026-07-16: the Linux suite runs **1156 passed / 28 skipped** vs Windows'
  1126 / 58 — the ~30 extra are the shell/systemd/backup tests win32 skips.
  See `CONTRIBUTING.md` "Windows notes" and the `windows-local-dev-env` memory. Revisit if the primary dev machine
  moves to Linux — then native/WSL2 becomes the default and the Windows
  caveats disappear.

## 9. Dev environment — WSL2 primary, single loop (supersedes #8)

- **Context**: #8 (same day, earlier) framed the environment as tiered —
  Windows daily loop with WSL2 for parity — which forces **double work**:
  two venvs, two locks, two suites, two divergent dep sets kept in sync
  manually. That is the opposite of the intent. The actual goal is a
  single dev environment that matches production and eliminates the
  Windows/Linux drift entirely.
- **Decision**: **WSL2 Ubuntu 24.04 is THE dev environment** — one clone,
  one venv, one loop.
  1. **Dev + tests + local deployment all live in WSL2**, per-machine at
     `/home/hardg/ameli-app-template` (Linux fs). The venv installs from
     **both** hash-pinned locks — `requirements.lock` (runtime:
     `uvicorn[standard]`, `uvloop`, `httptools`) and `requirements-dev.
     lock` (tooling: pytest, ruff, mypy, pip-audit). They are
     **complementary, not superset/subset**; `django` overlaps only
     because `pytest-django` pulls it. Same dependency set the prod
     deploy ships — no Windows drift, no version games.
  2. **Local deployment lives here too.** WSL2 emulates the production
     server directly — same `python -m ameli_app.api` under uvicorn,
     against a local Postgres in the same WSL — as the pre-promotion
     smoke. Faster than round-tripping to `ha-report2` for every change
     and matches the prod code path (no container layer between the code
     and the runtime). **Docker is not used locally.** The `docker
     compose up` path documented in the repo remains valid for anyone
     who wants it (and would run inside WSL2 native, not via Docker
     Desktop — the "expensive Docker" complaint in #8 was specific to
     Docker Desktop bridging Windows ↔ container filesystems), but this
     operator does not adopt it. `test_docker_stack.py` + CI stay as the
     anti-drift guard on the Docker artifacts themselves.
  3. **Production = Linux VM (`ha-report2`)**, deployed via `git pull` +
     systemd restart. Unchanged; the change is only "which local
     environment feeds it".
  4. **Windows-native venv is fallback only** — kept during the
     transition for the mypy-DLL edge case (see `mypy-windows-dll-block`
     memory) and quick emergency edits when WSL is unreachable. Not the
     daily loop. Will be archived / deleted once the WSL flow is stable.
  5. **Editing from Windows-side tools reaches WSL** via the UNC path
     `\\wsl.localhost\Ubuntu-24.04\home\hardg\ameli-app-template\` (VS
     Code with Remote-WSL opens it transparently). Terminals run inside
     WSL. The Windows path `C:\Users\hardg\AMELI APPS\AMELI_APP_TEMPLATE`
     is treated as archived — do not edit it after the migration; the
     canonical copy of any change lives in the WSL clone.
  6. **Multi-machine collaboration**: `origin` (GitHub) is the sole
     shared canonical. Each machine (a second laptop, a colleague,
     anything) installs WSL2 + its own Linux-fs clone; sync is by
     `git push`/`git pull` — same as any repo. WSL2 changes nothing
     about the collaboration model.
- **Consequences**:
  - **No dep drift** — the local venv installs the same hash-pinned lock
    that ships to production. Bugs that only reproduce with `uvloop` /
    `django==5.2.16` surface locally instead of in CI.
  - **No double work** — one venv, one suite, one edit path, one set of
    dependencies. When a lock changes, exactly one env needs the update.
  - **Docker is cheap again** — inside WSL2 it does not carry the Docker
    Desktop overhead; `docker compose up` for local pre-prod smoke is a
    normal step. `test_docker_stack.py` + CI stay as the anti-drift
    guard on the Docker artifacts themselves.
  - **Windows-native venv is deprecated** — a follow-up will remove
    `.venv` from the Windows clone once the migration is confirmed. The
    `windows-local-dev-env` memory notes the shift and points here.
  - **This supersedes #8.** #8 shipped in `v0.5.8-django` before the
    correction; #9 is what the flotilla should adopt going forward.
    Whether a corrective `v0.5.9` is cut or #9 folds into the next
    release is per-session judgment (a fresh child app onboarding today
    would consume the wrong strategy from `v0.5.8`, which argues for a
    quick tag).
