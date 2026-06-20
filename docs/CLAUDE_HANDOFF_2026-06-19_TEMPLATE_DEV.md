## AMELI App Template handoff (sesion Claude, 2026-06-19)

Fecha: `2026-06-19`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del fix throttle ceil)
Rama estable: `main` (en `88cce00`; pendiente promote PT-1)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-18_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-18_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `dev @ d1f046b`, `main @ 88cce00`. Diferencia
  4 commits (`b94dfcc`, `d91ef8d`, `9df29c4`, `d1f046b`).
- Tests local: 882 passed sin deselect.
- CI: ultimo run `#93` sobre `d1f046b` rojo en Python 3.12 con
  `test_forgot_password_throttle_after_too_many_requests`
  (assert 200 == 429). CI `#92` sobre el parent `9df29c4` verde
  — el commit del fail es solo docs (handoff close), asi que
  NO es regresion introducida por el cambio: es un nuevo flake.
- ASVS L2: **151 PASS / 0 strict-tracked GAP**.
- Frente abierto del handoff 18-jun §8: **PT-1..PT-4** wire
  tests pendientes para retomar en otro equipo.

## §2. Objetivo de la sesion

Resolver el flake CI nuevo (lo primero, sin esto no se promueve
nada), retomar PT-1 (promote `dev → main`) y avanzar con
PT-2/PT-3/PT-4 segun lo que sea aplicable desde este entorno.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `67ae53a` | Fix CI flake — `_read_throttle_counter_sliding` cambia `int()` truncation por `math.ceil` (rate limiter no debe under-contar) + test guard | 882 → 883 (+1) |
| — | **PT-1** Promote `dev → main` (`88cce00..67ae53a`, 5 commits) — CI #94 verde | suite stays green |

### Wire validation 2026-06-19 — PT-1, PT-2, PT-3

Branch promote ejecutado desde el sandbox checkout que tenia el
pre-push hook instalado de ayer (PT-2 layer 1 ya activo).
Cadena de pruebas:

1. **PT-2 layer 1 (client hook) atrapa la version sin bypass**:
   ```
   $ git checkout main && git push origin main
   [pre-push] Direct push to 'main' refused.
   ...
   error: failed to push some refs
   ```
   El push regular se rechaza con el mensaje canonico del hook
   (`deploy/git-hooks/pre-push:36`). El operador queda forzado
   a usar bypass o PR.

2. **PT-2 bypass funciona como documentado**:
   ```
   $ ALLOW_DIRECT_PUSH=1 git push origin main
   [pre-push] ALLOW_DIRECT_PUSH=1 set; skipping branch-protection check
   To .../HarDGameinc/AMELI-App-Template
      88cce00..67ae53a  main -> main
   ```
   Push completado, hook reconoce el bypass.

3. **PT-3 layer 2 (audit workflow) detecta el direct push**:
   `Main push audit #1` corrio sobre `67ae53a`. Job
   `Audit direct pushes to main` exit 0, log:
   ```
   ##[warning]commit 67ae53a by Claude <noreply@anthropic.com>
       -- subject: fix sliding-window throttle: ceil prev contribution
   This commit landed on main without going through a PR merge.
   On a private + Free-plan repo, GitHub does not enforce branch
   protection server-side. The pre-push hook
   (scripts/install-pre-push-hook.sh) is the client-side guard;
   this job is the audit-log substitute.
   ```
   Anotacion `::warning::` greppable en Actions. **PT-3 layer 2
   wire-verified end-to-end**.

4. **PT-3 layer 3 (latente)**: Rulesets + classic rules siguen en
   repo settings sin enforce hasta upgrade a Team. NO se prueba
   en wire (ya documentado como inactivo).

**PT-1 status**: cerrado. `main == dev == 67ae53a`.
**PT-2 layer 1 status**: cerrado para este checkout (hook
instalado y verificado). Para Windows + ha-report2 sigue como
PT-pendiente — `bash scripts/install-pre-push-hook.sh`.
**PT-3 status**: cerrado (layer 2 wire-verified; layers 1 y 3
ya cubiertos).

### Wire validation 2026-06-19 — PT-4 (backup + PG TCP + timer)

Server `ha-report2`, branch `dev` con codigo de hoy
(`061ef5e` final). PT-4 surface 3 bugs latentes que pasaron
todos los unit tests pero rompian el flujo real del deploy.

**Bloque 1 — pre-push hook en ha-report2**: instalado OK.

**Bloque 2 — estado PG**:
- PG 17 ya escucha TCP en `127.0.0.1:5432` y `[::1]:5432`
  (default de PG 17 = `listen_addresses = 'localhost'`).
- `pg_hba.conf` ya tiene
  `host all all 127.0.0.1/32 scram-sha-256`. **#19 estaba
  hecho del lado PG sin que lo supieramos**; el roadmap
  bullet decia "configurar PG TCP" pero el deploy real lo
  tenia desde el dia 1.

**Bloque 3 — backup.sh primer run**:
```
WARN: no DATABASE_URL nor AMELI_APP_SQLITE_PATH — DB dump skipped
Backup creado: /var/backups/ameli-app-dev/ameli-app-dev-20260619-110758.tar.gz
```
Archive creado, **pero SIN DB dump y en path equivocado**
(`/var/backups/ameli-app-dev/` en lugar de
`/var/backups/ameli-app-template-dev/`). Wire test detecto
lo que ningun unit test podia ver.

**Bug 1 — slug derivation incorrecta en `_common.sh`**:
`APP_SLUG` no exportada → default `ameli-app` →
`APP_INSTANCE=ameli-app-dev` → `ENV_FILE=/etc/ameli-app-dev/app.env`
(no existe) → `DATABASE_URL` nunca leida → WARN + archive
sin DB. Fix en `cfb3086`: derivar slug del basename del
PROJECT_DIR (strip `-dev`/`-prod`). 4 tests pin el contrato.

**Bug 2 — `pg_dump` rechaza la URL con driver suffix**:
Despues del fix #1, `backup.sh` leyo
`DATABASE_URL=postgresql+psycopg://...` y se lo paso a
pg_dump. libpq NO entiende `+psycopg`, descarta la URI,
cae a default socket + peer auth con el OS user (root) →
`FATAL: no existe el rol root`. Fix en `061ef5e`: sed
strip de `+<driver>` ANTES de pg_dump. 7 tests pin la
normalizacion (psycopg, psycopg2, asyncpg, bare passthrough,
path-substring no-touch, contract pin del sed en el
script).

**Bug 3 — `git reset --hard origin` (sin `/dev`)**:
Operador escribio el comando truncado. `origin` resuelve
a `refs/remotes/origin/HEAD` = default branch = main, y
main estaba 3 commits atras de origin/dev. HEAD termino en
`67ae53a` (commit del flake fix) en lugar de `061ef5e`.
Sintoma: backup.sh seguia con el bug 1 visible porque el
codigo nuevo no llegaba al checkout. Lecccion: **siempre
explicitar la branch en `git reset --hard origin/<branch>`**
y verificar HEAD con `git log -1` antes de retest.

**Bloque 4 — backup post-fixes verde**:
```
Dumping Postgres -> /tmp/ameli-app-template-dev-backup-q6nknt/db.pgdump
Backup creado: /var/backups/ameli-app-template-dev/ameli-app-template-dev-20260619-112201.tar.gz (42K)
```
DB dumpeada correctamente, archive en el path canonico.

**Bloque 5 — restore verify**:
```
Extracting into /tmp/ameli-app-template-dev-restore-nHKZET
Verifying MANIFEST checksums
Manifest OK
Verify mode complete; live system untouched.
```
Contract test del backup pasa end-to-end. El archive no
solo se crea, sino que ademas se sabe restaurar.

**Bloque 6 — systemd timer activo**:
```
$ APP_SLUG=ameli-app-template APP_ENV=dev bash scripts/install.sh
RESUMEN: OK=23 WARN=0 FAIL=0
[OK] ENABLED ameli-app-template-dev-backup.timer
[OK] ACTIVE  ameli-app-template-dev-backup.timer

$ systemctl list-timers '*ameli*' --no-pager
...
Sat 2026-06-20 04:11:55 -04   16h   -    ameli-app-template-dev-backup.timer
```
`install.sh` renderizo y activo el unit junto con el resto
del stack. Proximo trigger del primer backup automatico:
`Sat 2026-06-20 04:11:55 -04` (04:10 + RandomizedDelaySec
de ~1m55s). Wire test del backup automatico se completa
**en 16h** y queda para registrar en el handoff del 20-jun.

**PT-4 status**: cerrado al nivel codigo + activacion del
timer. Wire test del run automatico (primer trigger
nocturno) queda pendiente y se valida con
`journalctl -u ameli-app-template-dev-backup.service --since today`
+ `ls /var/backups/ameli-app-template-dev/` el 20-jun.

### Doc-hygiene cleanup (86186c3)

Audit amplio sobre el sprint entero (no solo el dia). Detectados
y corregidos 3 problemas de coherencia documental:

1. `SECURITY.md` R-04 tagged "Mitigation pending" pese a que el
   item #14 (lockfile + `--require-hashes`) lo cerro el 18-jun.
   Actualizado a "Closed 2026-06-18" con todas las referencias.
2. R-IDs no alineados entre `SECURITY.md` y `COMPLIANCE.md`:
   compliance R-04 = sudo replay nonce; security R-04 = dep pins.
   Reconciliados; agregados R-09 (sudo replay) y R-10
   (body parsing) a SECURITY.md.
3. Dos strict GAPs (V11.1.5, V13.1.5) marcados sin la etiqueta
   "accepted" — re-tagueados `**GAP-accepted**` con cross-ref a
   sus R-IDs en SECURITY.md. Sin estos marks, un scan greps un
   "pending" donde la realidad es residual aceptado.

### Independent security re-audit (d785518) — 2 bugs latentes encontrados

Despues del cleanup, lanzamos dos agentes paralelos en read-only
mode:
- Code quality audit sobre los archivos shippeados en el sprint.
- Security re-audit "trust but verify" sobre las claims de
  151/151 PASS.

**Code quality**: 4 findings, todos falsos positivos o de
estilo preventativo. Cero acciones.

**Security re-audit**: 3 findings; 2 reales materiales:

[HIGH] `AMELI_APP_AUDIT_HMAC_KEY` sin boot guard. Patron
inconsistente con `MFA_ENCRYPTION_KEY` (que SI hard-failea).
Un operador que olvida exportar la key en prod silenciosamente
desactiva la integridad del audit chain (ASVS V7.3.2, V6.3.1).
`verify_audit_chain` refuses to verify, pero solo lo descubris
cuando manualmente probas — entre tanto el chain claim es
vacuously satisfied. Fix: mirror del MFA pattern — outside dev,
empty raises RuntimeError con instrucciones single-screen.

[MED] `AMELI_APP_AV_ENDPOINT` scheme sin validar at boot. Un
typo como `file:///etc/passwd` o `av-host:3310` (sin scheme)
parseaba bien al boot, pero el runtime `av.py` devolvia
`check_failed` y el upload se completaba (fail-open por
diseno). Fix: boot guard rechaza cualquier scheme distinto de
`tcp://`, `http://`, `https://`.

[LOW] `HEALTH_METRICS_ALLOWLIST` empty = open. Documentado por
design pero el comentario en OPERATIONS.md vale claridad. Lo
dejo como-esta; no es bug.

**Tests nuevos** (5): boot guard AUDIT_HMAC_KEY (3), boot
guard AV_ENDPOINT (2). Suite 894 → **898 passed**.
**Helpers actualizados** (2): los fixtures de
`test_settings_boot_guards.py` y `test_host_cookie_prefix.py`
auto-setean AUDIT_HMAC_KEY para prod tests, mismo patron que
ya tenian para MFA.
**SECURITY.md gana R-11 (closed)** y **R-12 (closed)** con
status traceable.

### Leccion sprint-wide — auditor externo VS self-review

El sprint cerro 151/151 controles L2 con "0 strict GAPs" segun
self-review. Una segunda mirada independiente con LITERALMENTE
NADA de codigo nuevo en 24h encontro 2 bugs materiales. Es la
misma leccion del wire test (PT-1..PT-4 surfaced 3 bugs
template-side que unit tests no veian) escalada al doc nivel:
**el que escribio las pruebas no es el que las puede auditar
imparcialmente**. Patron a incorporar al S-04 del playbook:
despues de declarar un capitulo ASVS al bar L2, mandar UN
agente independiente a buscar lo que no vimos. Costo: 5 min de
agent + 30 min de fix. ROI: 2 HIGH/MED bugs evitan llegar a
prod silenciosamente.

## §4. Decisiones tomadas

1. **Flake = bug latente, fix en producto**. El truncation
   en `_read_throttle_counter_sliding` no era "ruido CI" —
   era un rate limiter que perdia 1 unit por 0.5% de los
   requests. La regla nueva: ningun test marcado como
   "flaky" sin entender el mecanismo Y descartar el path
   de fix en producto.
2. **Slug derivation comun entre Python y bash**. `manage.py`
   (#20) y `_common.sh` (PT-4) usan el MISMO heuristic
   (dir basename). Cuando agreguemos `ROLE_OPERATOR` o
   cambiemos el slug, ambos siguen el mismo camino.
3. **PG TCP localhost YA estaba configurado en `ha-report2`**;
   el roadmap bullet #19 era preventivo, no reactivo.
   Documentado para no buscar problema donde no hay.
4. **No promote inmediato post-PT-4**: la sesion deja `dev`
   con 4 commits adelantados (`67ae53a..061ef5e`). El
   operator promueve a `main` cuando vuelva al equipo con
   `gh` autenticado, o usa el bypass del pre-push hook.

## §5. Metricas al cierre

| Metrica | Inicio dia | Cierre dia | Δ |
|---|---|---|---|
| Suite local (sin deselect) | 882 (1 failure CI #93) | **898** | +16 (+1 throttle ceil, +4 slug autodetect, +7 pg_url, +5 boot guards) |
| ASVS L2 active rows PASS | 151 | 151 | 0 |
| Roadmap items abiertos | 0 | 0 | 0 |
| Wire tests ejecutados | 0 | **6** (PT-1 promote, PT-2 hook, PT-3 audit, PT-4 backup, PT-4 verify, PT-4 timer) | — |
| Bugs latentes descubiertos | 0 | **5** (throttle truncation, slug fallback, pg_url libpq incompat, AUDIT_HMAC_KEY guard, AV_ENDPOINT scheme guard) | +5 |
| Residual risks register entries | 8 (R-01..R-08) | **12** (R-01..R-12; +R-09 sudo replay doc, +R-10 body limits doc, +R-11/R-12 boot guards closed) | +4 |
| Commits sobre `dev` | 0 (start at `d1f046b`) | 8 (`67ae53a..d785518`) | — |
| Version | `v0.3.0-django` | **`v0.3.1-django`** | patch bump |
| CI verde | 1 failure / 1 ultimo run | 4 verdes consecutivos | drastic recovery |

## §6. Hallazgos / findings

1. **`_read_throttle_counter_sliding` under-cuenta al edge**.
   El `int(prev_count * prev_weight)` trunca; un rate limiter
   debe usar `ceil`. Cualquier formula que mezcle floats con
   integer-conversion para una decision de seguridad debe
   redondearse hacia "mas estricto", no hacia "mas permisivo".
2. **`_common.sh` cae a slug literal `ameli-app` sin
   `APP_SLUG=` explicito**. La default era razonable para el
   template canonico, pero un deploy multi-instancia (que es
   el unico uso real) la rompe. La derivacion desde el
   dirname matchea install.sh + manage.py.
3. **libpq descarta URIs con scheme desconocido y cae al
   socket default**. Esto NO es documentado claramente en
   `pg_dump --help`; los logs solo dicen "FATAL: no existe el
   rol root". El normalizer del scheme es defensa
   anti-silencioso.
4. **`git reset --hard origin` (sin `/branch`) resetea a
   `refs/remotes/origin/HEAD` = default branch del remote**.
   Casi nunca lo que se quiere; es facil leerlo como
   "resetear a origin/<current>". Agregar al S-04 como
   gotcha tipico.
5. **#19 estaba ya cubierto en el deploy real**. Wire test
   nos ahorro tocar PG config innecesariamente. La leccion:
   antes de "configurar X", probar el estado actual de X.

## §7. Roadmap actualizado

Heredado del 18-jun. Items abiertos: **0**.

PT-1..PT-4 estado al cierre:
- **PT-1** ✓ wire-verified (promote completado)
- **PT-2** ✓ wire-verified (hook anda y bloquea; bypass anda)
- **PT-3** ✓ wire-verified (audit workflow emite warning)
- **PT-4** ✓ wire-verified (backup + restore verify + timer
  activado; primer trigger automatico el 20-jun 04:11)

## §8. Continuidad — para el proximo agente

**Roadmap 100% cerrado**. PT-1..PT-4 todos verdes + auditoria
independiente cerro 2 bugs latentes (R-11, R-12). El template
queda en `v0.3.1-django`, suite 898/898 verde sin deselect,
`dev @ af6667e`, `main @ 67ae53a` (8 commits behind dev, para
promote opcional cuando vuelvas con `gh`).

### Tareas operacionales pendientes (no nuevos items)

1. **Verificar primer backup automatico** (madrugada del 20-jun
   ~04:11 local). `journalctl -u
   ameli-app-template-dev-backup.service --since today` +
   `ls -lh /var/backups/ameli-app-template-dev/`. Esperado una
   entrada nueva con fecha del 20.
2. **Promote `dev → main`** — 8 commits ahead. Cuando el
   operador este en una shell con `gh` autenticado:
   ```
   gh pr create --base main --head dev --title "promote dev -> main (sprint cierre)"
   gh pr merge --merge
   ```
   O usar el bypass del pre-push hook si seguimos con merge
   directo desde shell.
3. **Wire test PT-2 en Windows checkout** (cuando vuelvas a tu
   maquina): `bash scripts/install-pre-push-hook.sh` +
   probar bloqueo + bypass.

### Para el 2026-06-20 — sesion abierta

El operador pidio un analisis de mejoras post-sprint-de-seguridad
(buckets backend + frontend, sin desarrollo). El plan vive
ya en `CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md` como §2
objetivo, con un mini-roadmap priorizado. Si se aprueba,
empieza por el Bucket D (developer experience) — mejor ROI por
unidad de esfuerzo.

### Lecciones consolidadas del sprint 2026-06-15..06-19

- Wire test ANTES de declarar cualquier item OPS cerrado.
- "Configurar X en server" → primero probar el estado actual.
- Flake → causa real en producto; nunca `--deselect` sin
  diagnostico cerrado.
- Boot guards deben ser SIMETRICOS entre keys (MFA vs AUDIT vs
  AV) — la asimetria es el bug.
- Auditor externo (agente paralelo en read-only) encuentra lo
  que self-review da por sentado. **Patron**: despues de
  declarar un capitulo ASVS al bar L2, mandar un agente
  independiente con instrucciones "trust but verify".
- IFS-safe env loader es no-negociable en wire tests.
- `git reset --hard origin/<branch>` con `/branch` explicito;
  sin el branch, resetea al default remote (main), confundiendo.
- Slug derivation: dir basename primero, pyproject name despues.
  Mismo patron en `manage.py` y `_common.sh`.

### Fix CI flake — root cause distinto al "test-state isolation"

El test `test_forgot_password_throttle_after_too_many_requests`
hace tres POST a `/login/forgot/` con
`FORGOT_PASSWORD_IP_MAX=2`, `FORGOT_PASSWORD_IP_WINDOW=600`:

```python
for _ in range(2):
    response = client.post("/login/forgot/", ...)
    assert response.status_code == 200
response = client.post("/login/forgot/", ...)
assert response.status_code == 429
```

CI `#93` fallo en Python 3.12: el 3er request devolvio 200 en
lugar de 429. Local pasa 5/5 — no es leak de estado.

**Root cause**: `_read_throttle_counter_sliding` en
`services.py` calculaba:

```python
return cur_count + int(prev_count * prev_weight)
```

El `int()` trunca hacia 0. Cuando el test cruza la frontera de
un bucket de 600s entre el request 2 y el request 3:

- Request 1,2 caen en bucket A: count_A = 2, sliding = 2 (200 ✓).
- Bucket cruza.
- Request 3 cae en bucket B: count_B = 1. `elapsed ≈ 1ms`,
  `prev_weight ≈ 0.99999`. `int(2 * 0.99999) = int(1.99998) = 1`.
  sliding = 1 + 1 = 2. Test espera > 2 → falla con 200.

Probabilidad: `test_duration / window_seconds ≈ 3s / 600s = 0.5%`
por corrida. CI ~12 corridas/dia → flake cada ~17 dias. Acaba
de ocurrir.

**Fix**: cambiar `int()` por `math.ceil()`. Un rate limiter
NUNCA debe under-contar — el truncation era un bug de
seguridad latente, no solo un flake. Con `ceil(1.99998) = 2`,
sliding = 1 + 2 = 3 → 429 correcto. Costo: maximo 1 over-count
al edge (sesgo defensivo aceptable).

Tests: nuevo
`test_throttle_sliding_window_rounds_prev_contribution_up` en
`test_code_review_fixes_20260615.py` que mockea
`timezone.now` a 1ms post-boundary y verifica
`sliding == 3` (con `ceil`, vs `2` con `int()`). Pin contra
regresion futura.

### Leccion incorporada — flakes como bugs latentes

Un flake de 0.5% es **un bug de seguridad real** disfrazado de
"problema CI". Si el test que protege la propiedad de
rate-limiting puede pasar con un valor incorrecto el 0.5% del
tiempo, la propiedad NO esta enforced — el atacante real puede
explotar el mismo edge. **Regla**: no marcar un test como
"flake" sin entender el mecanismo de falla. Si el fix correcto
es en producto, hacerlo ahi.

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Heredado del 18-jun. Roadmap items: **0 abiertos**. Items con
operator-side validation pendiente:

- **PT-1** sync `dev`/`main` y promote (4 commits pre-fix +
  este).
- **PT-2** instalar `pre-push` hook en cada checkout.
- **PT-3** verificar branch protection layered.
- **PT-4** server-side: PG TCP localhost + backup timer +
  restore verify.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
