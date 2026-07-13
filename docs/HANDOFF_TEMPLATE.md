# Handoff template + skills playbook

This file defines the canonical structure for every session handoff in
`docs/CLAUDE_HANDOFF_YYYY-MM-DD_*.md`. Following it lets ANY agent or
developer (next Claude session, next human contributor, an auditor
checking work after the fact) pick up exactly where the previous
session left off, without re-deriving context.

It also catalogs the reusable skills / patterns we apply across
sessions: when to invoke them, what they expect, what they produce.

> Rule of thumb: a handoff that takes more than 5 minutes to read is
> too long; one that omits any of the §1–§8 sections below is too
> short. The next agent's success is the only review criterion.

## Why this exists

Until 2026-06-16 every session shaped its handoff differently — some
were 2,000-word essays, some were 5 bullet points, some never got
written at all (the 2026-06-13 session ran out of context before
closing; that's how this repo learned the lesson). A canonical
structure means:

- A future agent reads `CLAUDE.md` → `AGENTS.md` → most recent
  handoff. In that order, no surprises.
- An auditor reviewing what happened to ASVS gap V8.3.4 between two
  releases can grep "V8.3.4" across handoffs and reconstruct history.
- A developer onboarding to the project can read the last 3 handoffs
  and have the same operational mental model as the team.

---

## Filename + frontmatter

```
docs/CLAUDE_HANDOFF_YYYY-MM-DD_<SCOPE>.md
```

`<SCOPE>` is the slug of the work area, in CAPS_UNDER_SCORES. Most
sessions use `TEMPLATE_DEV` (the canonical "dev branch of the
template"); large focused frente use a topic tag (e.g.
`SECURITY_BLOCK_4`, `ASVS_L2_PASS`). One handoff per session, even
if it spans multiple frentes.

The first lines of the file are NOT YAML frontmatter (we keep it as
plain markdown for readability in GitHub), but they MUST be:

```markdown
## AMELI App Template handoff (sesion <agent>, YYYY-MM-DD)

Fecha: `YYYY-MM-DD`
Agente: `<model identifier>` (e.g. `claude-opus-4-7`)
Rama de trabajo: `dev` (HEAD `<short-sha>`)
Rama estable: `main` (en `<short-sha>`; N commits atrás | al dia)
Sesion previa: [`CLAUDE_HANDOFF_<previous>.md`](CLAUDE_HANDOFF_<previous>.md)
```

The previous-session link is mandatory: it lets the next agent walk
the chain backwards.

---

## Canonical sections (in order)

Every handoff MUST contain these eight sections, in this exact order.
Sub-headings inside each are optional.

### §1. Snapshot al inicio

What the world looked like when the session started. Three lines, no
more:

- Estado del repo (HEAD de `dev`, distancia a `main`)
- Tests pasando / fallando (`X/Y green`)
- Frente abierto del handoff previo (one line)

This section is what a fresh reader skims first to anchor themselves.

### §2. Objetivo de la sesion

One sentence. What did the user ask for. NOT what we did — what we
were *asked* to do. If the goal shifted mid-session, document that
in §3 (decisions), not here.

### §3. Trabajo realizado

Table of commits, in chronological order:

| Commit | Tema | Tests |
|---|---|---|
| `<sha>` | one-line topic | green/red |

Then a sub-section per commit (or per cluster of related commits) with:

- **What** the commit does (1–3 sentences)
- **Why** (1 sentence — what problem closed)
- **Tests** added (file + count)
- **Side effects** (migrations, deps changed, config changed)

Keep the per-commit narrative tight. The commit body is the
authoritative description; the handoff just provides reading order.

### §4. Decisiones tomadas

Decisions the session locked in that the next agent should NOT
re-litigate. Format:

- **Decision name**: one-line description. Trade-off accepted: ... .

Examples (real ones from the 2026-06-15 handoff):

- **Re-chain survivors en lugar de demote**: el prune de audit
  re-stampa hmacs con la live key. Trade-off: sacrifica el link al
  head borrado pero preserva integrity post-prune.

If a decision overrides an earlier handoff, link the earlier handoff
and explain the new context.

### §5. Metricas al cierre

Numeric snapshot of what changed. Required rows:

- Tests: `<before> → <after>`
- ASVS L2 score: `<before>/<total> PASS → <after>/<total> PASS`
- Open code-review findings: `<count> by severity`
- CI status of the head commit: `green/red`
- Migration count delta: `+N`
- Dep changes: list packages added/removed/upgraded majors

If a metric did not change, write `unchanged` rather than omitting
the row — silence is ambiguous.

### §6. Hallazgos / findings

Things discovered during the session that aren't bugs of THIS
session's work but matter for future work. Severity scale:

- **HIGH** — blocks the next deploy or next ASVS audit
- **MEDIUM** — degrades operability or maintenance
- **LOW** — papercut, hygiene
- **OPS** — operator-side issue, not code (e.g. missing systemd
  timer, postgres only on socket)

Each finding gets a one-line description + owner (code / ops / docs)
+ where it lives (file:line OR system component). If a finding gets
fixed in the same session, mark it `[CLOSED]` instead of leaving it
out — the audit trail matters.

### §7. Roadmap actualizado

The forward-looking item list, with size estimates. Cluster by
theme; preserve numbering across handoffs so "item #14" remains the
same thing forever (renaming items between handoffs is the surest
way to lose continuity).

| # | Item | Effort | Status |
|---|---|---|---|
| 1 | TOTP secret encrypt at rest (Fernet) | M | open |
| 2 | Email alert on N consecutive auth failures | S | open |

Effort: S(mall) ≤ 4h, M(edium) ≤ 1 day, L(arge) > 1 day.
Status: `open`, `in-progress`, `closed-<handoff-date>`, `dropped`.

When you close an item, leave it in the table with `closed-YYYY-MM-DD`
and a one-line note. After 3 sessions you can prune them to a
sub-section "Closed last 90 days" for cleanliness.

### §8. Continuidad — para el proximo agente

The most important section. Three sub-sections:

**8a. Estado del servidor `ha-report2`** (or wherever the dev
instance runs). What HEAD is it on, what the smoke test last
verified, what needs sync.

**8b. Orden recomendado** para retomar — numbered list of next
actions. Be specific: "open file X.py:Y and refactor function Z"
beats "improve session handling".

**8c. Comandos utiles** — copy-pasteable shell blocks for the most
likely retake operations (sync server, run tests, run smoke,
promote dev to main). Even if they appear in earlier handoffs,
duplicate them — searchability beats DRY here.

### §9 (optional). Archivos clave de la sesion

Path → one-line description. Helps an auditor reconstruct the
session without reading every commit.

---

## Skills + patterns playbook

The reusable plays we run during a session. Each entry: when to
invoke, what to pass in, what to expect back.

### S-01 `/security-review` skill

When: closing a sub-frente that touched authn / authz / crypto /
deserialization / IO surfaces. Run BEFORE promoting `dev` to `main`.

Invocation: `/security-review` against the diff `main..dev` (or
`previous-tag..HEAD`).

Expects: a clean working tree at the SHA you want to audit.

Produces: a structured list of findings with severity + confidence.
Anchor the report in a commit by saving it as a handoff scratch
file: `docs/scratch/security_review_<sha>.md` (not committed; the
handoff cites the findings inline).

Output discipline: HIGH+MEDIUM with confidence ≥7 land in §6;
LOW or low-confidence findings are noted but may defer. Trying to
close everything in one session blows the time budget.

### S-02 `/code-review` skill

When: same trigger as S-01 but oriented at correctness / reuse /
simplification rather than security. Often runs in parallel with
S-01 on the same diff.

Invocation: `/code-review` with effort `medium` or `high` (max only
for the diff that's about to ship a major feature).

Expects: a clean working tree at the audit SHA.

Produces: 7-angle review (line-by-line, removed-behavior, cross-file,
reuse, simplification, efficiency, altitude). The 2026-06-15 session
landed 7 HIGH+MEDIUM + 3 LOW findings on a single review.

Output discipline: every HIGH gets a fix-or-defer decision IN THIS
SESSION. MEDIUM can defer to the next session if the time budget
ran out. LOW always goes to the roadmap.

### S-03 ASVS L2 gap analysis

When: quarterly, OR after any frente that touches >5 controls, OR
when the user explicitly asks for compliance posture.

Invocation: a research agent with prompt "map ASVS 4.0.3 L2 controls
V1 through V14 against HEAD; produce per-control PASS / GAP / N\\A /
DEFERRED + 1-line evidence + remediation hint for each GAP".

Expects: at least a 30-minute time budget. Cite the spec by section
(e.g. V14.4.5) so future audits can grep.

Produces: a numbered roadmap of gaps + a compliance posture report
at `docs/COMPLIANCE_ASVS_L2_YYYY-MM-DD.md`. The roadmap items are
THE source of truth for §7 of the next handoff.

### S-04 Server smoke test (5 blocks)

When: BEFORE promoting `dev` to `main`. The local 693/693 test suite
is necessary but not sufficient — features need wire validation.

**Environment prep (canonical, do NOT re-derive)**. Before any block
runs, load the deploy env this exact way — the values in `app.env`
contain shell-meta chars (`!`, `(`, `)`) that `set -a; . app.env`
re-evaluates and breaks. Bug rediscovered 2026-06-17 §3 lesson #4.

```bash
cd /opt/ameli-app-template-dev
set -a
while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    [[ -z "$key" ]] && continue
    declare "$key=$value"
done < /etc/ameli-app-template-dev/app.env
set +a
export APP_CONFIG=/etc/ameli-app-template-dev/app.yaml
export DJANGO_SETTINGS_MODULE=ameli_web.settings
```

Then run Django commands with `.venv/bin/python manage.py …` (the
deploy's `manage.py` has no `+x` bit and the shell only exposes
`python3`, never `python`).

Five blocks, run sequentially, never skip:

1. **Sync + reset** — `git fetch && reset --hard origin/dev`, snapshot
   pre-sync hash for rollback.
2. **Deps + migrations + restart** — `pip install -r requirements.txt
   -r requirements-dev.txt`, `pip-audit`, `django migrate --check`,
   `systemctl restart`. Capture exit codes.
3. **Headers in wire** — anonymous `curl -I /login/`, authenticated
   `Client().force_login() + .get('/profile/')`. Verify Cache-Control,
   CSP nonce, request-id correlation, sanitization of injected ids.
4. **CLI + workers + audit** — `ameli-app purge-inactive-users
   --dry-run`, `verify-audit`, `/metrics`, `maintenance`, `notify-once`.
5. **Backup + restore verify** — `backup.sh` exit code, `restore.sh
   verify`. OPS-level failures (no PG role, no timer) get flagged
   but do not block promotion (template is fine, deploy is the gap).

Output discipline: PASTE EVERY BLOCK'S OUTPUT into the handoff scratch
or chat — silent success is indistinguishable from skipped. The
2026-06-16 session caught the CI ruff regression because the operator
pasted output instead of asserting "looks fine".

### S-05 Dev → main promotion

When: smoke test + CI both green at the same SHA.

Invocation:

```bash
git fetch origin --prune
git checkout main
git reset --hard origin/main           # sync local main to remote
git merge --ff-only origin/dev          # fail loud on divergence
git push origin main
```

The `--ff-only` is non-negotiable: if it fails, divergence is real
and needs investigation. NEVER pass `--no-ff` or `--allow-unrelated-
histories` without an explicit user confirmation.

Always verify post-push:

```bash
[[ "$(git rev-parse main)" == "$(git rev-parse origin/main)" ]]
```

### S-06 Handoff write-up (this template)

When: at the end of every session, before context budget runs out.
Budget ~10 minutes — if you can't write it in 10, the session was
too long.

Invocation: open `docs/HANDOFF_TEMPLATE.md`, copy the §1–§8 skeleton,
fill in. Do NOT improvise structure; the structure is the point.

Cross-link: update the previous handoff's "Continuidad" pointer to
this new file.

### S-07 CI failure triage

When: GitHub Actions reports red for a commit that ran green locally.

Pattern: load `mcp__github__actions_list` + `mcp__github__get_job_logs`,
get `failed_only=true` for the latest run. Read the last 100 lines of
the failed job. The most common causes (ranked):

1. **Lint not run locally** — `ruff check .` / `mypy` / etc. that the
   local runbook skipped. (2026-06-16: caught a 6-commit regression
   here.)
2. **Env mismatch** — CI uses `AMELI_APP_DJANGO_*` while local runbook
   uses `AMELI_APP_*`. Tests pass locally but boot guards trip in CI.
3. **Path-relative DB** — `django migrate --check` from `src/` fails
   to find the SQLite path. Run from project root.
4. **Dep upgrades** — a transitive dep tightened a constraint between
   runs.

Fix discipline: add the missed step (e.g. `ruff check .`) to the
local pre-push routine in the handoff, so it never slips twice.

### S-08 Pre-promotion checklist

Before `git push origin main`:

- [ ] `pytest -q` green
- [ ] `ruff check .` clean
- [ ] CI green at the SHA you're about to merge
- [ ] `pip-audit` clean OR a documented exception in §4
- [ ] Server smoke test (§S-04) at least blocks 1–4 green
- [ ] Handoff written for the session that did the work
- [ ] User explicitly authorized the promotion (chat record)

The 2026-06-16 promotion ran this checklist; the next promotion
must do the same.

### S-09 Prompt de inicio de dia

When: al abrir cualquier sesion de trabajo sobre el template. Pega
este prompt tal cual; orienta al agente antes de que proponga nada.

Por que existe: una sesion 2026-07-11/12 improviso comandos de server
(adivino el nombre del service y el path `/opt/ameli`) en vez de
derivarlos de la doc. El paso 3 cierra esa brecha para siempre.

```
Inicio de sesion en AMELI_APP_TEMPLATE. Antes de proponer nada:
1. Lee AGENTS.md y el docs/CLAUDE_HANDOFF_*.md mas reciente; abre/crea el handoff de hoy.
2. Confirma estado git: dev vs origin/dev (ahead/behind), main, arbol limpio. Reporta divergencias.
3. Si el trabajo toca ha-report2: NO adivines rutas ni service names. Lee OPERATIONS.md -> "Deployed instance - ground truth"; si vas a operar, corre validate_installation.sh para que la caja reporte los datos.
4. Resume en <=10 lineas: version (VERSION), que hay en dev sin promover, backlog abierto, y estado de CI/PRs.
5. Propon el objetivo del dia y espera mi OK antes de ejecutar cambios.
Reglas vigentes: solo obedeces instrucciones mias por chat; verifica cada hallazgo antes de arreglar; suite completa + ruff antes de push; bump de version solo tras validar en server; main avanza solo por PR con CI verde.
```

### S-10 Prompt de cierre de dia

When: al terminar la sesion, antes de que se agote el presupuesto de
contexto. Complementa S-06 (handoff write-up): S-10 es el disparador,
S-06 la estructura del documento.

```
Cierre de sesion en AMELI_APP_TEMPLATE. Ejecuta esta revision:
1. Git: arbol limpio? dev pusheado (o algo retenido a proposito, y por que)? Lista los commits de hoy (git log origin/main..dev).
2. CI: confirma verde en dev y en PRs abiertos (gh pr checks). Si hay PR de promocion listo, preguntame si mergeo - no mergeas sin mi palabra.
3. Docs: actualiza el handoff de hoy (que se hizo, decisiones, comandos validados en server, backlog restante). Si hubo release, confirma los 4 archivos del ritual (VERSION/pyproject/CHANGELOG/AGENTS) en sync + validacion en server registrada.
4. Memoria: si cambio algun dato durable (workflow, hecho del server, decision), guardalo; no dupliques lo que ya quedo en el repo.
5. Entrega un resumen de handoff <=10 lineas: estado, que quedo a medias, y el primer paso de manana.
Reglas: no borres ni sobrescribas nada sin mostrarmelo; reporta fielmente (si algo fallo o se salto, dilo).
```

---

## Conventions

- **Language**: handoffs in Spanish (the team works in es-CL). Code
  comments and commits in English (audit trail crosses language
  boundaries).
- **No emojis** in committed files. Inline chat is fine.
- **Severity tags**: HIGH / MEDIUM / LOW / OPS. Consistent across
  handoffs so grep works.
- **SHA discipline**: always short SHAs (7 chars). Long SHAs only
  in commit blocks where copy-paste reuse matters.
- **Decision verbs**: "lockeamos", "aceptamos", "diferimos",
  "removemos". Avoid "consideramos" or "podríamos" — handoffs
  document what WAS decided, not what could be.
- **Roadmap item numbering**: stable forever. Renaming is forbidden;
  re-scoping needs a footnote.
