## AMELI App Template handoff (sesion Claude, 2026-06-21)

Fecha: `2026-06-21`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — commit del open)
Rama estable: `main` (sync `e9d1e24`, recien promovido del cierre 20-jun)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `main == dev == e9d1e24` (sync absoluto al
  abrir).
- Tests: **943 passed** sin deselect. CI #117 verde sobre
  `676d6a2` (parent del handoff close).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 47 archivos src.
- Version: `v0.4.0-django` (deployed en `ha-report2` con todos
  los checks de `/health/deep` operativos tras el wire test del
  20-jun).
- ASVS L2: 151 PASS / 0 strict GAP.
- Mini-roadmap mejoras: 7/12 items shipped (Fase 1+2 closed,
  Fase 3 partial: #6 mypy done, #7 OpenTelemetry pendiente;
  Fases 4-6 abiertas).
- Frente abierto del 20-jun §8:
  - Promote `dev → main` post-cierre ← **DONE al abrir 21-jun**.
  - Re-install + wire test del avatar UI en `ha-report2`.

## §2. Objetivo de la sesion

Wire test del nuevo bundle deployado a `ha-report2`:
1. Re-correr `install.sh` con el fix `d4ade5e` (auto-restart
   de daemons running). Validar que el operador YA NO necesita
   restart manual post-upgrade.
2. Smoke del avatar UI: login → `/profile/` → upload imagen →
   verificar render → delete → vuelve a iniciales.
3. Smoke del dark mode (#3 de Phase 1) si no se valido aun
   visualmente.

Si el wire test queda verde, sesion cierra con el bundle del
20-jun confirmado en produccion. Si surge bug nuevo, fix in
template + re-deploy (patron del 20-jun PT-4).

### Convencion de branches (ratificada por el operador 2026-06-21)

| Branch | Rol |
|---|---|
| `dev` | Server `ha-report2` pullea SIEMPRE de aca. Bleeding-edge para wire test. |
| `main` | Solo se actualiza cuando cerramos un bloque GRANDE de desarrollo + testeado. Es una "milestone branch", no un continuous sync. |

Mi error en sesiones 06-20 / 06-21: cambie silenciosamente las
instrucciones del wire test para que server pullee `main` en
vez de `dev`. El operador me corrigio. **Para el proximo
agente**: server pull = `dev`. Promote a main solo cuando el
operador explicitamente dice "milestone, llevalo a main". NO
hacer fast-forward automatico despues de cada CI verde.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `4e986e7` | Open 2026-06-21 handoff | suite stays green |
| `1f3190c` | Boot guard: refuse `data_dir` / `profile_uploads_dir` inside checkout (post-wire-test fix) | 943 → 945 (+2) |
| `1355060` | Record 2026-06-21 avatar wire test + boot guard en §3 del handoff | doc only |
| — | Fast-forward `dev → main` (`e9d1e24..1355060`) — mi error de convencion, NO se revierte porque dev==main coinciden ya | — |
| `d70bff6` | Documentar convencion branches en §2: server pullea SOLO `dev`; `main` = milestone manual | doc only |
| `32dc83f` | Cierre del wire test del 21-jun + journal review del 500 en §3 | doc only |
| `af6b185` | Hero del dashboard + admin panel honran `current_user.has_avatar` (mismo patron que profile.html) | 945 → 948 (+3) |
| `9c800a9` | Avatar UI polish: drop ring + gradient backdrop del hero cuando hay imagen | suite stays green |
| `6ac13fc` | Sibling: drop ring del chip top-right (`.menu-avatar.has-image`) | suite stays green |
| `f76af65` | Hero avatar 72→96px (radius 24→28, iniciales 28→36) para mejor proporcion respecto al panel | suite stays green |

### Wire test 2026-06-21 — avatar UI end-to-end

Server `ha-report2` sync a `main @ e9d1e24` (bundle del cierre
20-jun). install.sh corrio con el fix d4ade5e: 23 OK / 0 WARN
/ 0 FAIL, daemons restart-eados automaticamente, `/health`
reporto `v0.4.0-django` SIN restart manual (fix confirmado
in wild).

Wire UI del avatar revelo dos bugs reales:

1. **Comentario Django multi-linea filtrado como HTML**. Mi
   commit del 20-jun (`676d6a2`) puso un `{# ... #}` de TRES
   lineas en profile.html. Django solo entiende `{# ... #}`
   en una sola linea; multi-linea se imprime como texto plano.
   Fix: `{% comment %}...{% endcomment %}`. Caught en el wire
   test del UI nuevo.

2. **POST /profile/avatar/ → 500** al subir un webp valido.
   Root cause: `profile_uploads_dir` defaulteaba a
   `data/uploads/{env}` (path relativo). `path_from_value`
   en config.py lo anclaba contra PROJECT_DIR (= /opt/<slug>/,
   root-owned). MEDIA_ROOT terminaba en root-only dir,
   `default_storage.save()` reventaba con PermissionError.
   **MISMA clase de bug que el `data_dir` del 20-jun
   /health/deep**.

Fixes shippeados en `1f3190c`:
- **Boot guard**: settings.py refuses MEDIA_ROOT / data_dir
  inside PROJECT_DIR cuando NOT _IS_DEV_ENV. Loud fail at
  startup beats subtle fail-at-first-write. Dev conserva
  paths relativos por convenience.
- **Env overrides nuevas**: `AMELI_APP_DATA_DIR` y
  `AMELI_APP_PROFILE_UPLOADS_DIR` para que operadores
  puedan inyectar absolutos sin tocar yaml.
- **Helpers de test** actualizados (`test_settings_boot_guards`,
  `test_host_cookie_prefix`) — auto-set `/tmp/test-*` en prod
  fixtures.
- **Test nuevo** `test_non_dev_refuses_media_root_inside_checkout`
  pinea el guard contra la specific relative-default que
  surface el bug.

Operator workaround in wild (aplicado durante el wire):
```bash
sed -i.bak2 's|profile_uploads_dir:.*$|profile_uploads_dir: /var/lib/ameli-app-template-dev/uploads|' /etc/ameli-app-template-dev/app.yaml
mkdir -p /var/lib/ameli-app-template-dev/uploads
chown -R ameli-app-template-dev:ameli-app-template-dev /var/lib/ameli-app-template-dev/uploads
chmod 750 /var/lib/ameli-app-template-dev/uploads
systemctl restart ameli-app-template-dev-api.service
```

Estado final wire-verified en `ha-report2`:
- POST /profile/avatar/ con `.webp` valido → 302 redirect a
  /profile/ + "Imagen de perfil actualizada." flash.
- Hero del profile swappea a `<img>` con la imagen real.
- Top-right menu chip muestra el avatar.
- GET /media/avatars/admin-16ca30139a9f984d.webp → 200 OK
  vía IDOR gate (owner serving su propio avatar).

### Journal review del 500 del wire test

Pedi journal de los 30 min del wire test buscando el
traceback del 500. Resultado: uvicorn solo loggea access lines
a nivel INFO; el traceback del 500 lo swallow-a el handler de
error de Django y se renderiza al cliente (no aparece en el
journal a nivel default). **Diagnostico se confirma
empiricamente** por el patron before/after:

```
08:17:11  POST /profile/avatar/ → 500   (yaml relativo)
08:19:33  systemctl restart  (post sed + chown del yaml)
08:19:39  POST /profile/avatar/ → 302 Found   (yaml absoluto)
08:19:39  GET /media/avatars/admin-...webp → served via IDOR gate
08:26:29  POST /profile/avatar/delete/ → 302 Found
08:26:45  POST /profile/avatar/ → 302 Found    (re-upload OK)
```

Para futuros tracebacks de 500: o subir `DJANGO_LOG_LEVEL=DEBUG`
o usar el structured log si el operador lo configura.

### Correccion de convencion de branches (mid-sesion)

Sin avisar, cambie las instrucciones del wire test 06-20/21
para que el server pullee `main` en vez de `dev`. El operador
detecto el cambio y me corrigio: convencion del proyecto es
**server pulea SIEMPRE `dev`**; `main` solo avanza cuando se
cierra un bloque grande de desarrollo + validado, decision
explicita del operador.

Concecuencias inmediatas:
- Mi promote `dev → main` del 21-jun (`e9d1e24..1355060`) no
  se revierte porque dev y main coinciden hoy; queda como
  registro historico.
- A partir de aca: NO mas fast-forward automatico despues de
  CI verde. Server pulls = dev.
- Re-install pendiente en `ha-report2` usa `git fetch origin dev
  && git reset --hard origin/dev` (NO main).

Leccion: cualquier cambio de convencion operativa requiere
confirmacion explicita del operador antes de implementarlo.

### Avatar UI polish — follow-up 2026-06-22

Re-deploy del wire test del 21-jun en `ha-report2` (sync a `af6b185`
con `git fetch origin dev && git reset --hard origin/dev && ./install.sh`,
23 OK / 0 WARN / 0 FAIL, daemons restart-eados automaticamente
otra vez por d4ade5e). Operador subio una captura del dashboard
mostrando que el hero seguia con la "A" inicial pese a tener avatar
seteado. Root cause: el 06-21 yo habia agregado el swap `has_avatar`
SOLO a `accounts/profile.html`; los hero de `dashboard/home.html`
y `admin/panel.html` seguian hardcoded a `current_user.initials`.

Fix `af6b185` aplica el mismo bloque en los tres templates y los
tests `test_dashboard_hero_shows_avatar_image_when_set` +
`test_admin_panel_hero_shows_avatar_image_when_set` lo pinean.

Luego de wire-verificar visualmente, operador pidio dos rondas de
pulido del avatar UI:

1. **Quitar el "halo" plateado alrededor de la imagen**. CSS de
   `.profile-avatar` y `.menu-avatar` aplicaba `box-shadow: ... 0 0 0
   2px rgba(148,163,184,.22)` (ring de 2px) ademas del drop shadow
   suave. El ring quedaba visible como halo plateado contra la foto.
   `.menu-avatar.has-image` ya neutralizaba el background gradient
   pero NO el ring; `.profile-avatar.has-image` no tenia override
   ninguno.

   Fix `9c800a9` + `6ac13fc`: cuando `.has-image` esta on, drop del
   gradient backdrop Y del ring; solo queda el drop shadow inferior
   en el hero, nada en el chip top-right. El path de iniciales
   (sin `has-image`) conserva el gradiente + ring originales — los
   PNG con transparencia ahora respetan su silueta sobre el panel
   en vez de mostrar el gradiente accent/ok detras.

2. **Subir el tamano del hero avatar** para mejor proporcion con
   el panel. Fix `f76af65`: 72→96px, radius 24→28 (conserva el
   ratio 24/72 ≈ 28/96), iniciales fallback 28→36 para que la
   letra escale. Chip top-right (`.menu-avatar`) sin tocar — 32px
   esta sized correcto para el nav row, no el hero.

Estado final wire-verificado en `ha-report2` (3 capturas operador
2026-06-22):
- Hero del dashboard: avatar 96px nitido sin halo, sticker rojo
  respeta el panel oscuro.
- Hero del profile: idem, mismo tamano, sin halo.
- Hero del admin panel: idem.
- Chip top-right: 32px sin halo, proporcionado al nav.

## §4. Decisiones tomadas

1. **Convencion de branches ratificada** (operador, mid-sesion
   21-jun): server `ha-report2` pullea SIEMPRE de `dev`; `main`
   solo avanza cuando el operador dice explicitamente
   "milestone". No mas fast-forward automatico tras CI verde.
   Mi promote del 21-jun (`e9d1e24..1355060`) queda como
   registro historico porque dev == main coincidieron, pero
   no se repite el patron.
2. **Boot guard "path inside checkout"** se enforza en non-dev,
   no en dev. Dev conserva paths relativos por convenience
   (los tests y el operador local los usan); en prod loud-fail
   at startup beats subtle fail-at-first-write. Misma clase de
   bug que `data_dir` (20-jun) y `profile_uploads_dir` (21-jun);
   cerrar la clase de una.
3. **Avatar UI: ring + gradiente OFF cuando `.has-image`**, ON
   cuando hay iniciales. Imagen reales no necesitan halo
   decorativo (la silueta ya la separa del panel); iniciales SI
   lo necesitan (el gradiente + ring es la "presencia" que
   reemplaza la foto). Diferente regla por estado, no toggle
   global.
4. **Hero avatar a 96px**, no 72 (under-anchored vs h2 28px) ni
   112+ (oversized en paneles densos). Mid-point que mantiene
   el chamfer ratio original (24/72 ≈ 28/96) y escala las
   iniciales fallback (28→36) proporcionalmente. Chip top-right
   queda en 32px porque ese tamano fue pensado para el nav row,
   no el hero.
5. **NO promote `dev → main` esta sesion**. Operador no marco
   milestone; cambios son UI polish + doc, no bloque grande de
   features cerrado. Bundle se acumula en dev hasta proxima
   sesion donde el operador decida.

## §5. Metricas al cierre

| Metrica | Inicio dia (21-jun) | Cierre dia (22-jun) | Δ |
|---|---|---|---|
| Suite local (sin deselect) | 943 | **948** | +5 (+2 boot guard, +3 dashboard/admin hero) |
| Coverage % (branch + line) | 85% | **85%** (floor pinned) | 0 |
| mypy errors en src/ | 0 / 47 archivos | **0 / 47 archivos** | 0 |
| Commits sobre `dev` (sesion) | 0 (start at `e9d1e24`) | 9 (4 wire-test fixes + 4 UI polish + 1 handoff close) | — |
| ASVS L2 active rows PASS | 151 | 151 | 0 |
| Mini-roadmap items closed | 7 / 12 | 7 / 12 | 0 |
| Wire test full stack | 1 verde (20-jun bundle) | **3 verdes** (avatar end-to-end 21-jun, UI polish 22-jun, install.sh auto-restart confirmado in wild) | +2 |
| Bugs latentes encontrados via wire | 0 | **3** (multi-line `{# #}` leaks, profile_uploads_dir relative path, hero hardcoded initials) | +3 |
| Version | `v0.4.0-django` | **`v0.4.0-django`** (UI polish, no bump) | 0 |
| Branches state | `dev == main == e9d1e24` | `dev @ d279c24`, `main @ 1355060` (5 commits ahead en dev, sin promote) | — |

## §6. Hallazgos / findings

1. **Clase de bug "path resuelto inside PROJECT_DIR"** se manifiesto
   por segunda vez (data_dir el 20-jun, profile_uploads_dir el
   21-jun). Mismo root cause: yaml usaba string relativo,
   `path_from_value` lo anclaba contra `/opt/<slug>/` (root-owned),
   primer write reventaba con PermissionError. Cerrado via boot
   guard que rechaza el path en startup cuando `not _IS_DEV_ENV`.
   Lecccion para futuros configs: cualquier path destinado a
   write-at-runtime debe ser absoluto en prod, validado en boot.
2. **Comentario Django `{# ... #}` es single-line only**.
   Multi-linea se renderiza como texto plano al cliente.
   `{% comment %}...{% endcomment %}` es el unico path para
   bloques. Mi commit del 20-jun (`676d6a2`) lo violo y el
   bug aparecio en el wire test del 21-jun. Lecccion: si vas
   a comentar varias lineas en un template Django, usar
   `{% comment %}` siempre.
3. **Fix UI parcial es un anti-patron del "endpoint POST sin
   UI consumer"**. El 21-jun fixee `accounts/profile.html`
   para honrar `has_avatar`; los heros de `dashboard/home.html`
   y `admin/panel.html` quedaron hardcoded a `initials`. El
   bug paso porque mire SOLO el template del endpoint, no los
   templates hermanos que renderizan el mismo dato. Mitigado
   via tests pinned (test_dashboard_hero_*, test_admin_panel_hero_*);
   patron checklist: "cuando agregas/cambias asset compartido,
   grep todos los templates que lo referencian".
4. **`.menu-avatar.has-image` override-aba background pero NO
   box-shadow**. El ring de 2px se inherita y queda visible
   contra cualquier imagen. Patron CSS-side del #3: si tenes
   una clase de override por estado, override TODA la
   decoracion que tiene sentido neutralizar, no solo una
   propiedad. Mismo bug applies a `.profile-avatar` (que no
   tenia override alguno).

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras (heredado del 2026-06-20 §7, sin
movimiento esta sesion):

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | partial — #6 done, #7 open |
| 4. Hardening | #8 SRI propios, #9 circuit breakers | open |
| 5. Performance | #10 django-silk, #11 pool tuning | open |
| 6. E2E | #12 Playwright | open |

Wire test arc 21-22 jun: **closed** (avatar UI end-to-end +
polish visual confirmado por operador en 3 capturas).

Follow-ups nuevos esta sesion (sin shippear):
- Checklist UI: "cuando agregas o cambias un asset compartido
  (avatar, badge, chip), grep todos los templates que lo
  renderizan antes de cerrar". Evitaria el bug del hero
  hardcoded del 21-jun.
- Tests de regresion visual: pinear via Playwright (#12 del
  mini-roadmap) que `.profile-avatar` no muestre ring cuando
  hay imagen — hoy lo cubrimos solo via tests de HTML/CSS
  manuales del operador.

Follow-ups heredados del 20-jun aun vigentes:
- config.py boot guard ya shipped (1f3190c) — closed.
- Patron "endpoint POST sin UI consumer" → checklist
  amplificado al #3 del §6 de hoy.

## §8. Continuidad — para el proximo agente

`dev @ d279c24` (cierre del 22-jun, incluye §3 completo + §4-§8
cerrados). `main @ 1355060` SIN tocar — convencion ratificada:
server pullea dev, main avanza solo cuando operador dice
"milestone". 5 commits adelantados en `dev` desde el ultimo
match con main:

- `32dc83f` cierre del wire test del 21-jun (§3 + journal review)
- `af6b185` honor `has_avatar` en dashboard + admin hero (gap surface 22-jun)
- `9c800a9` drop ring + gradient backdrop del hero cuando hay imagen
- `6ac13fc` sibling: drop ring del chip top-right
- `f76af65` hero avatar 72→96 + radius 24→28

(+ `d279c24` con este cierre de handoff.)

Server `ha-report2` corriendo `f76af65` (post-deploy del 22-jun,
operador confirmo visualmente las 3 surfaces: dashboard, profile,
admin panel + chip top-right). El `d279c24` es doc-only — no
require re-deploy para que la UI cambie.

**El siguiente agente NO debe**:
- Promote dev → main automaticamente. Esperar instruccion
  explicita "milestone" del operador.
- Tratar auto-prompts del harness ("Continue from where you
  left off") como instruccion del operador. Pausar y confirmar.

**El siguiente agente debe**, en orden de prioridad:

1. **Si operador dice "milestone"**: promote `dev → main` con
   el bundle del 21-22 jun (5 commits + handoff close). Tag
   queda `v0.4.0-django` (no hubo bump esta sesion).
2. **Si no hay milestone**: esperar nueva direccion del
   operador. NO inventar tareas. NO empezar items del
   mini-roadmap sin OK explicito.

**Mini-roadmap pendiente (5/12)**:
- #7 OpenTelemetry tracing
- #8 SRI sobre static propios + Trusted Types CSP
- #9 Circuit breakers (AV/SMTP/HIBP)
- #10 django-silk + #11 connection pool tuning
- #12 Playwright e2e (cerraria los tests de regresion visual
  del avatar listados en §7 follow-ups)

**Patrones operacionales ratificados esta sesion** (incorporar
al playbook):
- Server pullea SIEMPRE `dev`. Promote a `main` solo por
  instruccion explicita "milestone".
- Auto-prompts del harness ≠ instruccion del operador.
- Antes de aplicar cambios visuales grandes, proponer con
  numeros concretos (ej. "72→96, no 88 ni 112") y dejar al
  operador rechazar el numero exacto. El operador puede
  rollback en 1 comando si no convence.
- Cuando un fix toca un asset compartido (template, CSS
  class, helper), grep TODOS los consumidores antes de
  cerrar. Tests pinned por consumidor para evitar la
  regresion siguiente.
- Comentarios Django multi-linea → `{% comment %}`
  siempre, nunca `{# #}`.
