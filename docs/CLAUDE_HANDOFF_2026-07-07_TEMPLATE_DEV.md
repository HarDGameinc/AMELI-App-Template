## AMELI App Template handoff (sesion Claude, 2026-07-07)

Fecha: `2026-07-07`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version final `v0.4.16-django`)
Rama estable: `main` (default en GitHub; congelado hasta v0.5.0/v1.0.0)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-06_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-06_TEMPLATE_DEV.md)

> **Nota**: sesion continuada tras compactacion de contexto. Cubre lo que
> quedo fuera del handoff 2026-07-06: **a11y++** (focus-trap de modales,
> `v0.4.12`) y **D-1 identidad visual COMPLETA** (`v0.4.13`→`v0.4.16`):
> Fase A (paleta+tipografia) + paletas de color seleccionables, Fase B
> (jerarquia/layout, hero), Fase C (elemento signature), Fase D (motion).
> Todo validado en server (`ha-report2`) y CI. §9 detalla las paletas; §10
> el arco B/C/D + el hallazgo del allowlist de `/health`.

## §1. Snapshot al inicio

- Rama `dev`, version `v0.4.12-django`, working tree con la Fase A de D-1
  sin commitear (paleta + tipografia en `app.css` + `base.html`).
- El handoff 2026-07-06 cerro a11y+ (`v0.4.11`) + `THEMING.md`. Desde ahi
  ya se habia commiteado a11y++ (`d0f8307`, bump `1ba2b72` → `v0.4.12`).
- Entorno dev: Windows nativo, venv Python 3.14 desde rangos; server en
  Django 5.2.15 LTS via lock. Ver `CONTRIBUTING.md` "Local dev environment".

## §2. Objetivo de la sesion

Instruccion del operador: **cerrar el resto de a11y (a11y++) y arrancar
D-1** (identidad visual). Direccion de D-1 elegida por el operador:
**"Propuesta del review"** — navy + acento teal-verde, DM Sans (display) +
IBM Plex Sans (cuerpo). Ver `FRONTEND_DESIGN_REVIEW.md`.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `d0f8307` | a11y++: focus management de modales (trap + restore) + roles dialog | 13/13 a11y + 1068 unit |
| `1ba2b72` | Bump `v0.4.12-django` (tras smoke server de a11y++) | — |
| `72470ee` | D-1 Fase A: paleta navy+teal + tipografia DM Sans / IBM Plex Sans | 13/13 a11y + 1068 unit |

### 3.1. a11y++ — focus management de modales (`d0f8307`, `1ba2b72`)

Cierra el ultimo pendiente de accesibilidad. Los modales admin
(reset-password / change-role / delete-user) y el flujo sudo ahora cumplen
WCAG 2.1.2 (No Keyboard Trap, en su lectura correcta: el foco se *contiene*
pero se puede cerrar con Escape) y 2.4.3 (Focus Order):

- **Focus trap** (`admin-panel.js`): al abrir un modal se recuerda el
  trigger (`rememberModalTrigger`) y se enfoca el primer elemento
  focuseable dentro (`focusFirstIn`). Un keydown global atrapa Tab/Shift+Tab
  dentro de cualquier `.modal-backdrop` visible (ciclo entre el primer y
  ultimo focuseable via `MODAL_FOCUSABLE`).
- **Escape** se enruta por `[data-modal-close]` (no un handler ad-hoc), asi
  que cerrar por teclado usa la misma ruta que el boton.
- **Focus restore**: al cerrar, el foco vuelve al trigger que abrio el modal
  (`restoreModalFocus`), no al `<body>`.
- **Roles ARIA** (`admin/panel.html`): los 3 modales llevan
  `role="dialog" aria-modal="true" aria-labelledby=<id-del-h3>`.

Nuevo test e2e `test_admin_modal_traps_focus_and_escape_closes`. Suite a11y
sube a **13** (5 paginas x 2 temas + 2 teclado + 1 modal). Bump `v0.4.12`
tras smoke en server.

### 3.2. D-1 Fase A — identidad visual (paleta + tipografia) (`72470ee`)

Primera fase de D-1. Reemplaza el azul generico (`#155eef`) por la
identidad del review: **superficies navy + acento teal-verde**.

- **Paleta** (`app.css`), claro y oscuro: `--accent` → teal
  (`#0f766e` claro / `#22c9ac` oscuro), nuevo token `--brand:#00c9a7`,
  navy en `--bg`/`--surface`/`--ink`/`--line`. **Se conservo la estructura
  de tokens `--*-fill`** de v0.4.11 (fondo relleno bajo texto blanco), asi
  que el contraste 4.5:1 se mantiene en ambos temas.
- **Tipografia**: cuerpo → **IBM Plex Sans** (humanista); titulos
  (`h1-h4`, `.modal-title`, `.hero-title`, etc.) → **DM Sans** (geometrica,
  `letter-spacing:-0.015em`). Link de Google Fonts en `base.html` ya estaba
  permitido por la CSP (`fonts.googleapis.com` / `fonts.gstatic.com`).
- **Azules hardcodeados** restantes ruteados a los tokens teal: skip-link
  (`var(--accent-fill)`), tints `rgba(...)`, hover de `.refresh-btn`
  (`#2563eb` → `#0c5f59`, teal oscuro).
- El gate a11y (13/13) atrapo un fallo de contraste durante la fase
  (`--ok` claro como texto sobre tint verde daba 4.31:1) → se oscurecio
  `--ok` a `#0f6d3e` (dejando `--ok-fill:#157f4b` para pills de texto
  blanco). Todo verde tras el fix.

> **NO bumpeado**: la Fase A es user-visible y espera **smoke visual en
> server** antes del bump, por el ritual de `RELEASE.md`. Version sigue en
> `v0.4.12-django`.

## §4. Decisiones tomadas

1. **a11y++ antes de D-1** — deliberado: el gate a11y (claro+oscuro, 13
   checks) protege la Fase A de D-1 contra regresiones de contraste al
   cambiar toda la paleta. Se validó en la practica (§3.2, el `--ok`).
2. **Direccion de D-1 = "Propuesta del review"** (navy + teal, DM Sans +
   IBM Plex) — eleccion del operador sobre las alternativas del review.
3. **D-1 por fases** (A paleta/tipografia → B jerarquia/layout → C signature
   → D motion), commiteando y smokeando A primero: si el teal no convence,
   se ajusta antes de construir encima.
4. **Fase A sin bump** — commiteada para poder smokearla, pero el bump
   espera validacion visual en server (cambio user-visible).

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests (Windows local) | **1068 pass / 46 skip / 0 fail** |
| a11y (Playwright axe) | **13/13** (5 pag x 2 temas + 2 teclado + 1 modal) |
| Node JS tests | 13 pass |
| Ruff | 0 errores |
| CI (dev) | verde: matriz 3.11-3.14 + test-postgres + e2e + js-unit + pip-audit |
| Version | **`v0.4.16-django`** (D-1 completo A+B+C+D; ver §9 paletas, §10 B/C/D) |

## §6. Hallazgos / findings

### 6.1. El gate a11y valida cambios de paleta, no solo de codigo

Cambiar toda la paleta de D-1 y correr los 13 checks a11y (claro+oscuro)
atrapo el unico fallo de contraste (`--ok` sobre tint) antes de que llegara
al server. La secuencia a11y++ → D-1 hizo que la red de seguridad estuviera
lista justo cuando el mayor cambio visual la necesitaba.

### 6.2. Distincion texto vs relleno sigue viva en el rediseño

La estructura `--*` (texto/icono, colores brillantes) vs `--*-fill` (fondo
bajo texto blanco, mas oscuro) de v0.4.11 se preservo intacta en la nueva
identidad. Un futuro cambio de color debe respetarla: no colapsar `--ok` y
`--ok-fill` a un solo valor "porque se ve igual" — el segundo existe por
contraste con texto blanco encima.

## §7. Roadmap actualizado

**a11y cerrado por completo** (base + claro/oscuro + teclado + modales).
**D-1 COMPLETO** (`v0.4.13`→`v0.4.16`): Fase A (paleta+tipografia) + paletas
de color (§9), Fase B (jerarquia/layout, hero), Fase C (signature pulse),
Fase D (motion). Todo smokeado en server y bumpeado. Ver §10.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| Promote | `dev → main` v0.5.0 | — | `main` congelado; requiere instruccion explicita. Candidato natural tras D-1 |
| Refactor opt | Inline styles → utility classes en templates | ~2h | Cosmetico, no bloqueante (unico gap de front que queda) |
| Low/opt | `django-csp`, Prometheus lib, Ansible, jsdom | — | Ninguno urgente (`TECH_EVOLUTION.md`) |

### OPS — branch protection (latente, no accionable)

Sin cambios: bloqueado por el plan Free privado (`gh api .../protection` →
403). Payload listo en `OPERATIONS.md` para cuando se suba a Pro/Team o se
haga publico. No es olvido.

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama **`dev`**, version **`v0.4.16-django`**, todo pusheado. `main`
  congelado.
- Sesion: a11y++ (focus-trap de modales, `v0.4.12`) + **D-1 identidad
  visual COMPLETA** (`v0.4.13`→`v0.4.16`): A (navy+teal + DM Sans/IBM Plex +
  4 paletas seleccionables), B (jerarquia/layout, hero palette-aware), C
  (signature "telemetry pulse"), D (motion: reveal + hover). Ver §9 (paletas)
  y §10 (B/C/D + hallazgo `/health`).
- Validado: unit **1074** verde, **21/21 a11y** (4 paletas × claro/oscuro +
  teclado + modal). CI dev verde. Cada fase smokeada en server (`ha-report2`).
- Entorno dev = Windows nativo. `gh` CLI en `C:\Program Files\GitHub CLI\`
  (no en PATH — invocar por ruta).

### 8.1. Primer paso (siguiente agente)

**D-1 esta completo** — no hay fase de diseño pendiente. Elegir del roadmap
§7. El candidato natural es **promover `dev → main` para `v0.5.0`** (requiere
instruccion explicita del operador; `main` congelado, via PR). Si se sigue
en front, lo unico que queda es el refactor opcional de inline-styles →
utility classes (cosmetico). Regla al tocar cualquier color: sale de los
tokens (`var(--accent)` etc.) — nada hardcodeado, o se rompen las 4 paletas.

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` congelado hasta v0.5.0/v1.0.0; solo
  por instruccion explicita, via PR.
- Deploy (root, sin `sudo`): `git fetch && git reset --hard origin/dev` →
  `pip install --require-hashes -r requirements.lock` (no-op si no cambiaron
  deps) → `migrate` → `check` → `systemctl restart
  ameli-app-template-dev-api.service`. Esperar readiness antes de leer
  `/health` (handoff 2026-07-06 §6.2).
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self`.
- No romper la API publica de `services/` ni de `views/`.
- Preservar la distincion `--*` (texto) vs `--*-fill` (fondo) al tocar
  colores (§6.2).
- Correr ruff + mypy + pytest + node tests antes de cada push.
- Bump solo por cierre de fase validado en servidor.
- No instalar Playwright/chromium en el servidor (a11y/e2e se validan en
  CI Linux).

## §9. Extension: paletas de color (D-1, `v0.4.13`)

Tras aprobar la Fase A en server, el operador pidió (a) bajar el verde
fluorescente y (b) **varios temas** con cambio de fondo/bordes/acento. Se
implementó como un **segundo eje ortogonal** al modo claro/oscuro/auto.

### 9.1. Arquitectura

- **Modelo**: `User.color_theme` (choices `teal`/`indigo`/`amber`/`violet`,
  default `teal`) + migración `0014`. `display_palette_label` helper.
- **CSS**: los bloques base (`:root` …) son el default **Teal**. Cada
  `data-palette` añade bloques de override que cambian **solo** neutros +
  acento (`--bg --surface --ink --muted --line --accent --accent-fill
  --brand`) en claro / oscuro / auto. Los **estados** (`--ok/--warn/--bad`
  + fills, `--unknown/--closed`) **caen del base** → constantes entre
  paletas (verde=OK no cambia de significado). Light usa el selector
  `[data-palette=X]` pelado; los bloques dark/prefers-dark tienen mayor
  especificidad y ganan, igual que el base.
- **Aplicacion**: el context processor resuelve `active_palette` (siempre,
  default teal incluso anónimo) → `data-palette` en `<html>` en base.html.
- **UI**: swatches en el perfil (Django `RadioSelect` estilado con `:has()`
  + `input[value=...]::before` con degradado por paleta), focuseable por
  teclado. El campo es **opcional en el form** (`required=False` +
  `clean_color_theme` cae a la paleta actual) para que un POST parcial no
  tire la edición — un detalle que evitó romper 1 test existente y es más
  robusto. Persistido en las rutas JSON y form del `update_preferences`;
  el audit payload registra `color_theme`.

### 9.2. Decisiones

1. **Acento variable + neutros con tinte sutil** (no fondos saturados) —
   es el patrón de theming multi-marca de productos serios (GitHub/Linear).
   El operador validó las 4 en claro y oscuro y aprobó cerrar así.
2. **Estados constantes entre paletas** — evita que "verde/ámbar/rojo"
   cambien de significado y reduce la superficie de contraste a probar.
3. **Degradado de avatar/logo `accent → accent-fill`** (antes `accent →
   ok`) — monocromático por paleta; evita el degradado azul→verde en
   Índigo, etc. axe no evalúa degradados, así que no afecta el gate.
4. **Gate a11y = red de seguridad de color**: se extendió a las 4 paletas ×
   claro/oscuro sobre el dashboard (forzando `data-palette` por JS). 21 axe
   verdes cubren el riesgo real (contraste) sin multiplicar todas las
   páginas.

### 9.3. Gotcha corregido

El bloque **Auto** (`@media prefers-color-scheme: dark`) todavía tenía los
verdes **neón** originales: el primer tone-down solo tocó el bloque de
oscuro **explícito** (indentación distinta → el `replace_all` no lo pilló).
Un usuario en tema Auto+oscuro seguía viendo el neón. Al tocar tokens de
modo, cambiar **los tres** bloques (light / dark explícito / auto-media).

### 9.4. Añadir una paleta nueva (receta)

1. `User.PALETTE_CHOICES` + validar el valor en context processor, vista
   (ambas ramas) y el set del test a11y `_PALETTES`.
2. En `app.css`, 3 bloques `[data-palette="X"]` (light / dark / auto-media)
   con los 8 tokens de neutros+acento. Asegurar `--accent` (texto) ≥4.5:1
   sobre `--bg`/`--surface`, `--accent-fill` ≥4.5:1 bajo blanco, `--muted`
   ≥4.5:1. El gate a11y lo verifica.
3. Un swatch: `.palette-swatches label:has(input[value="X"])::before`.
4. Correr el gate a11y (`DJANGO_ALLOW_ASYNC_UNSAFE=true pytest
   tests/e2e/test_accessibility.py`).

## §10. D-1 Fases B / C / D (`v0.4.14`→`v0.4.16`)

Todo palette-aware (colores desde tokens) y reduced-motion-safe. Cada fase
smokeada en server antes del bump.

### 10.1. Fase B — jerarquia + layout (`v0.4.14`, commit `19a2b0f`)

- **Hero** (`.panel.profile-hero`): wash de acento (`radial-gradient` con
  `color-mix`), borde teñido, barra de 2px `accent→brand` arriba, sombra
  suave teñida. En **oscuro esto hace visible el color de la paleta** — sin
  esto los dark bg se veian casi iguales entre paletas (feedback del
  operador). Es el mayor win de jerarquia.
- **Header alineado**: se envolvio el contenido del header en `.header-inner`
  con el mismo `max-width` que `<main>`/`.footer-inner` (1320). Antes la app
  bar sangraba al borde de la ventana. El media query `<=880px` ahora apunta
  a `.header-inner`, no a `header`.
- Paneles: radio 8→12, mas padding; shell 1280→1320.

### 10.2. Fase C — signature "telemetry pulse" (`v0.4.15`)

Sparkline en el header (2 polilineas SVG: base tenue + segmento de barrido
con `stroke-dasharray` + `pathLength=100` para bucle perfecto), color =
`--accent`, `aria-hidden` (decorativo). `prefers-reduced-motion` lo congela.

**Hallazgo importante — `/health` es 403 para el navegador** (commits
`31a9684`→`ed36889`→`c5ec17d`): la sonda inicial hacia `fetch('/health')`
para reflejar salud en vivo, pero `/health` pasa por
`_operational_allowlist_block` (`HEALTH_METRICS_ALLOWLIST`, allowlist por IP
en `dashboard/views.py`). En deploys asegurados el navegador **no** esta en
la lista → **403 "forbidden"** (body texto plano → `.json()` lanzaba). Un
probe fallido + `403` en consola por pagina es mal default para un template,
asi que el pulso quedo **puramente decorativo** (no consulta `/health`). El
hook CSS `[data-health="degraded"]` queda documentado para deploys abiertos.
Se quito ademas el link `/health` del footer (daba "forbidden" a usuarios).

> Gotcha para el proximo agente: **no agregar features de salud que dependan
> de un `fetch('/health')` desde el navegador** — 403 en cualquier deploy con
> el allowlist. La salud del lado del cliente hay que resolverla server-side
> (las cards del dashboard ya lo hacen, renderizadas con el estado).

### 10.3. Fase D — motion (`v0.4.16`, commit `648923e`)

- **Reveal escalonado**: `main > *` hace `ameliReveal` (fade + slide-up) con
  `animation-delay` por `nth-child` (cap en el 5+). `fill-mode:both` evita
  flash a opacidad plena. El reduced-motion global colapsa la duracion →
  aparece instantaneo.
- **Hover**: `.summary-card-compact` / `.hero-stat` se elevan con borde de
  acento (`color-mix`) + sombra; `a.icon-action` gana transicion + wash.
- No rompe a11y: el reveal usa opacity/transform (el contraste que mide axe
  no cambia). 21/21 verde.
