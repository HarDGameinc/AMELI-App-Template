## AMELI App Template handoff (sesion Claude, 2026-06-22)

Fecha: `2026-06-22`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `c643af8` al abrir)
Rama estable: `main` (`1355060`, sin tocar — 8 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-21_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-21_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ c643af8` (sync local == origin).
  - `main @ 1355060` (sync local == origin), 8 commits atras de `dev`.
  - Sin promote pendiente: convencion ratificada el 21-jun es
    server pullea `dev`, `main` avanza solo por instruccion
    explicita "milestone" del operador.
- Tests: **948 passed** sin deselect.
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 47 archivos src.
- Version: `v0.4.0-django` (deployed en `ha-report2 @ f76af65`,
  ultimo commit con cambio de codigo; los siguientes son doc-only).
- ASVS L2: 151 PASS / 0 strict GAP.
- Mini-roadmap mejoras: 7/12 items shipped (Fase 1+2 closed,
  Fase 3 partial: #6 mypy done, #7 OpenTelemetry pendiente;
  Fases 4-6 abiertas).
- Frente abierto del 21-jun §8:
  - Promote `dev → main` cuando operador diga "milestone".
  - Continuar mini-roadmap (5/12 items) si hay direccion.
  - Patrones operacionales ratificados (server pulls dev only,
    auto-prompts ≠ instruccion, etc.) — incorporados al playbook.

### Commits pendientes en `dev` desde el ultimo match con `main`

| Commit | Tema |
|---|---|
| `d70bff6` | Convencion de branches documentada en §2 del 21-jun |
| `32dc83f` | Cierre wire test 21-jun + journal review |
| `af6b185` | Hero dashboard + admin panel honran `has_avatar` |
| `9c800a9` | Drop ring + gradient backdrop del hero cuando hay imagen |
| `6ac13fc` | Sibling: drop ring del chip top-right |
| `f76af65` | Hero avatar 72→96px + radius 24→28 |
| `d279c24` | §3 del 21-jun amplificado con polish del 22-jun |
| `c643af8` | Cierre §4-§8 del handoff 21-jun |

## §2. Objetivo de la sesion

Continuar el mini-roadmap pendiente del 21-jun §8 — items #8 (SRI
propios + Trusted Types CSP) y #9 (circuit breakers AV/HIBP/SMTP).
Cierre del handoff con wire test en `ha-report2` confirmado.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `08e2583` | Open 2026-06-22 handoff | doc only |
| `2db09cb` | Enforce Trusted Types CSP on own pages (mini-roadmap #8b) | 948 → 952 (+4) |
| `afa083d` | SRI on own static bundles (mini-roadmap #8a) | 952 → 957 (+5) |
| `39d3243` | Circuit breakers AV/HIBP/SMTP (mini-roadmap #9) | 957 → 970 (+13) |
| `1a2ea7f` | Cierre §2-§8 del handoff (primer pase) | doc only |
| `3885252` | Documentar follow-up clamav Unix-socket (Debian gotcha) | doc only |
| `a51d2b8` | Scheme `unix://` en `av.py` (cierra ASVS V12.4.1 strict) | 970 → 976 (+6) |
| `9c16b2d` | Wire test unix:// AV verde + close follow-up + doc gotcha primer install | doc only |
| `8de62d1` | OpenTelemetry tracing opt-in (mini-roadmap #7, cierra Fase 3) | 976 → 987 (+11) |
| `<this>` | Re-cierre del handoff con OTel + wire test parte A | doc only |

### Mini-roadmap #8b — Trusted Types CSP (2db09cb)

Surface relevada: 11 sitios de DOM HTML-sink en 2 archivos.
- `app.js`: 1 `panel.innerHTML = html` (partial swap, HTML del backend)
  + 1 `button.innerHTML = '<span>...'` (literal estatico del back-to-top).
- `profile.html` MFA tab: 1 `qrSlot.innerHTML = data.qr_svg` (SVG del
  backend), 2 `recoveryList.innerHTML = ""` (clears), 5
  `w.document.write(...)` en popup de impresion de recovery codes.

Refactor:
- **Bootstrap** en `base.html` `<head>` crea `window.ameliTrusted`
  via `trustedTypes.createPolicy("ameli-template", { createHTML:
  s => s })`. Firefox/Safari sin TT caen a identity wrapper; misma
  ruta de codigo cross-browser.
- **CSP middleware** (build_csp) ahora emite
  `require-trusted-types-for 'script'; trusted-types ameli-template`
  en la project-wide. `_django_admin_csp` y `_docs_csp` quedan SIN
  TT — el admin shippea inline scripts framework-owned que hacen
  innerHTML uncontrolled, y Swagger UI / ReDoc bundles del CDN
  manipulan HTML por su cuenta.
- **HTML-writers** wrappeados por policy: `panel.innerHTML =
  ameliTrusted.createHTML(html)`, `qrSlot.innerHTML =
  ameliTrusted.createHTML(data.qr_svg)`.
- **Refactor a DOM APIs** donde el wrap era innecesario:
  back-to-top reescrito con `createElement` chain;
  recovery-list clears con `replaceChildren()`; popup de
  impresion rebuild completo con DOM APIs (5 `document.write`
  eliminados).

Tests pinned: project-wide CSP trae las 2 directivas TT,
`/django-admin/` CSP las omite, `/docs` CSP las omite, base.html
embebe el bootstrap del policy.

### Mini-roadmap #8a — SRI sobre propios (afa083d)

Hueco residual: third-party CDN bundles (swagger-ui, redoc) ya
tenian `integrity=` gated por `CDN_SRI_HASHES` desde el 19-jun,
pero `css/app.css` y `js/app.js` propios shippeaban sin integrity.
Un MITM que swappeara una response 200 del `/static/` quedaba
sin detectar.

Implementacion:
- **Tag nuevo** `{% sri_for 'path' %}` en
  `src/ameli_web/accounts/templatetags/sri.py`. Hash sha384 +
  cache por `(path, mtime)` a nivel proceso. Dev edits invalidan
  automaticamente porque el mtime cambia; prod cachea after
  collectstatic y reusa forever.
- **Wire** en `base.html`: `<link rel="stylesheet" ...>` y
  `<script src=...>` ambos llevan `integrity="sha384-..."` ahora.
- **Missing-file graceful**: tag retorna `""` si el archivo no
  esta on-disk (typo, no collectstatic todavia). La pagina sigue
  shippeando, solo pierde el hint de integrity — un error de
  asset name no debe tirar el render.

Tests pinned: digest del tag matchea sha384 base64 del file bytes
(catches algo/encoding drift), missing-file returns "" (graceful
degrade), cache hits on unchanged mtime / invalidates on rewrite,
end-to-end `/` carga con ambos integrity correctos.

### Mini-roadmap #9 — Circuit breakers (39d3243)

Las 3 integraciones externas (AV clamd, HIBP, SMTP queue) ya tenian
manejo de errores existente. El gap: cada llamada paga el timeout
completo (5 s AV, 3 s HIBP, ~30 s SMTP) antes de caer al fail-open.
Con 50 uploads concurrentes contra un clamd wedged, ~250 s
acumulados de wait. Breaker fast-fails durante el outage.

Implementacion:
- **Modulo nuevo** `accounts/circuit_breaker.py` con `CircuitBreaker`
  thread-safe. State machine CLOSED → OPEN tras N fallos
  consecutivos → HALF_OPEN tras cooldown → CLOSED en probe success.
  Failed probe reabre con cooldown nuevo. State process-local (no
  shared cache) — cada worker descubre el outage independientemente,
  worst case escala lineal con worker count.
- **AV wire** `accounts/av.py`: `scan_bytes` consulta `breaker.allow()`
  antes de cualquier transport. Open → returns `("check_failed",
  "breaker_open")` en <1 ms en vez de esperar 5 s. La existing
  fail-open audit branch en la view de upload lo cubre sin cambios.
  `ok` / `infected` cuentan como interaccion saludable;
  transport-error / bad-response bumpean el counter.
- **HIBP wire** `accounts/validators.py`: mismo pattern. Open → log
  `"unavailable; allowing password: breaker_open"` y allow sin
  pegarle a `api.pwnedpasswords.com`. URLError/TimeoutError/OSError
  cuentan failure, k-anon range fetch cuenta success.
- **SMTP wire** `accounts/services.py:process_email_queue`: shape
  distinto porque es batch worker. Si breaker abierto al tick start
  → skip batch ENTERO sin tocar attempts (burnear max_attempts en
  outage conocido marcaria emails legitimos como failed
  permanentemente). Mid-batch trip → break del loop. Nuevo
  `skipped_breaker` field en summary + `email.queue_tick_skipped`
  log line.

Defaults: AV 5 / 30 s, HIBP 5 / 60 s, SMTP 5 / 60 s. Tunables via
settings (AV_CIRCUIT_BREAKER_THRESHOLD, etc.); no env vars plumbed
todavia — si un deploy real necesita runtime tuning, las
ploteamos ahi.

Tests pinned: state machine (open at threshold, half-open after
cooldown, close on probe success, re-open on probe failure,
counter resets on interleaved success), AV short-circuit + reset
en ok/infected, HIBP short-circuit, SMTP batch skip con attempts
NO bumpeados.

### Mini-roadmap #7 — OpenTelemetry tracing (8de62d1)

Cierra Fase 3 entera (que tenia abierto SOLO #7 desde el 20-jun;
#6 mypy se cerro ese mismo dia). Operador pidio explicacion previa
de "que hace OTel en el desarrollo o app" antes de implementar —
respondida con escenarios concretos del template (waterfall de
avatar upload, debug del 500 del 21-jun, login + MFA chain) que
ayudaron a tomar la decision "integremoslo".

Tracing opt-in: el SDK se carga en `asgi.py` en cada boot pero NO
registra TracerProvider a menos que el operador setee
`AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT` apuntando a un collector.
Sin endpoint configurado, `get_tracer()` devuelve un `ProxyTracer`
de la API de OTel (NoOp por default), los spans del codigo
degradan a no-ops con costo per-request cercano a cero.

Modulo nuevo `src/ameli_web/telemetry.py` (~190 LOC):
- `setup_otel()` — bootstrap idempotente con lock, lee endpoint +
  service_name + sample_ratio del env. Activa TracerProvider +
  BatchSpanProcessor + OTLP/gRPC exporter cuando hay endpoint.
- `get_tracer(name)` — safe wrapper que funciona pre/post setup,
  con o sin el package `opentelemetry` instalado (fallback
  `_NoopTracer` para envs minimos).
- `is_enabled()` — refleja estado REAL del SDK (no solo el env);
  endpoint sin exporter package reporta False.

Auto-instrumentations activadas en setup: **Django** (middleware
+ views + DB), **psycopg** (queries), **urllib** (cubre HIBP
outbound). Cada una en su try/except — un fallo en una no bloquea
las otras ni el boot.

Spans manuales agregados en los 3 puntos diagnostico-heavy:
- `av.scan_bytes` — atributos `av.endpoint_scheme`, `av.bytes`,
  `av.verdict`, `av.signature` (cuando infected), `av.reason`
  (cuando check_failed / breaker_open). Refactor extract de
  `_scan_with_breaker` para que el outer `scan_bytes` quede limpio
  con span wrapper + short-circuit.
- `hibp.range_query` en `HIBPPasswordValidator.validate` —
  atributos `hibp.prefix`, `hibp.outcome` (`ok` / `unreachable` /
  `breaker_open`), `span.record_exception` cuando network falla.
- `smtp.send` en `process_email_queue` (per row) — atributos
  `smtp.queue_id`, `smtp.attempts`, `smtp.audit_action`.

Boot guard en `settings.py`: endpoint debe empezar con `http://`
o `https://`. Bare `host:port` se comportaria distinto entre
versiones del SDK — refuse loud at boot.

Deps nuevas (6 declared + transitives): `opentelemetry-api`,
`-sdk`, `-exporter-otlp-proto-grpc`, `-instrumentation-django`,
`-instrumentation-psycopg`, `-instrumentation-urllib`. Transitives:
`grpcio` (~7 MB compiled), `protobuf`, `googleapis-common-protos`,
`wrapt`, `opentelemetry-semantic-conventions`, etc. — 17 packages
nuevos en total. Lockfile crece +254 lineas con hash-pinned
entries.

Docs: nueva seccion en `docs/OPERATIONS.md` con dev quickstart
(Jaeger all-in-one via docker) + minimum otel-collector pipeline
para prod.

Tests nuevos (`tests/test_telemetry.py`, +9):
- bootstrap NoOp cuando endpoint vacio
- idempotencia de setup
- `get_tracer` funciona pre-setup
- fallback NoOp cuando opentelemetry no esta instalado
- spans de AV/HIBP capturados via `InMemorySpanExporter`
- atributos correctos (scheme, verdict, signature, outcome, prefix)
- breaker_open registrado en spans

+2 tests en `test_settings_boot_guards.py` para el scheme check.

### Wire test 2026-06-22 — OTel parte A en `ha-report2`

Solo se ejecuto la parte "A" (deploy + verificar dormant correcto)
porque el servidor no tiene docker → la parte "B" (activar
endpoint apuntado a Jaeger) no es posible sin instalar docker o
el otel-collector standalone. La parte A confirma:

- `update.sh`: 23 OK / 0 WARN / 0 FAIL. 17 paquetes nuevos
  descargados + instalados via `--require-hashes`. `grpcio-1.81.1`
  (6.8 MB compiled) fue el mas pesado.
- `/health` reporta `v0.4.0-django`.
- `manage.py shell` confirma:
  - `is_enabled (no endpoint): False`
  - `tracer type: ProxyTracer` (OTel API default, NoOp transparent)
  - Span context manager corre sin error.

**Hallazgo cosmetico** (no shippeado, documentado en §6 #6): el
log line `otel.disabled reason=no_endpoint` no aparece en
`journalctl` porque `setup_otel()` corre en `asgi.py` **antes** de
que Django configure `LOGGING` desde `settings.LOGGING`. El
`logger.info()` se va al root logger que filtra INFO por default
(solo deja pasar WARNING+). Estado funcional verificado via
`manage.py shell`; visibility-only gap.

### Wire test 2026-06-22 — bundle #8 + #9 en `ha-report2`

`scripts/update.sh` (segun `docs/FIRST_INSTALL_DJANGO.md` §"Primera
actualizacion") fue el path canonico — me equivoque entregando
`install.sh` el primer turno, el operador me corrigio a revisar la
doc primero.

**Bundle #8 — full smoke verde**:
- update.sh: 23 OK / 0 WARN / 0 FAIL, daemons restart automatico
  (fix d4ade5e).
- `/health` reporta v0.4.0-django.
- SRI: HTML trae `integrity="sha384-..."` en `/static/css/app.css` y
  `/static/js/app.js`, hashes coinciden 1:1 con
  `openssl dgst -sha384 -binary` sobre los archivos en disco.
- CSP project-wide trae `require-trusted-types-for 'script';
  trusted-types ameli-template`.
- `/django-admin/login/` CSP omite TT (confirmado).
- `/docs` GET-real (no HEAD): `_docs_csp` whitelistea
  `cdn.jsdelivr.net` en `script-src` + omite TT (operator
  confirmo con `curl -s -D -`). HEAD via `curl -I` traía la
  project-wide CSP — falso positivo descartado.
- Browser smoke (Chrome + Firefox):
  - Login flow normal sin TT violations en Console.
  - `/profile/` MFA tab carga + recovery codes section.
  - Pagination AJAX swap (3 navegaciones consecutivas a
    `?sessions_page=N&partial=sessions`) — todas 200, swap
    in-place sin recargar → ejerce
    `panel.innerHTML = ameliTrusted.createHTML(html)`.
  - Back-to-top button visible en scroll → ejerce el refactor
    de `createElement`.
  - Swagger UI renderiza los 3 endpoints, ReDoc tambien.

**Bundle #9 — wire shell smoke**:
clamav-daemon NO esta instalado en `ha-report2` (`AV_ENDPOINT`
vacio → `scan_bytes` short-circuita antes del breaker), HIBP esta
funcionando ok, y no hubo trafico SMTP durante el wire window. Asi
que el journalctl filtrado por "circuit_breaker|breaker_open" salio
vacio — esperado, no hay degradacion para gatillar el breaker.

Wire test alternativo via `manage.py shell` en el binario
desplegado:

```
av    threshold=5 cooldown=30.0s allow=True    ← settings defaults
hibp  threshold=5 cooldown=60.0s allow=True
smtp  threshold=5 cooldown=60.0s allow=True

start            allow=True
after 1 fail     allow=True
after 2 fail     allow=True
circuit_breaker.opened name=probe failures=3 cooldown_s=0
after 3 fail     allow=False
after cooldown   allow=True   (half-open probe)
after success    allow=True   (closed again)
```

State machine + factory + settings integration verdes en wild.

Errores de Console visibles en las capturas son ruido conocido y
pre-existente al bundle #8/#9:
- `Cross-Origin-Opener-Policy header has been ignored` → esperado
  por HTTP (no HTTPS) en `10.100.100.16`. Desaparece con TLS.
- `Connecting to https://cdn.jsdelivr.net/.../swagger-ui-dist.map`
  blocked por `connect-src 'self'` → sourcemap de swagger-ui, no
  afecta rendering. Pre-existente desde 19-jun.
- `cdn.redoc.ly/redoc/logo-mini.svg` blocked por `img-src 'self'
  data:` → logo de ReDoc, cosmetico. Pre-existente.
- `window.__chromium_devtools_metrics_reporter is not a function`
  → del DevTools de Chrome, ajeno a la app.

Cosmetic follow-up: el log line del breaker usa `%.0f` para
`cooldown_seconds`, lo que muestra `cooldown_s=0` cuando el
cooldown es < 0.5 s (como en los tests unit). En prod con 30/60 s
no se ve. Pulir a `%.1f` si re-pasamos por el modulo.

## §4. Decisiones tomadas

1. **Servidor pullea SOLO `dev`** — convencion ratificada el 21-jun
   se mantiene. Esta sesion `main` quedo en `1355060`, dev avanza
   10 commits (#8b → #9 → handoff close). NO promote a main sin
   instruccion explicita "milestone".
2. **#8 partido en 8a + 8b** — TT CSP (8b) primero porque toca
   flujo MFA sensible y queriamos pasarlo antes de meter la
   capa SRI. SRI fue refactor chico autocontenido despues.
3. **Trusted Types policy unica** (`ameli-template`) — identity
   wrapper, no DOMPurify. Justifica: solo recibimos HTML de NUESTRO
   propio backend. Una policy DOMPurify-backed agregaria runtime
   dep + perf cost por validacion sin beneficio. Si en el futuro
   integramos contenido user-supplied que tenga que ir por
   innerHTML, refactorizamos a una policy DOMPurify entonces.
4. **TT enforced en project-wide CSP, OFF en /django-admin y
   /docs**. Las 2 surfaces tienen inline scripts (framework / CDN)
   que no podemos wrappear; meterles TT romperia el admin y
   Swagger UI. Trade-off conocido y documentado en build_csp.
5. **SRI sobre propios falla-graceful**, no falla-loud. Un asset
   missing devuelve `""` (sin integrity) en vez de 500. Razon: un
   typo en `{% sri_for %}` no debe tirar el render — la regresion
   sigue siendo visible (browser reporta "no integrity" en
   DevTools) sin romper la UX.
6. **Breaker state process-local** — no Redis / shared cache.
   Razon: el template intencionalmente no agrega deps externas;
   worst-case (N workers descubren el outage independientemente)
   es bounded y aceptable.
7. **SMTP queue skip-batch sin bumpear `attempts`** — si
   bumpearamos attempts durante un outage conocido, los emails
   legitimos llegarian a `max_attempts` y se marcarian permanently
   failed sin haber tenido una verdadera oportunidad de delivery.
8. **`scripts/update.sh` es el deploy canonico**, no `install.sh`.
   Confirmado en `docs/FIRST_INSTALL_DJANGO.md` §"Primera
   actualizacion". `install.sh` queda solo para la primera
   instalacion en un host nuevo.

## §5. Metricas al cierre

| Metrica | Inicio dia (22-jun) | Cierre dia (22-jun) | Δ |
|---|---|---|---|
| Suite local (sin deselect) | 948 | **987** | +39 (+4 TT, +5 SRI, +13 breaker, +6 unix scheme, +11 OTel) |
| Coverage % (branch + line) | 85% | 85% (floor pinned) | 0 |
| mypy errors en src/ | 0 / 47 | 0 / 50 | +3 archivos (sri.py, sri __init__.py, circuit_breaker.py) sin errores |
| Commits sobre `dev` (sesion) | 0 (`c643af8`) | 5 (+ doc closer) | — |
| ASVS L2 active rows PASS | 151 | 151 (+ V12.4.1 ahora strict-shippable post `a51d2b8`) | 0 (+1 movido de partial → strict) |
| Mini-roadmap items closed | 7 / 12 | **10 / 12** | +3 (#7, #8, #9 — Fase 3 + Fase 4 ambas closed) |
| Wire tests verdes | 1 acumulado | **4 nuevos** (#8 full smoke browser + curl, #9 manage.py shell, unix:// + EICAR contra clamd real, OTel parte A dormant verify) | +4 |
| Bugs encontrados via wire | 0 | 0 (falso positivo de `curl -I` sobre /docs descartado; visibility gap del log line de OTel boot documentado) | 0 |
| Version | `v0.4.0-django` | **`v0.4.0-django`** (security + observabilidad opt-in, no bump funcional) | 0 |
| Lockfile entries (líneas con hash) | baseline | +254 (deps OTel + transitives) | — |
| Source files (mypy clean) | 47 | **51** (+SRI tag, +circuit_breaker, +telemetry) | +4 |
| Branches state | `dev @ c643af8`, `main @ 1355060` | `dev @ <this>`, `main @ 1355060` (sin tocar) | — |

## §6. Hallazgos / findings

1. **Confiar en `curl -I` para CSP testing es engañoso.** HEAD
   bypassea logica de view en Django: la response pasa por
   middleware (que aplica project-wide CSP) pero no por el view
   que setea `_docs_csp`. Resultado: HEAD trae project-wide CSP
   incluso en endpoints que SI overridean en GET. Mi unit test
   inicial paso porque stub-eaba `OPENAPI_SRI_REQUIRED`, no
   modelaba el HEAD vs GET. Para futuros CSP wire tests: usar
   `curl -s -D -` (GET con dump de headers) en vez de `curl -sI`.
2. **El operador pidio doc-first cuando le entregue comandos de
   deploy** — yo daba `install.sh` directo y el operador me
   redirigio a buscar en la doc. La respuesta correcta estaba en
   `docs/FIRST_INSTALL_DJANGO.md` §"Primera actualizacion":
   `scripts/update.sh` (que añade backup previo + validate al
   final). Leccion: ANTES de entregar comandos operativos, grep
   la doc por la operacion en cuestion.
3. **Trusted Types policy unica es la decision correcta para
   este template** porque todo el HTML que va a sinks proviene
   de NUESTRO propio backend. Si en el futuro renderizamos
   contenido user-supplied via `innerHTML`, tendremos que
   migrar a un policy DOMPurify-backed o similar. Patron a
   tener en mente.
4. **Breakers con cooldown sub-segundo confunden el log line**
   por el `%.0f` del format string. Cosmetic, no afecta prod
   (cooldowns 30/60 s), pero documenta el cuidado al formatear
   floats que pueden ser <1 en testing.
5. **Debian 13 (trixie) `clamav-daemon` shippea con systemd socket
   activation por default**, y el drop-in
   `/etc/systemd/system/clamav-daemon.service.d/extend.conf`
   restringe la red de forma que aunque pongas `TCPSocket 3310 +
   TCPAddr 127.0.0.1` en `/etc/clamav/clamd.conf` y deshabilites
   `clamav-daemon.socket`, el daemon NO termina bindeando TCP
   (clamd arranca limpio pero `ss -ltnp | grep 3310` queda
   vacio y `connect()` da `ConnectionRefusedError`). El path
   "Debian-correcto" es hablar con clamd via su Unix socket
   `/var/run/clamav/clamd.ctl` (que ES el que socket-activation
   expone). El template hoy solo soporta `tcp://` y `http://`
   en `AMELI_APP_AV_ENDPOINT` — agregar el scheme `unix://...`
   es la fix correcta (~15 lineas en `scan_bytes` + un
   `_scan_clamd_unix` que use `AF_UNIX`). Documentado como
   follow-up de Fase 4 (ver §7).

   Wire test del 22-jun confirmo el gotcha en vivo: install
   limpio de `clamav-daemon` + `clamav-freshclam`, signatures
   bajadas ok (~110 MB), clamd corriendo, `clamdscan` local
   detectando EICAR via Unix socket — pero el endpoint TCP
   nunca bindeo. Operador rollback-eo limpio
   (purge de paquetes + remove env var). ASVS V12.4.1 queda
   como **mitigacion parcial** (Pillow + Content-Type
   whitelist + noexec FS + IDOR gate del serve) hasta que se
   shippee el soporte `unix://`.

   **Beneficio adicional del fix**: con `unix://` el template
   queda plug-and-play en cualquier Debian futuro — el
   operador hace `apt install clamav-daemon` y setea
   `AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl`
   sin tocar systemd ni clamd.conf.

6. **`setup_otel()` corre antes que Django configure logging**
   (asgi.py llama bootstrap antes de `get_asgi_application`), asi
   que el `logger.info("otel.disabled reason=no_endpoint")` se
   filtra del root logger y nunca aparece en `journalctl`. NO es
   bug funcional — `manage.py shell` + `is_enabled()` confirman
   estado correcto — pero la observabilidad del propio bootstrap
   queda muda. Fix posibles: bump a `WARNING` (semantica rara
   pero garantiza visibility), o `logging.basicConfig(level=INFO)`
   en asgi.py antes de `setup_otel`. Documentado como follow-up
   cosmetico en §7.

7. **Primer install de clamav-daemon en Debian deja el unit
   inactive** hasta el primer `systemctl restart` post-freshclam.
   Causa: el package shippea sin DBs, el daemon refuses to start
   hasta tener signatures, freshclam baja signatures pero no
   puede notificar a clamd (`/var/run/clamav/clamd.ctl` no existe
   todavia — "Clamd was NOT notified" en el freshclam journal).
   Una vez que freshclam baja `main.cvd + daily.cvd + bytecode.cvd`,
   `systemctl restart clamav-daemon.service` crea el socket y
   subsequent boots / redeploys son automaticos via socket
   activation. Documentado en `docs/OPERATIONS.md` § "Debian /
   Ubuntu first-install gotcha" con commands.

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras:

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | **✓ closed esta sesion** |
| 4. Hardening | #8 SRI+TT, #9 circuit breakers + unix:// AV | **✓ closed esta sesion** |
| 5. Performance | #10 django-silk, #11 pool tuning | open |
| 6. E2E | #12 Playwright | open |

Net: **10/12 closed**. Quedan SOLO Fase 5 (#10 + #11) + Fase 6 (#12).

Follow-ups documentados:
- **`unix://` scheme en `av.py`** — SHIPPED `a51d2b8` + wire test
  contra clamd real (`unix:///var/run/clamav/clamd.ctl`):
  `clean: ('ok', '')`, `eicar: ('infected', 'Eicar-Test-Signature')`.
  ASVS V12.4.1 **strict-shipped** sobre Debian.
- **OpenTelemetry tracing** — SHIPPED `8de62d1` + wire test parte
  A (deploy dormant verify) en `ha-report2`. Parte B (Jaeger via
  docker) NO se ejecuto porque el servidor no tiene docker
  instalado; el bootstrap + integracion estan pinneados via los
  9 unit tests + `manage.py shell` smoke. Cuando el operador
  quiera activar tracing en wild, solo necesita un collector
  (otel-collector standalone via apt, o docker si lo instala) +
  un `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://...:4317` en
  app.env + restart api.
- **Cosmetic — OTel boot log no aparece en journal** (§6 #6):
  `setup_otel()` corre antes que Django configure LOGGING.
  Solucion 2-liner: bump `logger.info` → `logger.warning` en
  ambos paths (enabled / disabled) o `logging.basicConfig` en
  asgi.py. NO afecta funcionalidad. Reagendar si la proxima vez
  que activemos OTel queremos ver el "enabled" line en journal.
- **Cosmetic — log format del breaker** (`%.0f` → `%.1f` para
  cooldowns visibles en testing). Sin shippear, no afecta prod.
- **HEAD vs GET en `_docs_csp`** no es bug — los browsers nunca
  envian HEAD para esos endpoints. Documentado en §6 como gotcha
  de wire testing.

Sub-gotcha de primer install de clamav-daemon en Debian (§6 #7)
ya documentado en `docs/OPERATIONS.md` § "Debian / Ubuntu
first-install gotcha".

## §8. Continuidad — para el proximo agente

`dev @ <closer-commit>` (cierre re-cerrado del 22-jun). `main @ 1355060`
sin tocar — convencion del 21-jun ratificada. 14 commits
adelantados en `dev` desde el ultimo match con main:

- `d70bff6` Convencion branches en §2 del 21-jun
- `32dc83f` Cierre wire test 21-jun + journal review
- `af6b185` Dashboard + admin hero honran has_avatar
- `9c800a9` Drop ring + gradient backdrop cuando hay imagen
- `6ac13fc` Drop ring del menu-avatar chip top-right
- `f76af65` Hero avatar 72→96 + radius 24→28
- `d279c24` §3 del 21-jun amplificado con polish 22-jun
- `c643af8` Cierre §4-§8 del handoff 21-jun
- `08e2583` Open handoff 22-jun
- `2db09cb` Mini-roadmap #8b Trusted Types CSP
- `afa083d` Mini-roadmap #8a SRI sobre propios
- `39d3243` Mini-roadmap #9 circuit breakers AV/HIBP/SMTP
- `1a2ea7f` Cierre §2-§8 del handoff (primer pase)
- `3885252` Doc follow-up clamav Unix-socket
- `a51d2b8` Scheme `unix://` en `av.py` (ASVS V12.4.1 strict)
- `9c16b2d` Wire test unix:// AV verde + close follow-up
- `8de62d1` OpenTelemetry tracing opt-in (Fase 3 closed)
- (+ `<this>` re-cierre handoff 22-jun con OTel + wire test parte A)

Server `ha-report2` corriendo `8de62d1` (wire test parte A del
OTel confirmado via update.sh + manage.py shell + `is_enabled()`
False / ProxyTracer en dormant state). El re-cierre del handoff
es doc-only, NO require re-deploy.

**El siguiente agente NO debe**:
- Promote `dev → main` automaticamente. Esperar instruccion
  explicita "milestone" del operador.
- Tratar auto-prompts del harness ("Continue from where you
  left off") como instruccion del operador. Pausar y confirmar.
- Entregar comandos operativos sin chequear primero la doc
  (`docs/FIRST_INSTALL_DJANGO.md`, `docs/OPERATIONS.md`).

**El siguiente agente debe**, en orden de prioridad:

1. **Si operador dice "milestone"**: promote `dev → main` con el
   bundle del 21-22 jun. Tag queda `v0.4.0-django` (no hubo bump
   esta sesion).
2. **Si no hay milestone**: esperar direccion del operador. NO
   inventar tareas.

**Follow-ups del 22-jun ya cerrados en esta misma sesion**:
- `a51d2b8` scheme `unix://` en `av.py` — ASVS V12.4.1
  strict-shipped + wire test contra clamd real en `ha-report2`.
  Server tiene `AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl`
  en `app.env`.
- `8de62d1` OpenTelemetry tracing — Fase 3 closed. Tracing
  opt-in via `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`. Deps
  pesadas (grpcio + 16 packages) ya en lockfile. Wire test
  parte A verde; parte B (Jaeger) requiere docker (no
  disponible en `ha-report2` hoy).

**Mini-roadmap pendiente (2/12)**:
- **#10 django-silk** + **#11 connection pool tuning** (Fase 5
  Performance) — silk para profiling local de DB queries +
  templates; pool tuning para que el deploy aguante mas
  concurrencia sin que psycopg se vuelva el bottleneck.
- **#12 Playwright e2e** (Fase 6) — cerraria los tests de
  regresion visual del avatar listados en follow-ups del 21-jun
  §7. Toca CI + agrega Node deps + un docker-compose para
  correr el browser headless. Mas pesado que #10/#11.

**Otros candidatos NO en el mini-roadmap** que pueden interesar:
- Wire test parte B de OTel cuando haya docker disponible en
  el server, o cuando se instale `otel-collector` standalone
  via apt — para validar in-wild que los spans se exportan
  correctamente y se ven en el viewer.
- Fix cosmetico del log line de OTel boot (§7 follow-ups).
- Bump cosmetico del format del log line del breaker (§7
  follow-ups).

**Patrones operacionales ratificados** (incorporar al playbook):
- Server pullea SIEMPRE `dev`. Promote a `main` solo por
  instruccion explicita "milestone".
- Auto-prompts del harness ≠ instruccion del operador.
- ANTES de entregar comandos operativos: chequear la doc por
  el flow canonico.
- Para CSP wire testing: `curl -s -D -` (GET) en vez de
  `curl -sI` (HEAD).
- Cuando un fix toca un asset compartido (template, CSS class,
  helper, modulo de wire), grep TODOS los consumidores antes
  de cerrar.
- Comentarios Django multi-linea: `{% comment %}`, nunca `{# #}`.
