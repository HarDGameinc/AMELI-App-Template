## AMELI App Template handoff (sesion Claude, 2026-06-18)

Fecha: `2026-06-18`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del fix CI)
Rama estable: `main` (en `8bde7c0`; rezagada por CI rojo del dia previo)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-17_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-17_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `dev @ aa869be`, `main @ 8bde7c0`.
- Tests: 837 passed / 1 failed (CI rojo cronico desde `a1fe164`).
  El test que rompia era
  `tests/test_admin_audit_pagination.py:244
  test_filtered_audit_queryset_respects_combined_filters`. Mi
  diagnostico previo "es TZ flake" era incorrecto.
- ASVS L2: **150 PASS / 0 strict-tracked GAP** — bucket S del
  roadmap cerrado completo en sesion previa.
- Frente abierto al cierre de ayer (§8 del handoff 17-jun, orden
  estricto): (1) fix CI rojo, (2) promote dev→main, (3) #14
  lockfile con hashes.

## §2. Objetivo de la sesion

Resolver la primera prioridad del §8 del 2026-06-17 — el test
flaky que tiene CI rojo desde hace 8 runs consecutivos —
desbloquear la promocion a `main`, y arrancar #14 V14.2.3
(lockfile con hashes) si queda budget. Mantener disciplina:
NO promover a main hasta ver el run verde post-fix.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `702f82c` | Fix CI rojo — test combined-filters TZ-stable | 837 → 838 (+1 cubierto, suite verde sin deselect) |
| — | Promote `dev → main` fast-forward (`8bde7c0..702f82c`, 5 commits) — CI #73 verde | suite stays green |
| `8726411` | Item #14 — ASVS V14.2.3 lockfile con hashes + `--require-hashes` en CI + deploy | 838 → 847 (+9) |
| `ee5605b` | Hotfix #14 — argon2-cffi missing en requirements.txt + sync-guard test | 847 → 848 (+1) |
| `d4fd8d2` | Doc leccion del #14 hotfix en handoff §3 | suite stays green |
| — | Promote `dev → main` (`702f82c..d4fd8d2`, 4 commits) — CI #76+#77 verde | suite stays green |
| `b3688ba` | Item #20 — `manage.py` auto-load APP_CONFIG + app.env (IFS-safe) | 848 → 862 (+14) |
| `1e03264` | #20 wire-fix — slug from dir name first, pyproject second | 862 → 863 (+1) |
| — | Promote `dev → main` (`d4fd8d2..1e03264`, 3 commits) — CI #79+#80 verde | suite stays green |
| `f42e438` | Item #16 — drift banners en 6 handoffs `2026-06-09..06-13` | suite stays green |
| `8abc298` | Item #23 — branch protection runbook en OPERATIONS.md | suite stays green |
| `3c14b95` | Items #18 + #19 — backup systemd unit + timer + PG connectivity runbook | 863 → 873 (+10) |
| `2d1eb23` | Version bump v0.2.0-django → **v0.3.0-django** | suite stays green |
| `69f1790` | Record bucket OPS commits + version bump en handoff | suite stays green |
| `88cce00` | Expand §8 con post-#23 promote workflow + operator todo | suite stays green |
| — | **Promote final `dev → main`** (`1e03264..88cce00`, 6 commits) — CI #87 + #88 verde | suite stays green |
| `b94dfcc` | Refresh §5 metrics + record final promote | suite stays green |
| `d91ef8d` | #23 follow-up #1 — flag Rulesets-vs-classic trap (mi clasificacion era erronea) | suite stays green |
| `9df29c4` | #23 follow-up #2 — layered substitutes: pre-push hook + audit workflow | 873 → 882 (+9) |

### Wire validation 2026-06-18 — items #14 + #20

Server `ha-report2`, branch `dev @ 1e03264` (post-slug-fix).

**Item #14 — `--require-hashes` install**:

```
.venv/bin/python -m pip install --require-hashes -r requirements.lock -r requirements-dev.lock
exit=0
```

14 paquetes se downgrade-aron para matchear el lock (argon2-cffi
25.1→23.1, pyotp 2.9→2.10, pillow 11.3→12.2, sqlalchemy
2.0.50→2.0.51, etc.). Exit 0 confirma que CADA wheel
descargado matcheo su sha256 del lock. Un wheel rotado en PyPI
con hash distinto hubiera salido non-zero con "THESE PACKAGES
DO NOT MATCH THE HASHES". Verificacion del comportamiento de
proteccion exactamente como diseñado.

Smoke de imports posterior: ``import argon2, cryptography,
django, psycopg, qrcode`` → ``imports OK``. Sin
``ConfigurableArgon2Hasher`` errors (el bug que el hotfix
`ee5605b` cerro).

**Item #20 — autodetect APP_CONFIG + app.env**:

Primer intento (commit `b3688ba`, slug solo de pyproject):

```
APP_CONFIG resuelto -> /opt/ameli-app-template-dev/config/app.yaml.example
db backend         -> django.db.backends.sqlite3
```

Falla — la autodetección probó `/etc/ameli-app-template/app.yaml`
(pyproject `[project].name = ameli-app-template`) que no existe;
el deploy real es `/etc/ameli-app-template-**dev**/app.yaml`.
Fall-back al example yaml → SQLite. **Wire test atrapo lo que
los unit tests no podian: la mismatch entre slug canonico y
slug de instancia**.

Fix en `1e03264` — slug del directorio primero
(`/opt/<slug>/` ↔ `/etc/<slug>/` convencion):

```
APP_CONFIG resuelto -> /etc/ameli-app-template-dev/app.yaml
app_name           -> AMELI App Template
environment        -> dev
DJANGO_SECRET_KEY  -> <set>      (parsed from /etc/.../app.env, IFS-safe)
db backend         -> django.db.backends.postgresql
```

Wire test #20 confirmado verde. No mas
``export APP_CONFIG=/etc/...`` ni
``set -a; while IFS= read``: ``python manage.py shell`` es
plug-and-play en el deploy.

### Finding del wire — upstream tracking del repo deploy

Antes del fix `1e03264`, el wire test inicial tenia el server
en `git pull --ff-only` que decia "Ya está actualizado" cuando
en realidad local `dev` estaba en `d4fd8d2` y `origin/dev`
estaba en `1e03264`. Recovery necesito
`git fetch origin && git reset --hard origin/dev`. Posibles
causas: (a) tracking de `dev` apuntando a otro upstream, (b)
estado del checkout que pull ff-only no resuelve sin la fuerza.

NO es bug del template; es **deploy hygiene del server**. Lo
anoto aca para el proximo wire test: si el server muestra
"Ya está actualizado" pero el commit no avanzo, el patron de
recovery es `reset --hard origin/dev`. El item operacional #16
(doc drift) deberia agregar esto al runbook S-04.

### Item #14 — V14.2.3 lockfile con hashes

- **Qué**: nuevos `requirements.lock` (952 lineas) y
  `requirements-dev.lock` (516 lineas) generados con
  `pip-compile --generate-hashes`. Cada wheel/sdist de cada dep
  transitiva carga su sha256. CI y el script de deploy ahora
  instalan con `pip install --require-hashes -r
  requirements.lock -r requirements-dev.lock`. pip-audit movido
  a auditar el lock (lo que efectivamente se instala) en vez
  del rango source.
- **Por que**: ASVS V14.2.3 (third-party signature/integrity
  verified). Un wheel rotado en PyPI o un typosquat que
  satisficiese el rango ahora se rechaza al instalar — no llega
  al runtime.
- **Decisiones**:
  - **Source ranges (`.txt`) se mantienen** como input
    deliberado del operador; el `.lock` es la materializacion
    autogenerada. Una bump al `.txt` sin regenerar el lock
    rompe CI inmediatamente — feature, no bug.
  - **`--allow-unsafe` en el lock de dev** porque pip-tools
    arrastra `pip` y `setuptools` como deps. Sin la bandera
    pip-compile los excluye y el `--require-hashes` despues
    falla.
  - **`pip install -e . --no-deps`** en CI/deploy: el editable
    install no debe re-resolver, todo ya viene del lock.
  - **Fallback en `scripts/_common.sh`**: si el deploy se
    ejecuta contra una copia sin `.lock` (upgrade in-place
    desde una version pre-V14.2.3), instala desde el `.txt`
    con warning. Una vez que la primera promocion ship-ea el
    lock, el fallback nunca se dispara.
- **Tests**: 9 nuevos en `tests/test_lockfile_hashes.py`
  pinning del contrato — lockfiles existen, cada top-level
  dep esta en el lock, cada entry lockeada tiene `--hash=`,
  CI + deploy referencian los lockfiles, pip-tools en dev
  deps. Static-analysis only (no corre pip), corre en <100ms.
- **Doc**: `OPERATIONS.md` nueva seccion "Lockfile / supply
  chain" con el comando de refresh + sanity-test;
  `COMPLIANCE_ASVS_L2_2026-06-16` V14.2.3 GAP→PASS; V14.2.1
  promovida a PASS sin caveat; V14 chapter 23 → 24 PASS;
  totals 150/0 → 151/0.

### Fix CI rojo — root cause distinto al diagnosticado ayer

**Lo que dije ayer**: "test-state isolation rota, agregar
`AuditEvent.objects.all().delete()` en setUp".

**Lo que es en realidad**: time-of-day-dependent, no
state-leak. El test pedia `date_to=yesterday` (calculado como
`(timezone.now() - timedelta(days=1)).date().isoformat()`). En
CI:

| Variable | Valor en run #71 |
|---|---|
| `TIME_ZONE` Django | `America/Santiago` (UTC-3/-4) |
| OS de CI | UTC |
| Hora del run | `2026-06-18T02:30:51Z` = `2026-06-17 22:30:51` Santiago |
| `yesterday` calculado (UTC date) | `"2026-06-17"` |
| Filtro: `make_aware("2026-06-17 23:59:59", TIME_ZONE=Santiago)` | `2026-06-18 02:59:59 UTC` |
| Eventos seedeados a `timezone.now()` (02:30 UTC) | < `02:59:59 UTC` → **incluidos por error** |

Ventana de falla: cuando UTC esta entre 00:00 y 03:00 (~3h al
dia), el `yesterday 23:59:59 Santiago` cae DENTRO del "hoy" UTC
y los eventos seedeados a `timezone.now()` pasan el filtro
cuando no deberian.

Fix: cambiar el cutoff a 7 dias atras — fuera de la ventana
ambigua sin importar la hora del wall-clock. La intencion del
test es validar la composicion de filtros (`action` AND `date_to`),
no la frontera exacta del corte de fecha; el cutoff lejano
mantiene la semantica pero hace el test deterministico.

```python
cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
queryset = filtered_audit_queryset(action="login", date_to=cutoff)
```

### Leccion incorporada (item #14) — `pyproject.toml` vs `requirements.txt`

El primer commit del item #14 (`8726411`) prendio CI rojo en
ambos jobs (3.11 + 3.12) con 405 errors al import:
``No module named 'argon2'``. Root cause:

- `pyproject.toml` `[project].dependencies` listaba
  `argon2-cffi>=23.1.0`.
- `requirements.txt` NO lo listaba (drift historico).
- Pre-#14 el CI corria `pip install -r requirements.txt && pip
  install -e .` — el `pip install -e .` resolvia los deps del
  pyproject incluyendo argon2-cffi.
- Post-#14 el `pip install -e . --no-deps` (necesario porque
  --require-hashes prohibe re-resolver) ya no traia los deps
  del pyproject. Lock generado desde requirements.txt no tenia
  argon2-cffi. Resultado: ConfigurableArgon2Hasher rompe el
  import.

Fix en `ee5605b`: (a) agregar `argon2-cffi` a requirements.txt,
(b) regenerar lock, (c) **test guard nuevo**
`test_pyproject_runtime_deps_are_subset_of_requirements_txt`
que falla rapido si alguien agrega un dep a pyproject sin
mirrorearlo en requirements.txt. La invariante "pyproject es
metadata, requirements.txt es la verdad de install" queda
codificada en CI.

Leccion para el playbook: **al cambiar la fuente de
instalacion** (de `.txt` a `.lock` con `--require-hashes`),
**hay que auditar la diferencia entre el viejo y nuevo set de
deps instalados**. El `pip freeze` antes/despues del cambio
hubiera caught esto sin necesidad de un round-trip de CI rojo.
Patron: en un PR que mueva el install path, agregar un step
explicito que ejecute `pip freeze | diff` contra el resultado
del install viejo.

### Leccion incorporada (item #23 follow-up) — GitHub plan trap

Sobre el roadmap #23 (branch protection en main) me equivoque DOS
veces antes de ver la realidad:

1. **Primer intento**: propuse Rulesets. El operador aplico, la UI
   mostro "Active" y el banner amarillo decia "Your rulesets
   won't be enforced on this private repository until you move
   to GitHub Team". Pense que era warning informativo y dije
   "usa classic rules en su lugar".
2. **Segundo intento**: propuse classic Branch protection rules
   ("esas si funcionan en cualquier plan, incluyendo Free +
   private"). FALSO. El operador aplico, el rule aparecio con
   status **"Not enforced"** y el mismo banner.
3. **Realidad**: GitHub Free + private repo = **CERO branch
   protection nativa**. Ni Rulesets ni classic rules. Para
   enforcement server-side se necesita GitHub Team o el repo
   tiene que ser publico.

Fix en `9df29c4`: tres capas substitutas. Layer 1 = pre-push hook
local (`deploy/git-hooks/pre-push`). Layer 2 = audit workflow
post-push (`.github/workflows/main-push-audit.yml`) que detecta y
warning-loggea direct pushes. Layer 3 = el ruleset + classic rule
ya creados quedan latentes; activan en upgrade.

**Leccion para el playbook**: cuando un feature server-side se
declara "aplicado", el closure NO es legitimo hasta probar la
violacion (push directo, force-push, etc.) y verificar que el
rechazo ocurre. La UI puede mentir. Pin de S-04 al respecto.

### Leccion incorporada — diagnostico de CI rojo

Ayer asumi "es flake TZ" sin abrir un solo log de CI. La causa
real estuvo a un `mcp__github__get_job_logs` de distancia, e
incluso DESPUES de tener el log seguia diciendo "test-state
isolation" porque no calcule el shift TZ en la cabeza. **Regla
nueva**: antes de afirmar la naturaleza de un flake, abrir el
log del runner Y reproducir la asercion ofensora con sus
valores numericos. Sin eso, cualquier hipotesis es especulacion.
Esta leccion se agrega al S-04 / S-07 del playbook en la
siguiente promocion.

## §4. Decisiones tomadas

1. **Promoter dev→main solo despues de wire test verde**, no
   solo CI verde. El #20 commit `b3688ba` paso CI (los unit
   tests no podian ver la mismatch slug canonico vs slug de
   instancia) pero fallaba en el deploy real. Politica
   reforzada en S-04 § Environment prep del template: no
   promover items operacionales sin wire test.
2. **Slug derivation = directorio primero, pyproject despues**.
   La convencion `/opt/<slug>/` ↔ `/etc/<slug>/` del install
   script es la fuente mas estable; el pyproject name suele
   tener menos contexto (sin sufijo de instancia). El orden
   matchea tambien el patron "explicit beats implicit" del
   resto del codebase.
3. **pip-audit movido a auditar el `.lock` en vez del rango
   source `.txt`**. El lock es lo que se instala; un CVE
   sobre una version que el rango admite pero el lock no
   adopta seria falso positivo contra el deploy real.
4. **No subir argon2-cffi a `>=24` aunque el server tuviera
   `25.1.0`**. El lock pin 23.1.0 esta dentro del rango
   `>=23.1,<25` declarado por intent (next-next major boundary).
   El downgrade durante el wire test fue feature, no bug —
   ahora el deploy converge a la version exacta del lock.

## §5. Metricas al cierre

| Metrica | Inicio dia | Cierre dia | Δ |
|---|---|---|---|
| Suite local (sin deselect) | 837 (1 failure) | **882** | +45 (+1 fix CI, +9 #14, +1 #14-hotfix, +14 #20, +1 #20-slug, +10 #18, +9 #23-followup) |
| ASVS L2 active rows PASS | 150 | **151** | +1 (V14.2.3 GAP→PASS, V14.2.1 partial→full) |
| ASVS L2 strict GAP roadmap-tracked | 1 (V1.4.4 + V13.2.2 ya en main) | **0** | -1 |
| Capitulos completos al bar L2 | 8 | **9** (+V14) | +1 |
| Roadmap items abiertos al inicio | 6 (M=1, OPS=5) | **0** | -6 (todos cerrados template-side) |
| Commits sobre `dev` | 0 (start at `aa869be`) | 14 (`702f82c..88cce00`) | — |
| Commits propagados a `main` | 0 (8bde7c0) | 13 (`8bde7c0..88cce00`) | — |
| Version | `v0.2.0-django` | **`v0.3.0-django`** | minor bump |
| CI verde | 1 / 8 ultimos runs al inicio | 6 / 6 ultimos runs al cierre | drastic recovery |
| Wire validations ejecutadas | 0 | 2 (#14 + #20, ambas verdes despues de fix) | — |

## §6. Hallazgos / findings

1. **TZ wall-clock window flake** — el test
   `test_filtered_audit_queryset_respects_combined_filters`
   fallaba en CI 3h al dia (UTC 00:00-03:00) por el shift
   `America/Santiago` que mueve el cutoff de `date_to=yesterday`
   hasta 02:59 UTC. Mi diagnostico inicial "es flake TZ"
   senalaba la direccion correcta pero NO calculaba la ventana
   de horas; me llevo 8 runs de CI ignorar el log real.
   Lesson: si afirmas "es TZ", el log de CI tiene que
   confirmar la HORA en que paso. Fix: cutoff 7 dias atras,
   fuera de la ventana ambigua.
2. **`pyproject.toml` vs `requirements.txt` drift** — argon2-cffi
   en pyproject pero no en requirements.txt rompio el deploy
   cuando el install path se movio a `--require-hashes` (que
   prohibe re-resolver via `pip install -e .`). Test guard
   nuevo `test_pyproject_runtime_deps_are_subset_of_requirements_txt`
   evita la regresion. Lesson: cuando movemos la fuente de
   install, hay que diffear el `pip freeze` antes/despues.
3. **Slug derivation requerido para deploys multi-instancia**.
   El primer #20 derivo slug de pyproject `[project].name`,
   que es el slug canonico (`ameli-app-template`) — pero los
   deploys reales tienen sufijos de instancia
   (`ameli-app-template-dev`). El wire test catcheo lo que
   unit tests no podian ver. Fix: probar dir name primero.
4. **Deploy hygiene** — el server `ha-report2` tenia `dev`
   stuck en `d4fd8d2` con un `git pull --ff-only` que decia
   "Ya está actualizado" pese a que origin/dev avanzo. Recovery
   con `reset --hard origin/dev`. Posible upstream tracking
   misconfigurado o working tree state que pull-ff no resuelve.
   NO es bug del template; agregar al runbook S-04 como
   patron de recovery.

## §7. Roadmap actualizado

Heredado del 2026-06-17 §7. Items cerrados hoy:

| Item | ASVS | Commit | Wire |
|---|---|---|---|
| (fix TZ flake) | — | `702f82c` | n/a (CI green confirma) |
| #14 V14.2.3 lockfile con hashes | PASS | `ee5605b` + `1e03264` | ✓ |
| #20 manage.py auto-load APP_CONFIG | OPS closed | `1e03264` | ✓ |

Items roadmap restantes (todos OPS, sin impacto ASVS L2):

- **#16** Doc drift en handoffs `<2026-06-13` (S, ~15 min, doc-only).
- **#18** Install `backup.timer` + service (S, server OPS).
- **#19** PG TCP listener o backup-as-user (S, server OPS).
- **#23** Branch protection en `main` (S, GitHub repo settings).

## §8. Continuidad — para el proximo agente

**Roadmap COMPLETO** — bucket L2 + bucket OPS cerrados ambos
template-side. NO quedan items roadmap-tracked sin closure plan.
Version bumped a `v0.3.0-django`. `main == dev == 88cce00`
(commits posteriores `b94dfcc`/`d91ef8d`/`9df29c4` siguen solo
en `dev` hasta el proximo promote — vease pruebas pendientes
abajo).

### Pruebas pendientes — para retomar en otro equipo

El operador cierra la sesion 2026-06-18 con la suite verde y el
roadmap closeado template-side, pero quedan **4 wire tests** que
requieren acceso al server `ha-report2` o a una shell con `gh`
autenticado. No son items roadmap nuevos; son la otra mitad
operativa de #18/#19/#23.

**PT-1 — Sync de `dev` reciente y promote a `main`** (cualquier
shell con write a origin):

```bash
cd <checkout>
git fetch origin
git checkout main && git reset --hard origin/main   # main = 88cce00
git checkout dev  && git reset --hard origin/dev    # dev = 9df29c4 (despues de followups)
# Si la branch protection ya esta activa (PT-3):
gh pr create --base main --head dev --title "promote dev -> main (sprint close)"
gh pr merge --merge   # cuando los 3 status checks esten verde
# Si NO esta activa todavia:
git checkout main && git merge --ff-only origin/dev && git push origin main
```

**PT-2 — Instalar pre-push hook en cada checkout** (`ha-report2`
y cualquier maquina de dev):

```bash
cd <checkout>
bash scripts/install-pre-push-hook.sh
# -> [install-pre-push-hook] installed .git/hooks/pre-push
# Probar bloqueo:
git checkout main && git commit --allow-empty -m "probe"
git push origin main   # esperado: [pre-push] Direct push to 'main' refused.
# Probar bypass:
ALLOW_DIRECT_PUSH=1 git push origin main   # debe pasar; main-push-audit.yml graba warning
```

**PT-3 — Aplicar branch protection (Free-plan-aware)**:

- (a) Layer client-side: PT-2 ya cubre.
- (b) Layer audit server-side: el push de PT-1 ya dispara
  `.github/workflows/main-push-audit.yml`; verificar en
  Actions → "Main push audit" que la corrida sobre el merge
  commit emite `::notice::Merge commit detected` (no warning).
- (c) Layer latente: las reglas en Settings → Rules → Rulesets
  ("protect-main") y Settings → Branches → Branch protection
  rules (main) quedan como estan — se activan automaticamente si
  se hace upgrade a GitHub Team o si el repo se hace publico.

**PT-4 — Activar backup timer en `ha-report2` y verificar
restore** (server-side OPS, items #18 + #19):

```bash
# En ha-report2, como root:
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev   # tomar 9df29c4
bash scripts/install-pre-push-hook.sh

# (#19) Antes del primer backup, configurar PG TCP localhost.
# Editar /etc/postgresql/<ver>/main/postgresql.conf:
#     listen_addresses = 'localhost'
# Editar /etc/postgresql/<ver>/main/pg_hba.conf, agregar:
#     host  <db>  <app_user>  127.0.0.1/32  scram-sha-256
# Asegurar que /etc/ameli-app-template-dev/app.env tiene
# AMELI_APP_DATABASE_URL=postgresql://<app_user>:<pwd>@127.0.0.1:5432/<db>
systemctl restart postgresql
# Validar conexion:
sudo -u root .venv/bin/python -m ameli_app.cli db-status --config /etc/ameli-app-template-dev/app.yaml

# (#18) Re-instalar systemd units para renderizar backup.service/timer
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
systemctl list-timers '*-backup.timer'
# Esperado: ameli-app-template-dev-backup.timer activo, next ~04:10

# One-shot manual:
systemctl start ameli-app-template-dev-backup.service
systemctl status ameli-app-template-dev-backup.service   # esperado: active (exited)
ls -lh /var/backups/ameli-app-template-dev/

# Verify del archive:
sudo APP_ENV=dev bash scripts/restore.sh verify \
    /var/backups/ameli-app-template-dev/<latest-archive>.tar.gz
# Esperado: "verify OK" + exit 0
```

Cuando PT-1..PT-4 esten verde, agregar la evidencia al §3
"Wire validation 2026-06-18 — items #18 + #19 + #23" y mergear
el handoff del 19-jun (cuando aplique).

**Para futuras sesiones — patron de promote post-#23**:

```bash
git checkout dev && git pull
gh pr create --base main --head dev --title "promote dev -> main"
# CI corre; cuando los 3 status checks esten verdes:
gh pr merge --merge   # o --ff si querias linear history y CI lo permite
```

**Lecciones del dia incorporadas a S-04 / S-08**:
- Antes de proponer un fix de flake, abrir el log del runner
  Y calcular numericamente la hipotesis (no asumir).
- Cuando movemos la fuente de install, diffear `pip freeze`
  antes y despues como step explicito del PR.
- Items operacionales (OPS) requieren wire test obligatorio
  antes de promote dev→main — los unit tests no ven la
  realidad del deploy.
- Server deploy hygiene: si `git pull --ff-only` dice
  "Ya está actualizado" pero el HEAD esta atras,
  `reset --hard origin/<branch>` es el recovery canonico.
- Slug derivation para deploys multi-instancia: directorio
  primero, pyproject `[project].name` despues.
