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

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Heredado del 2026-06-17 §7. Items que arranca el dia abiertos:

- **#14 V14.2.3** Lockfile con hashes (M, ~1h).
- Operacionales: #16, #18, #19, #20, #23.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
