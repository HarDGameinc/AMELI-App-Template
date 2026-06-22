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
| `<this>` | Cierre del handoff §2-§8 + wire test evidence | doc only |

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
| Suite local (sin deselect) | 948 | **976** | +28 (+4 TT, +5 SRI, +13 breaker, +6 unix scheme) |
| Coverage % (branch + line) | 85% | 85% (floor pinned) | 0 |
| mypy errors en src/ | 0 / 47 | 0 / 50 | +3 archivos (sri.py, sri __init__.py, circuit_breaker.py) sin errores |
| Commits sobre `dev` (sesion) | 0 (`c643af8`) | 5 (+ doc closer) | — |
| ASVS L2 active rows PASS | 151 | 151 (+ V12.4.1 ahora strict-shippable post `a51d2b8`) | 0 (+1 movido de partial → strict) |
| Mini-roadmap items closed | 7 / 12 | **9 / 12** | +2 (#8, #9) |
| Wire tests verdes | 1 acumulado | **3 nuevos** (#8 full smoke browser + curl, #9 manage.py shell, unix:// + EICAR contra clamd real) | +3 |
| Bugs encontrados via wire | 0 | 0 (falso positivo de `curl -I` sobre /docs descartado) | 0 |
| Version | `v0.4.0-django` | **`v0.4.0-django`** (security hardening, no bump) | 0 |
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

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras:

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | partial — #6 done, #7 open |
| 4. Hardening | #8 SRI+TT, #9 circuit breakers | **✓ closed esta sesion** |
| 5. Performance | #10 django-silk, #11 pool tuning | open |
| 6. E2E | #12 Playwright | open |

Net: **9/12 closed**. Quedan #7 OTel + Fase 5 (#10 + #11) + #12 e2e.

Follow-ups documentados:
- **`unix://` scheme en `av.py`** — **SHIPPED `a51d2b8`
  (post-handoff-close turn)**. ~70 LOC en av.py (refactor extract
  `_run_instream` shared + nuevo `_scan_clamd_unix`) + boot guard
  update en settings.py + doc en OPERATIONS.md. 6 tests nuevos
  (5 wire-shape + 1 boot guard). Wire-validado en `ha-report2`
  contra clamd real: `clean: ('ok', '')`, `eicar: ('infected',
  'Eicar-Test-Signature')`. ASVS V12.4.1 ahora **strict-shipped**
  sobre Debian, sin gotchas de systemd.
  - Sub-gotcha del wire test, ya documentado en OPERATIONS.md:
    primer `apt install clamav-daemon` deja la unidad inactive
    porque no hay DBs todavia; despues que freshclam termina hay
    que hacer un `systemctl restart clamav-daemon.service` UNA
    vez para crear el socket. Reboots / redeploys siguientes son
    automaticos.
- Cosmetic: format del log line del breaker (`%.0f` → `%.1f` para
  cooldowns visibles en testing). Sin shippear, no afecta prod.
- HEAD vs GET en `_docs_csp` no es estrictamente un bug — la
  respuesta a HEAD viaja sin body y los browsers nunca envian
  HEAD para esos endpoints. Documentado en §6 como gotcha de wire
  testing, no como fix pendiente.

## §8. Continuidad — para el proximo agente

`dev @ <closer-commit>` (cierre del 22-jun). `main @ 1355060`
sin tocar — convencion del 21-jun ratificada. 10 commits
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
- (+ `<this>` cierre handoff 22-jun)

Server `ha-report2` corriendo `39d3243` (wire test del 22-jun
confirmado por operador via update.sh + manage.py shell). El
cierre del handoff es doc-only, NO require re-deploy.

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

**Follow-up del 22-jun ya cerrado** (`a51d2b8`): scheme
`unix://` agregado a `av.py`, boot guard actualizado, docs
actualizadas, wire-validado contra clamd real en `ha-report2`.
ASVS V12.4.1 strict-shipped. Server queda en `a51d2b8` con
`AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl` en
`/etc/ameli-app-template-dev/app.env`. Ver §6 hallazgo #5 +
§7 follow-ups para el detalle.

**Mini-roadmap pendiente (3/12)**:
- **#7 OpenTelemetry** (Fase 3) — tracing opt-in via
  `AMELI_APP_OTEL_EXPORTER`. Touch grandes: agrega 4-5 runtime
  deps (`opentelemetry-api`, `opentelemetry-sdk`,
  `opentelemetry-instrumentation-django`, etc.). Operador no
  aprobo aun la adicion de deps; preguntar antes.
- **#10 django-silk** + **#11 connection pool tuning** (Fase 5
  Performance) — silk para profiling local, pool tuning para
  prod load.
- **#12 Playwright e2e** (Fase 6) — cerraria los tests de
  regresion visual del avatar listados en follow-ups del 21-jun
  §7. Toca CI + agrega Node deps.

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
