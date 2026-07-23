# Operations

## Deployed instance — ground truth (never guess)

> **For any AI or operator touching a server: derive the instance facts,
> do not hardcode or guess them.** Service names, paths and ports are
> **computed**, not fixed — guessing `ameli-app-web.service` or `/opt/ameli`
> will target the wrong unit. There are two sources of truth:

1. **`scripts/_common.sh`** derives every path and unit name from
   `APP_INSTANCE` (= `APP_SLUG-APP_ENV`, e.g. `ameli-app-template-dev`).
   `resolve_systemd_profile()` picks which services/timers are enabled from
   `APP_SYSTEMD_PROFILE` — so *which* process is served is profile-dependent.
2. **`scripts/validate_installation.sh`** runs those on the box and prints
   `[OK]/[WARN]/[FAIL]` for paths, config, DB, `manage.py check`, and every
   enabled service/timer unit. **Run it first** — it *tells you* the real
   unit names instead of you guessing:
   ```bash
   cd "$APP_DIR" && APP_ENV=<env> bash scripts/validate_installation.sh
   ```

### Live deployment ground truth — derived on the box, not committed

The concrete facts of any live deployment (host, public URL, resolved paths,
service/timer unit names, bound ports) are **intentionally not hardcoded in
this public repo** — they are operational-reconnaissance detail an operator
keeps in a private ops note, not something a template consumer needs. This is
exactly why the two sources of truth above exist: **derive them on the box**
rather than reading them here.

```bash
cd "$APP_DIR" && APP_ENV=<env> bash scripts/validate_installation.sh
```

`validate_installation.sh` prints the resolved `APP_INSTANCE`, the real paths,
DB status, the `manage.py check` result, and every enabled service/timer unit
— the same facts that would otherwise be tabulated here, but computed live so
they can never drift. With the default slug the instance resolves to
`APP_SLUG-APP_ENV` (e.g. `<slug>-dev`), the API binds loopback-only on
`DEFAULT_API_PORT` behind the TLS reverse proxy, and the served unit is
`<instance>-api.service` (the `-web` unit ships disabled under the
`api-worker-maintenance` profile — **do not restart `-web`**).

Deploy + restart commands live in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) → "Deploying to the dev server". The
bump ritual is in [`RELEASE.md`](RELEASE.md).

## Local validation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
pytest
ruff check .
ruff format --check .
python manage.py migrate --noinput
python manage.py check
```

### Pre-commit hooks (Phase 1 #1, 2026-06-20)

`.pre-commit-config.yaml` ships with hooks that run on every
`git commit`:

* **ruff** (lint + auto-fix + format) — same rule set as CI.
* **detect-secrets** — refuses to commit a value that looks like
  a credential; baseline at `.secrets.baseline` lists known-OK
  fixtures.
* **trailing-whitespace / end-of-file-fixer / check-yaml /
  check-toml / check-merge-conflict / check-added-large-files**.

Install once per checkout (hooks do NOT travel with the repo):

```bash
pre-commit install
# -> pre-commit installed at .git/hooks/pre-commit
```

After install, every `git commit` runs the hooks. Bypass with
`git commit --no-verify` for the one-off (CI catches what is
bypassed locally anyway). Refresh the secrets baseline after
an intentional new fixture:

```bash
detect-secrets scan > .secrets.baseline
git add .secrets.baseline
```

### Code coverage (Phase 1 #2, 2026-06-20)

`coverage` measures line + branch coverage of `src/` against the
`tests/` suite. The floor is pinned at **85%** in
`pyproject.toml` (`[tool.coverage.report].fail_under`). A
regression that deletes production code without replacing the
test trips CI on the next push.

Local invocation:

```bash
coverage run -m pytest -q
coverage report          # text summary, exits non-zero if <85%
coverage html            # browseable HTML at htmlcov/index.html
```

Baseline at sprint closeout (2026-06-20): **85% with branch
coverage on**. Raise `fail_under` proportionally as new tests
land; never lower it.

The preferred local path is to set `DATABASE_URL` to PostgreSQL. If no local
database is available yet, SQLite can be used temporarily through
`AMELI_APP_SQLITE_PATH`.

## Linux install

```bash
APP_ENV=dev APP_SLUG=ameli-new-app APP_PACKAGE=ameli_new_app bash scripts/install.sh
```

The installer preserves `/etc/<instance>/app.env` and `/etc/<instance>/app.yaml`
if they already exist, creates the virtualenv, installs dependencies, runs
`manage.py migrate`, runs `manage.py check` and optionally bootstraps the first
superadmin. A real server install is expected to have `DATABASE_URL` pointing
to PostgreSQL.

## Lockfile / supply chain (ASVS V14.2.3)

The deploy and CI install runtime + dev deps from
`requirements.lock` / `requirements-dev.lock` with
`pip install --require-hashes`. Each entry in those files carries one
or more `--hash=sha256:...` lines so a rotated wheel on PyPI or a
typosquat that satisfies the source range never silently lands on the
host.

Refresh the lockfiles after editing `requirements*.txt`:

```bash
# from the project root, inside an env that has pip-tools
pip-compile --generate-hashes --output-file=requirements.lock requirements.txt
pip-compile --generate-hashes --allow-unsafe \
    --output-file=requirements-dev.lock requirements-dev.txt

git diff --stat requirements*.lock   # sanity-check what moved
```

`pip-tools` (which ships `pip-compile`) is declared in
`requirements-dev.txt`, so a normal dev install has it. The
`--allow-unsafe` flag on the dev lock is required because `pip` /
`setuptools` are themselves dependencies of pip-tools and would
otherwise be flagged as "unsafe to pin".

Sanity-test the lock locally before pushing:

```bash
python -m venv /tmp/lock-check
/tmp/lock-check/bin/pip install --upgrade pip
/tmp/lock-check/bin/pip install --require-hashes -r requirements.lock
```

A mismatched hash exits non-zero with the offending wheel's URL —
that is the expected behaviour and the protection the lock buys you.

### SBOM (CycloneDX)

Produce a CycloneDX software bill of materials from the hash-pinned deps —
one artifact that both inventories every shipped component and flags known
CVEs, because `pip-audit` (already a dev dep + a CI job) emits CycloneDX
natively (no extra tool):

```bash
# (A) RELEASE artifact — from the lock = exactly what ships. Attach THIS
#     to the GitHub release. Runtime-only, matches the CI pip-audit gate:
pip-audit -r requirements.lock -f cyclonedx-json -o sbom.cdx.json || true

# (B) Running-box audit — from the deployed venv. Faithful to what is
#     ACTUALLY installed, but INCLUDES dev/audit tooling (pip-audit and its
#     deps) that is NOT shipped. For inspecting a box, not for the release:
.venv/bin/pip-audit -f cyclonedx-json -o sbom.cdx.json || true
```

- **Attach form (A), not (B), to a release.** Form (B) inventories the whole
  venv, so it can flag CVEs in tooling that never ships. Seen for real
  (v0.5.3, 2026-07-12): (B) reported a High `msgpack` DoS — but `msgpack` is
  only pulled by `pip-audit`→`cachecontrol` (dev tooling; `requirements-dev.
  lock` already pins the patched 1.2.1), is absent from `requirements.lock`,
  and (A) reported **0 vulns / 48 components**. The CI gate audits the lock,
  so (A) is what "green CI" actually certifies.
- `|| true` because `pip-audit` exits non-zero when it finds a
  vulnerability — the SBOM file is still written (a clean run exits 0).
- Output is CycloneDX 1.4 JSON: a `components` inventory + a
  `vulnerabilities` section. Use `-f cyclonedx-xml` for the XML flavour.
- Form (A) must resolve the lock, so run it on **Linux** (CI or the server);
  it fails on the Windows workstation (`uvloop` won't build).

**When to refresh**: after any lock change (i.e. each release — the
`pip-audit` CI job already re-checks the lock then). **Where it lives**:
the SBOM is a generated, point-in-time artifact — do NOT commit it
(`*.cdx.json` is gitignored). Attach it to the GitHub release when a
downstream consumer or auditor needs the provenance for a version:

```bash
gh release upload vX.Y.Z-django sbom.cdx.json
```

The dev server authenticates to GitHub with a **deploy key (git-only)**, so
`gh` / the release-asset API do not work there. Generate the SBOM on the
server (form A), copy it to a workstation where `gh` is authenticated
(`scp root@<host>:.../sbom.cdx.json .`), and `gh release upload` from there
— or `curl -X POST` the uploads API with a PAT (`repo` scope).

## manage.py auto-loads APP_CONFIG (and app.env)

`manage.py` discovers a sensible `APP_CONFIG` automatically so
operators do not have to `export APP_CONFIG=...` before every
`python manage.py shell` (or wire test). Lookup order, first hit
wins:

1. `APP_CONFIG` / `AMELI_APP_CONFIG` already set in the env
   (e.g. by the systemd unit) — honored as-is.
2. `/etc/<slug>/app.yaml` where `<slug>` is the
   `[project].name` from `pyproject.toml`. Matches the
   install.sh layout (`/etc/ameli-app-template-dev/app.yaml`
   et al.).
3. `<project_root>/config/app.yaml` — dev override.
4. `<project_root>/config/app.yaml.example` — template default
   so a freshly-cloned repo boots without setup.

The matching `app.env` (alongside the chosen `app.yaml`, plus
`<project_root>/app.env` as fallback) is loaded by a
Python-native parser that handles values containing `(`, `)`,
`!` and a trailing `=` (Fernet padding) without the IFS / shell
gotcha that breaks `set -a; . app.env; set +a`. Existing env
vars are never overridden — explicit beats file.

This means a wire test on the deployed box now reduces to:

```bash
cd /opt/ameli-app-template-dev
.venv/bin/python manage.py shell <<'PY'
# ... probe ...
PY
```

No `set -a`, no `IFS= read`, no `export APP_CONFIG`.

## Continuous Integration (`.github/workflows/ci.yml`)

CI is tuned to stay inside the GitHub Actions monthly budget (2000 min on
the Free plan) **without weakening the promotion gate**. The trigger
strategy (since 2026-07-10):

| Event | What runs | ~Cost |
|---|---|---|
| **Docs-only push** (`**/*.md`, `docs/**`) | nothing — skipped via `paths-ignore` | 0 |
| **Code push to `dev`** | `Lint + Test` on **Python 3.13** only (ruff · ruff-format · bandit · mypy · django check · migrations · pytest+coverage on SQLite) + `pip-audit` + `js-unit` | ~4-5 min |
| **Pull request** (promotion to `main`) | the **full** `Lint + Test` matrix (3.11 · 3.12 · 3.13 · 3.14) + **E2E** (Playwright/Chromium) + **Test (PostgreSQL)** + `pip-audit` + `js-unit` | ~18 min |
| **Weekly schedule** (Mon 06:00 UTC) | same full sweep as a PR — catches Python-version drift and freshly-disclosed CVEs (`pip-audit`) even with no push | ~18 min |

Key points:

- **Skipping is precise.** A *mixed* commit (code **+** docs) still runs;
  a *release* commit touches `pyproject.toml`/`requirements*.lock` (not
  ignored), so `pip-audit` always gates a dependency change.
- **The full matrix + e2e + Postgres run on every PR to `main`**, so the
  branch-protection required checks below are all present on a promotion.
  A plain `dev` push only produces `Lint + Test (Python 3.13)` — that is
  expected, not a regression.
- The `dev` push runs the SQLite unit suite; the **PostgreSQL** run
  (which exercises `select_for_update()` etc. on the real backend) and
  the **e2e** browser flows move to PR + weekly.
- To force a full run without a PR: wait for the Monday schedule, or add
  a `workflow_dispatch` trigger if on-demand full runs become useful.

## Branch protection on `main`

Repo policy (applied 2026-06-18, roadmap #23):

* `main` is protected: **no force-push, no deletion, no bypass**.
* Pushes to `main` are blocked — every change goes through a PR.
* A PR can merge only when:
    - the CI workflow (`Lint + Test` matrix on 3.11 · 3.12 · 3.13 · 3.14)
      reports `success` on the head SHA, AND
    - the `Supply chain audit (pip-audit)` job reports `success`.
* PR review is NOT required (single-operator template), but the
  status checks must be green and up-to-date with `main`.

> **⚠ Free plan trap (verified 2026-06-18)**: GitHub does NOT
> enforce branch protection of any kind on **private** repos
> under the **Free** plan. Both flavors fail silently:
>
> * **Rulesets** (Settings → Rules → Rulesets): the UI says
>   "Active" but the banner reads "Your rulesets won't be
>   enforced on this private repository until you move to GitHub
>   Team organization account."
> * **Classic Branch protection rules** (Settings → Branches →
>   Branch protection rules): the rule shows status
>   **"Not enforced"** with the same upgrade banner.
>
> The session that closed #23 confirmed both: created the
> ruleset, observed it was no-op, switched to the classic rule,
> observed it was also no-op. The template ships two
> client/audit-side substitutes (below) that work on every plan,
> AND the server-side rule documented further down — it kicks in
> automatically the moment the plan upgrades to Team or the repo
> is made public.

### Substitute 1 — local pre-push hook (client-side prevention)

`deploy/git-hooks/pre-push` refuses any `git push origin main`
unless the operator sets `ALLOW_DIRECT_PUSH=1` for the one-off.
Install per checkout:

```bash
bash scripts/install-pre-push-hook.sh
# -> [install-pre-push-hook] installed .git/hooks/pre-push
```

The hook does NOT travel with the repo (git refuses to install
hooks at clone time for security reasons), so every checkout
needs the install step. CI and the install scripts mention this
where relevant.

Test it (refuses, then bypass succeeds):

```bash
git checkout main
git commit --allow-empty -m "probe"
git push origin main
# -> [pre-push] Direct push to 'main' refused.

ALLOW_DIRECT_PUSH=1 git push origin main
# -> pushes (logged by the audit workflow below)
```

### Substitute 2 — push audit workflow (server-side detection)

`.github/workflows/main-push-audit.yml` runs on every push to
`main` and emits an `::warning::` annotation when HEAD has only
one parent (= direct push, not a merge commit). Greppable in the
Actions log; the operator can review who pushed and when. The
job exits 0 so it does not block the next CI lap.

### Substitute 3 — the actual ruleset (latent)

The ruleset and classic branch protection rule documented below
remain in the repo settings even though they are not enforced
today. Both will start blocking the moment the plan upgrades to
GitHub Team or Enterprise — no further configuration needed at
that point.

Apply (one-time, repo admin only). Two equivalent paths:

**A. Classic Branch protection rule (GitHub UI)** — Settings →
Branches → Branch protection rules → Add rule:

* Branch name pattern: `main`
* Require a pull request before merging: ON (Required approvals = 0)
* Require status checks to pass: ON
    - Require branches to be up to date before merging: ON
    - Status checks: `Lint + Test (Python 3.11)`,
      `Lint + Test (Python 3.12)`,
      `Lint + Test (Python 3.13)`,
      `Lint + Test (Python 3.14)`,
      `Supply chain audit (pip-audit)`
    - **OPS (2026-07-02)**: the matrix grew from 3.11/3.12 to
      3.11-3.14. The two new contexts (`Python 3.13`, `Python 3.14`)
      must be added to the required set here — the pre-existing
      3.11/3.12 checks keep passing, so protection does not break if
      you forget, but the new Pythons would not gate a merge until
      added.
* Restrict who can push to matching branches: ON (empty allowlist
  — nobody pushes directly)
* Allow force pushes: OFF
* Allow deletions: OFF
* Do not allow bypassing the above settings: ON

**B. `gh` CLI** — equivalent classic branch-protection payload
(the legacy `/branches/{branch}/protection` endpoint, NOT the
`/rulesets` one):

```bash
gh api -X PUT "/repos/HarDGameinc/AMELI-App-Template/branches/main/protection" \
    --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint + Test (Python 3.11)",
      "Lint + Test (Python 3.12)",
      "Lint + Test (Python 3.13)",
      "Lint + Test (Python 3.14)",
      "Supply chain audit (pip-audit)"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Day-to-day promotion of `dev → main` becomes:

```bash
gh pr create --base main --head dev --title "promote dev → main" --body "fast-forward"
gh pr merge --merge       # or --rebase if you want a linear history
```

The fast-forward `git push origin main` pattern used through
2026-06-17 will be rejected once the ruleset is active — that is
the intended behaviour. The previous `dev → main` via shell
shows up clearly in the audit log; the protected workflow makes
every promotion reviewable via PR history.

## Health checks

```bash
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
curl http://127.0.0.1:18080/health         # shallow: config + last-write timestamps
curl http://127.0.0.1:18080/health/deep    # deep: real DB write + FS write
curl http://127.0.0.1:18080/api/health
```

### `/health` vs `/health/deep` (Phase 2 #5, 2026-06-20)

`/health` inspects config (SMTP backend valid, queue not
stalled, disk has free bytes, db.status returns ok) — fast
liveness probe. Does NOT actually exercise the write path,
so a deploy with a read-only DB replica or a read-only data
dir passes `/health` but silently fails the first user write.

`/health/deep` actually exercises the write path:

* **db_write** — INSERT/SELECT/DELETE inside a rolled-back
  savepoint (zero state leaked).
* **fs_write** — tmpfile in `DATA_DIR` with `write+fsync+read+
  unlink`. Catches "disk full", "mounted read-only by
  accident", and selinux/apparmor write denials.

Each check reports its own `ms` latency so external monitors
can alert on regressions without subscribing to journal logs.
Returns 200 when both probes succeed, 503 when either fails.

Schedule from your prober:

```
# every 30 s — shallow probe for liveness
curl --silent --fail http://127.0.0.1:18080/health > /dev/null

# every 5 min — deep probe for readiness
curl --silent --fail http://127.0.0.1:18080/health/deep > /dev/null
```

Both honor `HEALTH_METRICS_ALLOWLIST` so they can be locked to
loopback / known prober IPs.

> **Default is world-readable — but a prod install locks it down.** With
> the list empty the views answer any client, so behind a reverse proxy
> `/health` leaks version, uptime and disk, and `/metrics` exposes the
> full scrape to anyone who reaches the public port (a known version is a
> CVE shortlist). `scripts/install.sh` therefore seeds
> `AMELI_APP_HEALTH_METRICS_ALLOWLIST=127.0.0.1,::1` on a **fresh prod**
> install (dev stays open for local probes). The post-install smoke and
> `validate_installation.sh` hit `127.0.0.1:<port>/health` directly, so
> the lockdown does not break them. Add your external monitor's IP to the
> list explicitly. An instance provisioned before this seeding is **not**
> rewritten on upgrade — `install.sh` warns instead, so an external
> scraper that relies on the open default is not silently cut off.

## First install reference

Use the full first-install walkthrough in:

- `docs/FIRST_INSTALL_DJANGO.md`

## Backup + restore

```bash
# create an archive
APP_ENV=prod bash scripts/backup.sh

# verify an archive without touching the live deploy (cron-friendly)
APP_ENV=prod bash scripts/restore.sh verify /var/backups/<archive>.tar.gz

# restore (destructive)
APP_ENV=prod bash scripts/restore.sh restore /var/backups/<archive>.tar.gz --yes
```

`backup.sh` bundles:
- the DB dump (`pg_dump --format=custom` on Postgres, `sqlite3 .backup`
  on SQLite — both work against a live writer)
- `${ETC_DIR}` (env file + yaml config)
- `${DATA_DIR}` (user-uploaded media)
- a `MANIFEST.sha256` of every artifact

Tunables (env vars):

| Variable | Default | Effect |
|---|---|---|
| `AMELI_APP_BACKUP_RETENTION_DAYS` | `30` | Older archives matching `${APP_INSTANCE}-*.tar.gz(.gpg)` are deleted at the end of each run. Neighbouring deploys' backups are never touched. |
| `AMELI_APP_BACKUP_GPG_RECIPIENT` | unset | When set, the archive is `gpg --encrypt`ed to that recipient and the plaintext deleted. Required if backups leave the host. |

`restore.sh verify` is the contract test: it extracts to a scratch
dir, validates every `sha256sum` from the manifest, then exits 0.
Schedule it weekly so a silently-corrupt backup gets caught before
you need to restore in anger.

### Update — the pre-update backup is mandatory

`scripts/update.sh` takes a backup, **verifies it** (`restore.sh verify`),
and only then runs `migrate`. A migration can be irreversible, so the
verified backup is the sole recovery path — a failed or unverifiable
backup **halts the update**. Operators who back up out of band opt out
explicitly:

```bash
AMELI_APP_UPDATE_SKIP_BACKUP=1 APP_ENV=prod bash scripts/update.sh
```

(A GPG-encrypted archive whose private key is not on this host can't be
verified here; that is a warning, not a halt — the archive still exists.)

### Uninstall — safe by default, `--purge` behind a guard

```bash
# SAFE: stop + remove units, PRESERVE config/data/logs/backups
APP_ENV=prod bash scripts/uninstall.sh

# DESTRUCTIVE: also delete every dir + the system user/group.
# Takes a FINAL backup into /var/backups first (survives the purge).
APP_ENV=prod bash scripts/uninstall.sh --purge --yes
```

`--purge` refuses without `--yes`. The **database is never dropped** —
the installer does not create it, so its ownership is yours; `--purge`
prints the exact `dropdb`/`dropuser` commands (parsed from
`DATABASE_URL`) instead of guessing. Opt out of the final backup with
`AMELI_APP_UNINSTALL_SKIP_BACKUP=1` (and its destination with
`AMELI_APP_UNINSTALL_BACKUP_DIR`).

### Automated nightly backup via systemd (roadmap #18)

The template ships `deploy/systemd/ameli-app-backup.{service,timer}`.
`scripts/install.sh` renders the placeholders and registers the
timer in every supported profile (`api-worker-maintenance`,
`api-web`, `api-web-worker-maintenance`, `web-worker`,
`web-capture`, `api-web-capture`,
`api-capture-notifier-maintenance`). After a fresh install:

```bash
systemctl status ${UNIT_PREFIX}-backup.timer
# -> active (waiting), next: <today or tomorrow> 04:10:00
systemctl list-timers '*-backup.timer'
```

Schedule: daily at `04:10` local time + a 0-120s
`RandomizedDelaySec` jitter so multiple instances on the same host
(e.g. `ameli-app-template-dev` + `*-prod`) never contend for
`pg_dump`. The 04:10 slot sits after the 03:20 maintenance run so
the archive captures the post-purge state.

The unit runs as `root` because `scripts/backup.sh` needs to:
- read `/etc/<instance>/app.env` (mode `0640 root:<instance>`)
- read the data dir which may include files owned by the app user
- run `pg_dump` against the connection string declared in
  `DATABASE_URL`

Run an out-of-schedule backup at any time with
`systemctl start ${UNIT_PREFIX}-backup.service`. Disable
permanently (e.g. on a host with a different backup orchestrator)
with `systemctl disable --now ${UNIT_PREFIX}-backup.timer`.

### Postgres connectivity for backup (roadmap #19)

`backup.sh` uses `DATABASE_URL` to invoke `pg_dump`. Two patterns
work; pick one **before** enabling the timer on a Postgres deploy:

**Recommended — Postgres listens on `127.0.0.1:5432` with password
auth for the app user**. The connection string in `app.env`
already encodes the credential, so the same `DATABASE_URL` works
for Django at runtime AND for `pg_dump` invoked by the timer:

```
# /etc/postgresql/<ver>/main/postgresql.conf
listen_addresses = 'localhost'

# /etc/postgresql/<ver>/main/pg_hba.conf  — TCP loopback only
host  <db>  <app_user>  127.0.0.1/32  scram-sha-256
host  <db>  <app_user>  ::1/128       scram-sha-256

# /etc/<instance>/app.env
AMELI_APP_DATABASE_URL=postgresql://<app_user>:<pwd>@127.0.0.1:5432/<db>
```

No Unix-socket auth is needed; `pg_dump` connects via TCP using
the password baked into `DATABASE_URL`. The credential never
leaves the host (no `listen_addresses = '*'`), so the attack
surface is the same as the socket path while making the
single-shared-connection-string semantics easy to reason about.

**Alternative — keep socket auth, but grant the deploy user a PG
role**. Useful when policy bars opening TCP on the DB host. The
`DATABASE_URL` then needs a host-less form
(`postgresql:///<db>?user=<app_user>`) and `backup.sh` must
either:

1. run `pg_dump` via `sudo -u postgres pg_dump ...` (which means
   wrapping the call site, since `DATABASE_URL` alone won't
   redirect `pg_dump` through `sudo`), OR
2. expose an OS user that matches the PG role name AND grant peer
   auth to that user (and the systemd unit would run as that
   user, not root — at which point the unit can no longer read
   `/etc/<instance>/app.env`).

Option 1 is a backup-script refactor; option 2 forks the unit. The
TCP-localhost recommendation avoids both.

## Outbound email retry queue (#3)

Flows that can tolerate eventual delivery (password reset emails,
admin-initiated MFA-disabled notifications) use
`services.send_with_retry`. On transient SMTP failure the message
is persisted to `accounts_outboundemail` instead of bubbling the
exception up to the request handler.

The `notify-once` worker drains the queue using an exponential
backoff (1 min → 5 min → 15 min → 1 h → 6 h) and gives up after
5 attempts, recording an `email_failed_permanent` audit row for
the operator to investigate. Rows carrying an `expires_at` (e.g.
a password-reset URL whose token TTL elapsed) are dropped without
an SMTP attempt — better than shipping a dead link.

Schedule it via systemd timer alongside the other workers:

```bash
.venv/bin/ameli-app notify-once
```

The installer enables `ameli-app-template-<env>-notifier.service`
automatically as part of the default `api-worker-maintenance`
profile (and any other api-bearing profile). The service runs
`notify-once` in a `sleep $AMELI_APP_NOTIFIER_INTERVAL` loop
(default 30 s) so the OutboundEmail queue drains continuously
without operator intervention. If your install pre-dates this
change, enable it manually:

```bash
systemctl enable --now ameli-app-template-<env>-notifier.service
```

Inspect the queue:

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.models import OutboundEmail
for row in OutboundEmail.objects.exclude(status='sent').order_by('next_retry_at'):
    print(row.pk, row.status, row.attempts, row.next_retry_at.isoformat(), row.subject, row.to_emails)
"
```

Force a retry now (move the next_retry_at backwards):

```bash
.venv/bin/ameli-app shell -c "
from django.utils import timezone
from ameli_web.accounts.models import OutboundEmail
OutboundEmail.objects.filter(status='pending').update(next_retry_at=timezone.now())
"
.venv/bin/ameli-app notify-once
```

### Email queue dashboard widget

The custom `/admin/` panel renders a "Cola de email saliente" card
that polls `/admin/metrics/email-queue` every 30 s and shows live:

- pending rows (waiting for a worker tick)
- delivered in the last 24 h
- permanently failed in the last 24 h (after `max_attempts`)
- expired in the last 24 h (`expires_at` elapsed)
- oldest pending row age (when there is one)
- top error_classes among recent failures

Same auth posture as the audit / sessions listings — superadmin
visibility, no sudo prompt — so operators can keep the tab open
while monitoring. Acciones puntuales (forzar reintento, ver
detalle por fila) viven en `/django-admin/accounts/outboundemail/`.

Or use the Django admin: navigate to **Outbound emails** under the
*Accounts* section in `/django-admin/`, filter by `status=pending`,
select the rows you care about and run the **Reintentar ahora**
action. The page is read-only by design (no edit/delete) so the
queue stays driven by the worker. Reaching `/django-admin/`
requires sudo mode — see "Sudo mode" in `docs/SECURITY.md` if you
need a refresher.

### Structured logs (`ameli.email_queue`)

Every queue transition emits a record on the `ameli.email_queue`
Python logger with structured `extra=` fields so an aggregator
(journald + `MESSAGE_ID`, ELK, Loki, OTEL, ...) can index on
specific keys. Events:

| `event`              | level   | extras                                                              |
|----------------------|---------|---------------------------------------------------------------------|
| `email.sent_inline`  | INFO    | audit_action, target_username, recipient_count                      |
| `email.queued`       | WARNING | queue_id, audit_action, target_username, error_class, recipient_count, attempts |
| `email.delivered`    | INFO    | queue_id, audit_action, target_username, delivered_after_attempts   |
| `email.requeued`     | WARNING | queue_id, audit_action, target_username, attempts, error_class, next_retry_at |
| `email.gave_up`      | ERROR   | queue_id, audit_action, target_username, attempts, error_class      |
| `email.expired`      | WARNING | queue_id, audit_action, target_username                             |
| `email.queue_tick`   | INFO    | considered, sent, requeued, failed, expired                         |

The notifier service ships logs to journald by default; filter by
the logger name with `journalctl _SYSTEMD_UNIT=ameli-app-template-<env>-notifier.service | grep email\\.`
or by event:

```bash
journalctl -u ameli-app-template-dev-notifier.service --since "1 hour ago" \
  | grep -E 'email\.(queued|requeued|gave_up|expired)'
```

Flows that need the user to see a failure immediately (the profile
test-email button, MFA codes during login) keep using
`.send(fail_silently=False)` and surface the exception to the
caller — the queue is opt-in.

## Data retention sweep (maintenance worker)

The `maintenance-once` worker now runs a conservative retention
sweep on every tick — purges only resolved / expired / revoked
operational rows so the DB stays bounded on long-lived deploys.
Defaults:

| Table | Window | What gets deleted |
|---|---|---|
| `UserSession` | 30 d | rows with `revoked_at` set and older than window |
| `OutboundEmail` | 30 d | rows in `sent` or `failed` whose `updated_at` < window |
| `ThrottleCounter` | 1 d | rows whose `window_start` < window |
| `EmailChangeRequest` | 30 d | rows already `confirmed_at` or `cancelled_at` |
| `MFAEmailChallenge` | 7 d | rows with `used_at` set and older than window |
| `AuditEvent` | off by default | only when `AMELI_APP_AUDIT_RETENTION_MAX_AGE_DAYS` is set |

Audit pruning is opt-in. When you set
`AMELI_APP_AUDIT_RETENTION_MAX_AGE_DAYS=<N>` the sweep deletes rows
older than N days, demotes the surviving tail to legacy (clears
`hmac` and `prev_hmac` — they become pre-chain rows, skipped by
`verify-audit`), and writes a fresh `retention_audit_anchor` row
that becomes the new chain head. This sacrifices verifiability of
the rows that lived through the cut in exchange for a clean chain
going forward.

Each run is itself audited (`retention_sweep`) so the operator can
confirm via `/admin/` or `ameli-app verify-audit --strict-precondition`.

Run it manually:

```bash
.venv/bin/ameli-app maintenance
```

The installer enables `ameli-app-template-<env>-maintenance.timer`
by default — check its schedule with
`systemctl list-timers | grep maintenance`.

## Docker (dev only)

A `Dockerfile` (multi-stage, non-root, tini entrypoint) plus a
`docker-compose.yml` are included for local development:

```bash
docker compose up                     # api + notifier + postgres
docker compose run --rm api pytest    # full suite in-container
docker compose exec api .venv/bin/ameli-app verify-audit
```

The compose stack is intentionally not a production manifest —
the `AMELI_APP_SECRET_KEY` is a placeholder, no TLS termination,
no resource limits, email backend is the console (so flows that
send mail print to the api container's stdout instead of needing
a real SMTP relay). For prod, use `scripts/install.sh` against
the systemd profile of choice.

## Prometheus metrics (/metrics)

`/metrics` exposes the operator-relevant counters in Prometheus
text exposition format — gated by the same IP allowlist as
`/health`, so Prometheus scraping happens on the operator network
without any auth handshake. Implemented hand-rolled (no
`prometheus_client` dependency) so the template stays
dependency-free; swap in the library when you outgrow it.

Metrics surfaced:

| Name | Type | Description |
|---|---|---|
| `ameli_app_users_total` | gauge | Total registered users |
| `ameli_app_users_active` | gauge | Users with `is_active=True` |
| `ameli_app_users_locked` | gauge | Users with `locked_at` set (permanent lockout) |
| `ameli_app_users_pending_password` | gauge | Users with `must_change_password=True` |
| `ameli_app_sessions_total/active/revoked` | gauge | UserSession rollup |
| `ameli_app_audit_events_total` | counter | All audit rows |
| `ameli_app_audit_events_failed` | counter | Rows whose action ends in `_failed` |
| `ameli_app_audit_chain_ok` | gauge | 1 if tail row hmac matches the configured key |
| `ameli_app_email_queue_pending` | gauge | OutboundEmail rows waiting |
| `ameli_app_email_queue_oldest_seconds` | gauge | Oldest pending row's age |
| `ameli_app_email_queue_sent_24h` | gauge | Delivered in last 24 h |
| `ameli_app_email_queue_failed_24h` | gauge | Permanently failed in last 24 h |
| `ameli_app_email_queue_expired_24h` | gauge | Dropped before delivery in last 24 h |
| `ameli_app_maintenance_mode_active` | gauge | 1 when MaintenanceMode.active |
| `ameli_app_uptime_seconds` | counter | Seconds since process start |
| `ameli_app_info{version,environment}` | gauge | Static build info |

Sample alert rules:

```yaml
- alert: AmeliAuditChainBroken
  expr: ameli_app_audit_chain_ok == 0
  for: 5m
  annotations:
    summary: "Audit chain hmac mismatch — possible tampering"

- alert: AmeliEmailQueueStuck
  expr: ameli_app_email_queue_oldest_seconds > 3600
  for: 10m
  annotations:
    summary: "Oldest pending OutboundEmail row > 1h — notifier may be down"

- alert: AmeliMaintenanceLeftOn
  expr: ameli_app_maintenance_mode_active == 1
  for: 2h
  annotations:
    summary: "Maintenance mode active for > 2h, operator may have forgotten to disable"
```

## Database connection pool

Django opens a fresh Postgres connection per request by default, which
at moderate concurrency (~10 RPS or more) makes connection setup +
authentication latency the dominant cost. The template enables two
cheap mitigations out of the box on Postgres backends, plus an
opt-in real pool for higher concurrency.

### Persistent connections + health checks (always on, Postgres only)

`DATABASES["default"]` carries:

- `CONN_MAX_AGE = 60` (configurable via
  `AMELI_APP_DB_CONN_MAX_AGE_SECONDS`) — keep each worker's
  connection alive across requests for up to 60 s before recycling.
  Set to `0` to disable (back to per-request connections); set to
  a larger value to amortise more aggressively.
- `CONN_HEALTH_CHECKS = True` — Django 4.1+ probes a stale connection
  before reuse so a socket killed by Postgres'
  `idle_in_transaction_session_timeout`, a pgbouncer restart, or
  a network blip surfaces as a controlled error rather than a 500.

SQLite installs ignore both settings (no connection pooling makes
sense on a file lock).

### Real pool (opt-in)

For higher concurrency or workers behind pgbouncer, opt into
`psycopg3`'s built-in `ConnectionPool` via two env vars:

```env
AMELI_APP_DB_POOL_MIN_SIZE=2     # connections kept warm at idle
AMELI_APP_DB_POOL_MAX_SIZE=10    # cap during burst
```

When both (or just one) is set, the template adds
`OPTIONS["pool"] = {"min_size": ..., "max_size": ...}` to the
`DATABASES` entry. Django 5.1+ hands the dict to
`psycopg_pool.ConnectionPool` at connection time. `psycopg-pool`
is declared as a runtime dep (already pinned in
`requirements.lock`) so the package is present on every deploy;
the pool stays OFF unless the env vars are set.

Sizing rule of thumb: `max_size` per worker × number of workers
must stay below your Postgres `max_connections` minus headroom
(superuser slots, replication). For a 2-worker uvicorn fronting
`max_connections=100`, `max_size=20` per worker is conservative.

### Disable / rollback

```bash
# Per-request connections (Django default behaviour)
echo 'AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0' >> /etc/<instance>/app.env

# Turn the real pool off
sed -i '/AMELI_APP_DB_POOL/d' /etc/<instance>/app.env

systemctl restart <instance>-api.service
```

## django-silk profiler

`django-silk` records every matching request to its own DB tables and
exposes a drill-down panel at `/silk/`. Useful for "which view has
the N+1 query?" or "which template render is slow?" — complements
OpenTelemetry tracing (which is great for production aggregates but
hides the Python stack-trace of each query).

### Enabling in dev

```env
AMELI_APP_SILK_ENABLED=true
```

Restart the API. On boot the conditional in `settings.py` adds
`silk` to `INSTALLED_APPS`, `silk.middleware.SilkyMiddleware` to
`MIDDLEWARE`, and the `/silk/` URL route. Run migrations to create
the silk DB tables:

```bash
python manage.py migrate silk
```

Then navigate any path matching `^/(profile|admin|api)/` (the default
intercept regex) and open `http://<host>/silk/` as a logged-in
superadmin. The panel shows recent requests with SQL queries,
template renders, and per-callsite drill-down.

### Customising scope

```env
# Profile EVERYTHING (overrides the default intercept regex)
AMELI_APP_SILK_INTERCEPT_REGEX=.*

# Or limit to a single endpoint
AMELI_APP_SILK_INTERCEPT_REGEX=^/api/payments/

# Cap retained records (default 1000)
AMELI_APP_SILK_MAX_RECORDED_REQUESTS=500
```

The panel auto-prunes oldest records when the cap is hit
(`SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT=10` runs the sweep on
~10% of incoming requests so it amortises cheaply).

### Why the prod boot guard

By default silk persists **the full request body and response body**
to its DB tables. On a real-user prod (passwords, MFA codes, PII)
that violates ASVS V8.3.1 (no PII in logs) unless the operator
explicitly accepts the trade-off. Enabling silk outside dev
therefore requires a second flag:

```env
AMELI_APP_SILK_ENABLED=true
AMELI_APP_SILK_ALLOW_PROD=true
```

Without the second flag, settings.py raises `RuntimeError` at boot.
For a real prod profiling window the recommended pattern is:

1. Clone the prod DB to a staging host.
2. Set both flags in the staging env.
3. Replay anonymised traffic, drill into silk panel.
4. Disable + truncate `silk_*` tables before promoting back.

### Disable / rollback

```bash
sed -i '/AMELI_APP_SILK/d' /etc/<instance>/app.env
systemctl restart <instance>-api.service

# Optionally drop the silk tables (Django migration reverse)
python manage.py migrate silk zero
```

### Why ship silk if OTel already covers profiling?

| | OTel | django-silk |
|---|---|---|
| Backend infra | Needs collector + viewer (Jaeger/Tempo/Honeycomb) | Self-contained in app DB |
| Query callsite (Python stack) | No | **Yes** — links each query to the view line that fired it |
| Aggregate p99 / per-route | **Yes** | No |
| Production-grade overhead | Low (~1ms) | Higher (DB writes per request) |
| Storage cost | External backend | App DB tables |
| Cross-service correlation | **Yes** (W3C traceparent) | No |

They complement, not replace. OTel is the day-to-day production
observability; silk is the "debug this specific request" tool.

## Avatar AV scan (ASVS V12.4.1)

Avatar uploads can be funnelled through an antivirus scanner before
they hit disk. Opt-in by setting ``AMELI_APP_AV_ENDPOINT`` to one of:

- ``unix:///path/to/clamd.ctl`` — clamd over a Unix-domain socket
  (INSTREAM). **Recommended on Debian / Ubuntu**: ``apt install
  clamav-daemon`` ships with systemd socket activation pinned to
  ``/var/run/clamav/clamd.ctl`` and a hardening drop-in that blocks
  the TCP path even when ``clamd.conf`` carries ``TCPSocket``. The
  Unix endpoint sidesteps that entirely:
  ``AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl``.
- ``tcp://host:port`` — clamd over TCP (INSTREAM). Useful when the
  AV daemon runs on a separate host. Port defaults to 3310 if
  omitted. Requires ``TCPSocket`` enabled in ``clamd.conf`` and any
  systemd socket-activation / hardening drop-ins reviewed.
- ``http://...`` or ``https://...`` — an HTTP endpoint that accepts
  ``POST`` of the raw bytes and returns JSON
  ``{"stream": "OK"|"FOUND", "signature": "<name>"?}``. Suitable for
  a sidecar (clamav-rest) or managed AV service.

Unset → scanning is disabled (current residual risk R-05 stays
closed only when the operator opts in).

Verdicts:

| Verdict | Behaviour | Audit row |
|---|---|---|
| ``ok`` | Upload proceeds normally | None |
| ``infected`` | Upload rejected, generic error to user, signature stays in audit chain | ``avatar_upload_av_rejected`` with ``signature`` + ``endpoint_scheme`` |
| ``check_failed`` (timeout, unreachable, bad response) | Upload PROCEEDS — fail-open with audit visibility | ``avatar_upload_av_check_failed`` with ``reason`` + ``endpoint_scheme`` |

The fail-open policy mirrors the HIBP password validator: an AV
outage MUST NOT lock users out of profile updates. Operators that
require strict fail-closed behaviour deploy a reverse proxy with a
health probe in front of clamd.

### Debian / Ubuntu first-install gotcha

On a fresh ``apt install clamav-daemon``, the daemon does NOT
auto-start because the package ships with no virus databases.
``clamav-freshclam`` downloads ~110 MB of signatures (3–10 min on a
typical link); when it finishes it tries to notify clamd via
``/var/run/clamav/clamd.ctl`` but the socket does not exist yet
(``Clamd was NOT notified: ... No such file or directory`` in the
freshclam journal). A single manual restart wires everything up:

```bash
# Wait until /var/lib/clamav/ has main.cvd, daily.cvd, bytecode.cvd
journalctl -u clamav-freshclam.service -n 20 | grep -E '(main|daily|bytecode)\.cvd updated'

# Then start the daemon — subsequent boots / redeploys are automatic
# via systemd socket activation.
systemctl restart clamav-daemon.service
ls -la /var/run/clamav/clamd.ctl   # should now exist as srw-rw-rw-
```

### Quick test with the EICAR test signature

EICAR is a harmless file every AV must catch as a sanity check.

```bash
# On a host with clamd listening on 3310:
echo 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' \
    | python -c "import socket, struct, sys; \
        data = sys.stdin.buffer.read(); \
        s = socket.create_connection(('127.0.0.1', 3310)); \
        s.sendall(b'zINSTREAM\\0'); \
        s.sendall(struct.pack('!I', len(data)) + data); \
        s.sendall(struct.pack('!I', 0)); \
        print(s.recv(4096).decode())"
# Expected: stream: Eicar-Test-Signature FOUND
```

## OpenTelemetry tracing

Distributed tracing is opt-in. The SDK is loaded by `asgi.py` on
every boot but stays dormant unless the operator points it at a
collector:

```env
AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
AMELI_APP_OTEL_SERVICE_NAME=ameli-app-template          # optional, default "ameli-app-template"
AMELI_APP_OTEL_SAMPLE_RATIO=1.0                         # optional, default 1.0 (all spans)
```

The endpoint MUST start with `http://` (cleartext) or `https://`
(TLS). A bare `host:port` would behave inconsistently across SDK
versions — the boot guard refuses it loud at settings load.

What you get when the endpoint is set:

- Every HTTP request gets a span via the Django auto-instrumentation,
  with route attribute and status code.
- Every Postgres query gets a child span (truncated SQL + duration)
  via psycopg auto-instrumentation.
- Every outbound HTTPS call (HIBP password breach check) gets a
  child span via urllib auto-instrumentation.
- Manual spans for diagnostic-heavy code paths:
  - `av.scan_bytes` — attributes: `av.endpoint_scheme`, `av.bytes`,
    `av.verdict`, `av.signature` (when infected), `av.reason`
    (when check_failed / breaker_open).
  - `hibp.range_query` — attributes: `hibp.prefix`, `hibp.outcome`
    (`ok` / `unreachable` / `breaker_open`).
  - `smtp.send` (per outbound email) — attributes: `smtp.queue_id`,
    `smtp.attempts`, `smtp.audit_action`.

The existing `X-Request-Id` middleware already accepts and emits
W3C traceparent-compatible IDs, so a trace started by an upstream
load balancer continues into the app and the same id appears as
`request_id` in every log line (links log → trace in any backend
that supports it).

### Dev quickstart — Jaeger all-in-one

For local poking, run Jaeger and point the env var at it:

```bash
docker run -d --name jaeger \
  -p 16686:16686 -p 4317:4317 \
  jaegertracing/all-in-one:latest

# In /etc/<instance>/app.env or your local shell:
export AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317

# Restart the API
python -m ameli_app.api

# Make a few requests, then open http://127.0.0.1:16686
# and search service "ameli-app-template".
```

Spans appear in the Jaeger UI with parent-child relationships,
attributes, exception events, and duration.

### Production: pick a collector

For a real deploy use an OTel collector (`otel-collector` from the
opentelemetry-collector-contrib distribution) so you can route to
multiple backends (Tempo, Loki, Honeycomb, Datadog, …) and apply
sampling / redaction policies in one place. The minimum config:

```yaml
# /etc/otelcol/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 127.0.0.1:4317
processors:
  batch:
exporters:
  otlphttp:
    endpoint: https://your-backend.example.com/otlp
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp]
```

`AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317` then
ships spans to the local collector, which forwards.

### Disabling

Unset (or comment out) `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT` and
restart. The SDK loads but registers no provider; `av.scan_bytes`,
HIBP and SMTP code paths run unchanged but spans are no-ops with
zero per-request cost.

## Troubleshooting: SMTP "Network is unreachable" (Errno 101)

Symptom: a user attempts an email-based action (MFA email code,
password reset) and the UI surfaces `"No pudimos enviar el codigo
por email ahora mismo"`. The audit chain records an
`email_failed_permanent` (queue path) or
`mfa_email_login_send_failed` (sync path) row with
`error_class=OSError`. Journal traceback ends in:

```
File "/usr/lib/python3.13/socket.py", line 849, in create_connection
    sock.connect(sa)
OSError: [Errno 101] Network is unreachable
```

Surfaced 2026-06-23 on a Debian 13 host configured for IPv4 only
(no global IPv6 address, no IPv6 default route, DHCP only assigns
IPv4) while configured to send via `smtp.office365.com`. Office
365 publishes AAAA records; glibc's `getaddrinfo` returned them;
Python's `smtplib` tried IPv6 first; kernel returned ENETUNREACH;
the smtplib path raised before falling back cleanly to IPv4.

### Diagnose

```bash
ip -6 addr show                # global IPv6 assigned? (look past loopback + fe80)
ip -6 route show default       # IPv6 default route present?
getent ahosts <smtp-host>      # AAAA records returned by glibc?
nc -zvw 5 <smtp-host> 587      # raw TCP reachable?
nc -4 -zvw 5 <smtp-host> 587   # IPv4 specifically?
```

If `ip -6 addr` shows only `::1` + `fe80::*` and `ip -6 route show
default` is empty, the host is IPv4-only; `getent ahosts` returning
AAAA records means glibc is misleading smtplib.

### Fix (IPv4-only host)

Two layers, both reversible:

```bash
# A) Prefer IPv4 over IPv6 at getaddrinfo level (gai.conf)
cp /etc/gai.conf /etc/gai.conf.bak
cat >> /etc/gai.conf <<'GAI'
# IPv4 precedence bump — IPv6 stack inerte en este host
precedence ::1/128       50
precedence ::/0          40
precedence 2002::/16     30
precedence ::/96         20
precedence ::ffff:0:0/96 100
GAI

# B) Disable IPv6 entirely (kernel-level, persistent)
cat > /etc/sysctl.d/99-disable-ipv6.conf <<'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
sysctl -p /etc/sysctl.d/99-disable-ipv6.conf

# Verify
ip -6 addr show              # empty
getent ahosts <smtp-host>    # only IPv4 entries

systemctl restart <instance>-api.service
```

Smoke test:

```bash
cd /opt/<instance>
.venv/bin/python manage.py shell <<'PY'
from django.core.mail import EmailMessage
from django.conf import settings
msg = EmailMessage("[smoke] template", "ok",
                   from_email=settings.DEFAULT_FROM_EMAIL,
                   to=["YOU@example.com"])
msg.send(fail_silently=False)
print("send OK")
PY
```

### Rollback (if IPv6 routing is restored on the network later)

```bash
rm /etc/sysctl.d/99-disable-ipv6.conf
mv /etc/gai.conf.bak /etc/gai.conf
reboot  # cleanest; or sysctl --system + interface reload
```

The template code is unchanged — this is a host-level operational
fix only. The MFA UI's "try TOTP instead / Reenviar codigo"
fallback that surfaced this issue is the intended behaviour
(better than 500-ing the request) and stays as-is.

### Post-apply: transient EADDRNOTAVAIL window

Immediately after `sysctl -p` and the api restart, there is a brief
window (<60 s) where in-flight requests may still trip on
`OSError [Errno 99] Cannot assign requested address`. Cause:
glibc's getaddrinfo retains an internal cache that may still
return AAAA records for a few seconds after the kernel disables
IPv6; when Python opens the corresponding ``AF_INET6`` socket the
kernel rejects with EADDRNOTAVAIL. The error is **not** the same
``Errno 101`` you were chasing — it confirms the disable took
effect. Subsequent requests (after the cache expires) only see
IPv4 records and work normally.

If you want to avoid even that brief window, restart the api
service a second time ~60 s after the first restart:

```bash
sleep 60
systemctl restart <instance>-api.service
```

Or just accept the transient — the surfaced UI message offers
the user a TOTP / "Reenviar codigo" fallback that resolves
within the window.

## End-to-end tests (Playwright)

Mini-roadmap #12 (2026-06-23) ships a small Playwright suite at
``tests/e2e/`` that drives a headless Chromium against the live
Django app to cover the auth + avatar + password-change happy
paths. Pure Python — ``pytest-playwright`` integrates with the
existing pytest pipeline.

### Running locally

```bash
# Install browser (one-time per machine; ~140 MB chromium binary)
python -m playwright install chromium --with-deps

# Run only the e2e suite
python -m pytest tests/e2e/

# Or every test including e2e
python -m pytest --run-e2e
```

The default ``python -m pytest`` invocation **skips** e2e to keep
the unit suite fast (~100s). The skip is driven by a hook in
``tests/conftest.py`` + ``tests/e2e/conftest.py`` that detects
either the path or the ``--run-e2e`` flag as the explicit opt-in.

### Covered flows

- **Login + MFA email + dashboard** — exercise the full auth
  pipeline, captures the MFA code from the in-memory mail
  outbox, verifies redirect to the dashboard.
- **Wrong-password rejection** — ensures the login view re-renders
  with the generic error (no user-existence oracle).
- **Avatar upload** — uploads a tiny PNG, verifies the hero on
  both ``/profile/`` and ``/`` swaps to ``<img>``, plus the
  top-right menu chip.
- **Password change + re-login** — full rotation: change via the
  security tab, old password fails, new password works.

### Test isolation

- Each test gets a fresh Django user via the ``e2e_admin`` fixture.
- ``pytest-playwright`` opens a clean browser context per test
  (no cookie / localStorage leak).
- Email backend is switched to ``locmem`` per test via
  ``captured_emails`` fixture; no real SMTP traffic.
- ``pytest-django`` rolls back the DB after each test.

### CI

The ``e2e`` job in ``.github/workflows/ci.yml`` runs on every push
and PR. It downloads chromium (~30 s on GitHub runners), runs
migrations, then invokes ``pytest tests/e2e/ -v``. Independent
from the unit-test matrix job so unit failures don't gate the e2e
signal (and vice versa).

### Extending

Add a new test file under ``tests/e2e/``. The conftest provides
``page`` (function-scoped Playwright Page), ``live_url`` (str),
``e2e_admin`` (User), ``captured_emails`` (list[EmailMessage]).
Mark with ``pytestmark = pytest.mark.django_db`` if the test
touches the ORM.

Avoid:
- Screenshot diff tests without baseline management — the value
  is real but the operational cost (baselines per platform /
  browser, churn on every CSS tweak) is high. Document a
  rationale before adding.
- Cross-browser sweeps in CI — chromium-only keeps the job
  under 2 min. Operators that need Firefox / WebKit coverage
  add ``--browser firefox`` locally.

## OpenAPI docs panel SRI (ASVS V10.3.x)

The `/docs` (Swagger UI) and `/redoc` views load JavaScript bundles
from `cdn.jsdelivr.net`. ASVS V10.3.x requires Subresource Integrity
hashes on those bundles so a CDN compromise (or a misconfigured
upstream proxy) cannot inject JS into the operator's browser.

Out of the box:

- In `dev`: the docs panel renders without SRI configured (operator
  DX preserved; the panel is for local exploration).
- Outside `dev`: the docs panel refuses to render with HTTP 503 when
  any required SRI is missing. The 503 body names the missing env
  vars and the helper command.

To populate the four `AMELI_APP_SRI_*` env vars:

```bash
# From a workstation with public internet access (the helper fetches
# the bundles from cdn.jsdelivr.net to compute their sha384 digest).
python tools/sri_compute.py

# Output (paste into your app.env):
# AMELI_APP_SRI_SWAGGER_UI_CSS=sha384-...
# AMELI_APP_SRI_SWAGGER_UI_BUNDLE=sha384-...
# AMELI_APP_SRI_SWAGGER_UI_PRESET=sha384-...
# AMELI_APP_SRI_REDOC_BUNDLE=sha384-...
```

Re-run whenever `SWAGGER_UI_VERSION` or `REDOC_VERSION` change in
`dashboard/views.py` (the script reads those constants and bumps
the URLs accordingly).

Escape hatch for operators behind an air-gapped CDN mirror whose
bundle bytes do not match the upstream hashes:

```bash
AMELI_APP_OPENAPI_SRI_REQUIRED=false
```

This is an informed risk acceptance — the docs panel will render
without SRI even outside `dev`. Document the mirror's own integrity
controls if you use this path.

## Secret rotation

Four secrets live in `/etc/<instance>/app.env`. Their rotation cost and
procedure differ — read the row before you rotate. General rules: never
commit `app.env`; keep the OLD value offline until the new one is verified
(rollback); restart the api service after every rotation; re-run the
relevant smoke.

| Secret (env) | Rotating invalidates | Tooling |
|---|---|---|
| `AMELI_APP_DJANGO_SECRET_KEY` | active **sessions** + signed URLs (password-reset / email-change links) | set + restart |
| `AMELI_APP_MFA_ENCRYPTION_KEY` | **every enrolled TOTP secret** (ciphertext the new key can't open) | none shipped — re-enroll or a one-off re-encrypt |
| `AMELI_APP_AUDIT_HMAC_KEY` | the **audit-chain** verifiability unless re-stamped | `ameli-app rotate-audit-key` (below) |
| DB password (in `AMELI_APP_DATABASE_URL`) | nothing (just the credential) | `ALTER ROLE` + set + restart |

### `AMELI_APP_DJANGO_SECRET_KEY`

Signs session cookies, CSRF, and time-limited tokens. Rotating logs
everyone out and voids pending password-reset / email-change links (no
data loss).

```bash
NEW=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))")
sed -i "s|^AMELI_APP_DJANGO_SECRET_KEY=.*|AMELI_APP_DJANGO_SECRET_KEY=${NEW}|" /etc/<instance>/app.env
systemctl restart <instance>-api.service
```

> **Graceful option (not wired today)**: Django's `SECRET_KEY_FALLBACKS`
> keeps the old key validating existing sessions during a transition. The
> template does not set it (rotation = re-login); adding it is a small
> code enhancement if a zero-logout rotation is ever needed.

### `AMELI_APP_MFA_ENCRYPTION_KEY` — disruptive, read first

TOTP secrets are stored Fernet-encrypted with this key. `decrypt_secret`
falls back to "treat as plaintext" on `InvalidToken`, so rotating **breaks
every existing enrollment silently** — enrolled users simply fail TOTP,
with no error in the logs. Two paths:

- **Re-enroll (simple)**: rotate the key, then have enrolled users re-add
  their authenticator (an admin can disable MFA per user from the panel so
  they can re-enroll). Warn users first.
- **Re-encrypt (no user disruption)**: a one-off script that reads every
  TOTP secret with the OLD key and re-writes it with the NEW key. Not
  shipped — run it with both keys in hand, transactionally:
  1. with the OLD key still active, `decrypt_secret(row)` → plaintext,
  2. swap `MFA_ENCRYPTION_KEY` to the NEW key, `encrypt_secret(plaintext)`,
  3. save. Keep both keys only for the migration window.

**Always verify TOTP after rotating this key**: enroll a test user and
confirm a code validates.

### `AMELI_APP_AUDIT_HMAC_KEY`

Do **not** just change the env — that breaks `verify-audit` on every
pre-rotation row. Use the built-in re-stamping tool ([Rotating the HMAC
key](#rotating-the-hmac-key) below): it walks the chain under both keys so
history stays verifiable.

### DB password

Rotate in Postgres, then update the connection string and restart. The
backup timer reads the same `DATABASE_URL`, so there is no separate change.

```bash
su - postgres -c "psql -c \"ALTER ROLE <app_role> WITH PASSWORD '<new>';\""
sed -i "s|^AMELI_APP_DATABASE_URL=.*|AMELI_APP_DATABASE_URL=postgresql://<app_role>:<new>@127.0.0.1:5432/<db>|" /etc/<instance>/app.env
systemctl restart <instance>-api.service
.venv/bin/python manage.py check     # DB reachable
```

## Audit chain verification (H6)

Enable the HMAC chain by setting `AMELI_APP_AUDIT_HMAC_KEY` in the env
file. From then on every `record_audit` call writes a per-row hmac
plus the previous row's hmac; `ameli-app verify-audit` walks the chain
and reports the first divergence.

Run it manually:

```bash
.venv/bin/ameli-app verify-audit
```

Exit code 0 = clean, exit code 1 = tampering detected. Use range flags
to spot-check a window:

```bash
.venv/bin/ameli-app verify-audit --from-id 1000 --to-id 2000
```

### Schedule it (systemd timer)

The repo ships templates for a per-hour run:

- `deploy/systemd/ameli-app-verify-audit.service`
- `deploy/systemd/ameli-app-verify-audit.timer`

`scripts/install.sh` renders them like the other timers. Wire an alert
hook so a broken chain produces an operator notification:

```ini
# /etc/systemd/system/ameli-app-template-prod-verify-audit.service.d/alert.conf
[Service]
OnFailure=alert-on-audit-tamper.service
```

Where `alert-on-audit-tamper.service` is whatever you already use for
critical alerts (Slack webhook, email, PagerDuty, etc.).

### Rotating the HMAC key

Use case: the key was leaked, or your security policy mandates periodic
rotation. The chain stays verifiable after rotation — the helper
re-stamps every chained row with the new key while preserving the
prev_hmac sequence.

Run these steps as a single shell session so the `OLD_KEY` /
`NEW_KEY` variables stay defined. The recipe is intentionally
paranoid — an empty/typo'd variable blanking the env file is the
exact failure mode the #6 verification hit on dev.

1. **Verify the chain is clean first.** Rotation refuses to run when
   the source chain is broken (it would paper over tampering). Use
   `--strict-precondition` so a pipeline can tell "chain broken,
   can't rotate" (exit 3) apart from other errors (exit 1).
   ```bash
   .venv/bin/ameli-app verify-audit --strict-precondition
   ```
   Must print `{"ok": true, ...}`.

2. **Capture the current key and generate the new one into env
   vars (not argv).** Passing keys as `--from-key/--to-key` puts
   them in `ps`/`/proc/<pid>/cmdline` and shell history. Read them
   into env vars with `read -s` (silent) and use `--from-key-env`
   / `--to-key-env` instead. The guards below abort if either is
   empty.
   ```bash
   OLD_KEY=$(grep '^AMELI_APP_AUDIT_HMAC_KEY=' /etc/ameli-app-template-<env>/app.env | cut -d= -f2-)
   NEW_KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))")
   export OLD_KEY NEW_KEY
   [ -n "$OLD_KEY" ] || { echo "ABORT: OLD_KEY is empty"; return 1 2>/dev/null || exit 1; }
   [ -n "$NEW_KEY" ] || { echo "ABORT: NEW_KEY is empty"; return 1 2>/dev/null || exit 1; }
   [ "$OLD_KEY" != "$NEW_KEY" ] || { echo "ABORT: keys are identical"; return 1 2>/dev/null || exit 1; }
   ```
   If you'd rather not have the new key in your environment at all,
   skip the `export` and use `--to-key-stdin` in step 3.

3. **Run the rotation in one go (recommended).** `--apply-env` makes
   the helper atomically rewrite the env file after the DB is
   re-stamped, so you can't end up with a rotated DB and a stale env
   file (or worse, a blanked env file from a typo'd `sed`). Then
   restart the service.
   ```bash
   .venv/bin/ameli-app rotate-audit-key \
     --from-key-env OLD_KEY \
     --to-key-env NEW_KEY \
     --apply-env /etc/ameli-app-template-<env>/app.env || {
       echo "ABORT: rotation failed; env file untouched"
       return 1 2>/dev/null || exit 1
   }
   systemctl restart ameli-app-template-<env>-api.service
   unset OLD_KEY NEW_KEY   # keep them out of the shell after rotation
   ```
   Exit codes: `0` = full success, `2` = rotation refused (chain
   broken / bad args / unresolvable key), `4` = DB rotated but
   env-file write failed (in-memory key still mismatches;
   investigate before restarting).

   On success the JSON response contains a `next_steps` array and
   `rotated: N`.

   **stdin variant** (when you cannot or don't want to export the
   keys): pipe two lines, from-key first.
   ```bash
   { printf '%s\n%s\n' "$OLD_KEY" "$NEW_KEY"; } | .venv/bin/ameli-app \
     rotate-audit-key --from-key-stdin --to-key-stdin \
     --apply-env /etc/ameli-app-template-<env>/app.env
   ```

   **Legacy two-step variant with raw argv keys** is still
   supported but **discouraged** — the keys are visible in
   `ps`/history:
   ```bash
   # NOT RECOMMENDED: keys land in /proc/<pid>/cmdline
   .venv/bin/ameli-app rotate-audit-key \
     --from-key "$OLD_KEY" --to-key "$NEW_KEY" || {
       echo "ABORT: rotation failed; do NOT touch the env file"
       return 1 2>/dev/null || exit 1
   }
   sed -i "s|^AMELI_APP_AUDIT_HMAC_KEY=.*|AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY|" \
     /etc/ameli-app-template-<env>/app.env
   systemctl restart ameli-app-template-<env>-api.service
   ```

4. **Sanity-check the post-rotation chain.**
   ```bash
   .venv/bin/ameli-app verify-audit
   ```
   Must again print `{"ok": true, ...}` with the new tally including
   the rotation row.

**Caveats**:

- The OLD key cannot verify the chain anymore after step 3. Keep an
  offline copy if you need to retain "history was signed under that
  key" as evidence — anyone with the old key can verify against a
  point-in-time export from before step 3.
- If step 3 fails mid-walk for any reason, the transaction rolls back
  and the chain stays under the old key. You can retry.

If you'd rather wipe and start fresh (e.g. after an irrecoverable
break), use this older recipe instead — it discards verifiability of
the historical rows:

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.audit.models import AuditEvent
AuditEvent.objects.update(hmac='', prev_hmac='')
"
# then update AMELI_APP_AUDIT_HMAC_KEY and restart
```

### Disaster recovery: the key is GONE (`/etc` lost, database kept)

The rotation recipe above needs `OLD_KEY` to re-stamp the rows. When the
env file is gone, that key is gone with it, and **no procedure can make
the existing rows verifiable again** — that is the whole point of an HMAC
chain. Plan for it before it happens.

**How you get here.** Restoring a database backup onto a rebuilt host,
re-running `install.sh` after wiping `/etc/<instance>/`, or migrating an
instance without carrying the env file. `install.sh` generates a *new*
`AMELI_APP_AUDIT_HMAC_KEY` whenever the key is missing (it is idempotent
only while the file survives), so the deploy comes back up looking
healthy while `/health` reports:

```json
"audit_chain": { "ok": false, "detail": { "tail_id": 1, "match": false } }
```

and the overall status is `DEGRADADO`. Nothing is corrupt — the rows are
simply signed with a key nobody has.

**Prevention (do this now, not after).** The audit key belongs in your
backup set alongside the database. `scripts/backup.sh` dumps the DB, *not*
`/etc/<instance>/app.env`. Keep an offline copy of the three generated
keys — `AMELI_APP_DJANGO_SECRET_KEY`, `AMELI_APP_AUDIT_HMAC_KEY`,
`AMELI_APP_MFA_ENCRYPTION_KEY` — in your secret manager. Losing the MFA
key has the same shape: every enrolled TOTP secret becomes undecryptable.

**If it already happened**, decide explicitly and record the decision:

1. **The historical rows stay unverifiable, and you say so.** Keep them
   as-is. `verify-audit` will keep failing from row 1, so the timer alert
   is useless until you cut the chain. Note the incident, the date and
   the id range in your compliance log — silently clearing the flag is
   the one thing you must not do.
2. **Cut the chain at the recovery point.** Clear the hmac columns with
   the wipe recipe above so verification starts fresh from the next
   event. You lose tamper-evidence for everything before the cut; the
   rows themselves are untouched and still readable in `/admin/audit`.

Either way, `verify-audit` after the decision must return `ok: true`, or
the hourly timer's alert becomes background noise that trains operators
to ignore a real tampering signal.
