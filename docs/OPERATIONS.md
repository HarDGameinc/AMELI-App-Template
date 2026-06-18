# Operations

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

The preferred local path is to set `DATABASE_URL` to PostgreSQL. If no local
database is available yet, SQLite can be used temporarily through
`AMELI_APP_SQLITE_PATH`.

## Linux install

```bash
sudo APP_ENV=dev APP_SLUG=ameli-new-app APP_PACKAGE=ameli_new_app bash scripts/install.sh
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

## Health checks

```bash
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/api/health
```

## First install reference

Use the full first-install walkthrough in:

- `docs/FIRST_INSTALL_DJANGO.md`

## Backup + restore

```bash
# create an archive
sudo APP_ENV=prod bash scripts/backup.sh

# verify an archive without touching the live deploy (cron-friendly)
sudo APP_ENV=prod bash scripts/restore.sh verify /var/backups/<archive>.tar.gz

# restore (destructive)
sudo APP_ENV=prod bash scripts/restore.sh restore /var/backups/<archive>.tar.gz --yes
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

## Avatar AV scan (ASVS V12.4.1)

Avatar uploads can be funnelled through an antivirus scanner before
they hit disk. Opt-in by setting ``AMELI_APP_AV_ENDPOINT`` to one of:

- ``tcp://host:port`` — clamd over TCP (INSTREAM). The classic
  deployment: ``apt install clamav-daemon`` on the same host, then
  ``AMELI_APP_AV_ENDPOINT=tcp://127.0.0.1:3310``. Port defaults to
  3310 if omitted.
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

Quick test with the EICAR test signature (a harmless file every AV
must catch as a sanity check):

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
   sudo -E .venv/bin/ameli-app rotate-audit-key \
     --from-key-env OLD_KEY \
     --to-key-env NEW_KEY \
     --apply-env /etc/ameli-app-template-<env>/app.env || {
       echo "ABORT: rotation failed; env file untouched"
       return 1 2>/dev/null || exit 1
   }
   sudo systemctl restart ameli-app-template-<env>-api.service
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
   { printf '%s\n%s\n' "$OLD_KEY" "$NEW_KEY"; } | sudo .venv/bin/ameli-app \
     rotate-audit-key --from-key-stdin --to-key-stdin \
     --apply-env /etc/ameli-app-template-<env>/app.env
   ```

   **Legacy two-step variant with raw argv keys** is still
   supported but **discouraged** — the keys are visible in
   `ps`/history:
   ```bash
   # NOT RECOMMENDED: keys land in /proc/<pid>/cmdline
   sudo .venv/bin/ameli-app rotate-audit-key \
     --from-key "$OLD_KEY" --to-key "$NEW_KEY" || {
       echo "ABORT: rotation failed; do NOT touch the env file"
       return 1 2>/dev/null || exit 1
   }
   sudo sed -i "s|^AMELI_APP_AUDIT_HMAC_KEY=.*|AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY|" \
     /etc/ameli-app-template-<env>/app.env
   sudo systemctl restart ameli-app-template-<env>-api.service
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
