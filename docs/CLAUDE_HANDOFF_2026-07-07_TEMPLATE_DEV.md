## AMELI App Template handoff (sesion Claude, 2026-07-07)

Fecha: `2026-07-07`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `72470ee` al cierre; version `v0.4.12-django`)
Rama estable: `main` (default en GitHub; congelado hasta v0.5.0/v1.0.0)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-06_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-06_TEMPLATE_DEV.md)

> **Nota**: sesion continuada tras compactacion de contexto. Cubre lo que
> quedo fuera del handoff 2026-07-06: **a11y++** (focus-trap de modales,
> `v0.4.12`) y **D-1 Fase A** (identidad visual — paleta + tipografia),
> esta ultima **commiteada pero sin bump, pendiente de smoke en server**.

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
| Version | **`v0.4.12-django`** (a11y++); D-1 Fase A commiteada sin bump |
| HEAD | `72470ee` |

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
D-1 **en curso**: Fase A commiteada (pendiente smoke + bump).

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| **D-1 Fase A** | Smoke visual en server + bump | — | **SIGUIENTE PASO** — commiteado en `72470ee`, sin bump |
| D-1 Fase B | Jerarquia + layout (hero gradient, bordes de acento en cards primarias, max-width 1440, escala de spacing) | ~2h | Tras aprobar la paleta en server |
| D-1 Fase C | Elemento signature (el review propone un sparkline de salud animado en el header) | ~1-2h | — |
| D-1 Fase D | Motion (reveal escalonado al cargar, hover states) | ~1h | — |
| Promote | `dev → main` v0.5.0 | — | `main` congelado; requiere instruccion explicita |
| Low/opt | `django-csp`, Prometheus lib, Ansible, jsdom | — | Ninguno urgente (`TECH_EVOLUTION.md`) |

### OPS — branch protection (latente, no accionable)

Sin cambios: bloqueado por el plan Free privado (`gh api .../protection` →
403). Payload listo en `OPERATIONS.md` para cuando se suba a Pro/Team o se
haga publico. No es olvido.

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama **`dev`**, version **`v0.4.12-django`**, todo pusheado (HEAD
  `72470ee`). `main` congelado.
- Sesion: a11y++ (focus-trap de modales, `v0.4.12`) + D-1 Fase A (identidad
  navy+teal + DM Sans/IBM Plex, **commiteada sin bump**).
- Validado: unit 1068 verde, 13/13 a11y (claro+oscuro+teclado+modal). CI dev
  verde. a11y++ smokeado en server (`v0.4.12`). **D-1 Fase A NO smokeada en
  server todavia** — es el proximo paso.
- Entorno dev = Windows nativo. `gh` CLI en `C:\Program Files\GitHub CLI\`
  (no en PATH — invocar por ruta).

### 8.1. Primer paso (siguiente agente)

**Smokear D-1 Fase A en el server `ha-report2`** (sync a `72470ee`,
`check`, restart, verificar `/health`), y pedir al operador aprobacion
visual de la paleta teal + tipografia. **Si aprueba** → bump a `v0.4.13`
(los 4 archivos) y seguir con **Fase B** (jerarquia/layout). **Si no** →
ajustar el teal/tipografia antes de construir encima.

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
