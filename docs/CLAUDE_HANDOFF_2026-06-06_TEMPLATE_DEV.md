## AMELI App Template handoff (sesion Claude, 2026-06-06)

Fecha: `2026-06-06`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-05_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-05_TEMPLATE_DEV.md).

Cierra el bloque completo de **paginacion + filtros server-side + AJAX
swap** sobre los tres listados operativos (profile sessions, admin users,
admin audit) y agrega el boton flotante "volver arriba" como complemento
final.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **272 tests pasando** (`pytest -v`)
- **0 regresiones**
- Verificado end-to-end visual: paginacion de profile sessions (32
  sesiones reales), paginacion de admin users (32 usuarios reales, con
  filtros de search/rol/estado), paginacion de admin audit (190 eventos
  reales, con filtros de actor/objetivo/accion/resultado), AJAX swap sin
  recarga, URL bookmarkeable, hash anchor que mantiene el tab activo,
  acciones del admin (cambiar rol/eliminar/etc) sobreviven el swap

### Contexto al arrancar

El cierre del 2026-06-05 cerro 4 items tacticos (Sesiones tab, botones
MFA, smtp_password_file, CLI autodetect) y dejo abierto el bloque
estrategico de paginacion. El usuario propuso ideas concretas: paginar
profile sessions, admin users, admin audit; y agregar un boton "volver
arriba" como complemento.

### Pre-flight del dia (review de regresiones)

Antes de arrancar con codigo, corrida completa en el servidor para
confirmar baseline:

- `git log -1` → `790c579`
- `ameli-app config-check` / `db-status` → leen `/etc/<app>/app.yaml` y
  reportan SMTP + DB OK (auto-detect del 2026-06-05 funcionando)
- `pytest tests/` → 211 passed en Python 3.13 / Django 6.0.5
- Smoke test SMTP O365 → `OK enviado`
- `/health`, `/api/health`, `/docs`, `/redoc`, `/openapi.json` → 200
- Snapshot users: admin (TOTP+Email), tester (off)

Baseline limpio confirmado.

### Bloque paginacion: 7 commits

Plan acordado con el usuario: helper foundation, profile sessions, admin
users, admin audit, back-to-top. Patron uniforme: offset/limit + total
count + "Mostrando X-Y de N" + Prev/Next + URL bookmarkeable + AJAX swap
sin recarga.

| Commit | Bloque |
|---|---|
| `fe24922` | foundation: helper + footer parcial reutilizable |
| `1b1f473` | profile sessions paginadas |
| `ede9669` | fix: hash anchor para mantener el tab al paginar |
| `2d9e6fd` | refactor: AJAX swap para no recargar la pagina |
| `2dde00c` | admin users paginados + filtros server-side |
| `a839fe3` | admin audit paginado + filtros + outcome |
| `970b9d9` | boton flotante "volver arriba" |

#### `fe24922` — Foundation

Modulo nuevo `src/ameli_web/pagination.py`:

- `Page` dataclass con todo lo que necesita el template (items, page,
  total, has_prev/has_next, start/end_index, prev/next_page)
- `paginate_queryset(qs, page, per_page) -> Page` que usa
  `django.core.paginator.Paginator` internamente y clamp del page a
  ultima pagina valida (en lugar de 404)
- `paginate_list(rows, page, per_page) -> Page` para datos ya
  serializados en memoria
- `coerce_page()` y `coerce_per_page()` que parsean `request.GET` con
  fallback a defaults y clamps (page>=1, per_page in [1, 200])
- `Page.as_context(page_param="...", anchor="...")` que produce el dict
  consumido por el template parcial

Template parcial nuevo `_pagination_footer.html`:

- "Mostrando X-Y de N" + "Pagina A de B" + Anterior/Siguiente
- Preserva todos los otros query params al navegar (filtros, otros
  `*_page` keys de paneles hermanos)
- Si solo hay 1 pagina omite los controles
- "Sin resultados" cuando total=0
- Botones deshabilitados visualmente cuando no hay prev/next

CSS chico: `.pagination-footer`, `.pagination-controls`,
`.pagination-page-label`, `.icon-action.disabled` con border-top
discreto y gap responsive.

**23 tests** unitarios cubriendo coerce, paginate_list (primera /
middle / last / overflow / empty / clamp), paginate_queryset, as_context
shape.

#### `1b1f473` — Profile sessions paginadas

- Service `paginate_user_sessions(user, page, per_page,
  current_session_key) -> Page` usando el orden default
  `-last_seen_at` de `UserSession.Meta`
- `profile_view` lee `?sessions_page=N`, pagina con 20/pagina, expone
  `session_pagination` al template
- Footer incluido al final del panel de Sesiones
- **9 tests** E2E (service + view rendering, fallback a primera pagina
  con param invalido, no controls si <=1 pagina, etc)

#### `ede9669` — Fix tab anchor

**Bug visible**: al clicar Siguiente, la recarga del profile volvia al
tab "General" porque las tabs son client-side JS sin URL state.

Fix:

- `Page.as_context()` ahora acepta `anchor="..."` (el HTML id del
  tab/section)
- El footer agrega `#<anchor>` a los links de Prev/Next
- El JS de tabs ahora:
  - Restaura el tab activo desde `location.hash` al cargar
  - Actualiza `location.hash` cuando el user clickea un tab
  - Escucha `hashchange` para mantener todo sincronizado

Resultado: Prev/Next reconstruye `/profile/?sessions_page=2#profile-tab-sessions`
y el tab Sesiones queda activo al cargar.

**1 test** nuevo que confirma `sessions_page=2#profile-tab-sessions`
aparece en el body.

#### `2d9e6fd` — AJAX swap

Decision del usuario: mejor sin recarga completa, ahora antes de
replicar el patron a admin (asi se aplica a los 3 listados sin
retrofittear).

Backend:

- Extraje el contenido del panel de Sesiones a un partial
  `accounts/_sessions_panel.html` (panel-header + events list + footer)
- `profile_view` detecta `?partial=sessions` y renderiza solo el partial
- El parent `profile.html` envuelve el partial en
  `<div class="panel" data-pagination-panel="sessions">`

Frontend (`app.js`):

- `swapPanelTo(panel, url)`: fetch con `?partial=<key>`, replace
  `panel.innerHTML`, `history.pushState`. Fallback a navegacion real si
  falla.
- Intercepta clicks en `.pagination-footer a` dentro de
  `[data-pagination-panel]`
- Marca el panel con `aria-busy` durante el fetch

Resultado: una sola request `GET /profile/?sessions_page=2&partial=sessions`
que devuelve solo el HTML del panel (~8 kB) vs. la pagina completa
(~50 kB con CSS/fonts/etc). Scroll preservado, sin flash.

**2 tests** nuevos para `?partial=sessions`.

#### `2dde00c` — Admin users paginados + filtros server-side

El admin antes tenia filtros client-side (JS busca/oculta filas) y
listaba todos los usuarios. Con paginacion los filtros tienen que ser
server-side, porque el cliente solo ve la ventana actual.

Backend:

- Service nuevo
  `paginate_users_for_admin(*, page, per_page, search, role, status) -> Page`:
  - `search` icontains contra `username` y `display_name` (OR)
  - `role` filtra por valor exacto si esta en
    {superadmin, public}; otros se ignoran
  - `status` mapea enabled/disabled a `is_active`
- `admin_panel` lee `users_search`, `users_role`, `users_status`,
  `users_page` del request, pasa al service, expone
  `users_pagination` al template
- Soporta `?partial=users` que devuelve solo `_users_panel.html`

Frontend (`_users_panel.html`):

- Toolbar antes era `<input id="users-search">` etc. con JS
  client-side. Ahora es `<form method="get" action="" data-filter-form>`
  con `name="users_search"`, `name="users_role"`, `name="users_status"`
- Valores precargados desde `users_filters` para que la form refleje el
  estado actual al recargar
- `<noscript>` con boton "Aplicar filtros" para fallback sin JS
- Panel envuelto en
  `<section class="panel" id="admin-users-panel" data-pagination-panel="users">`

Frontend (`app.js` extension):

- `buildFilterFormUrl(form, panel)`: construye URL con todos los params
  actuales del query string + form values; resetea el page param del
  panel (`users_page`) para que al cambiar el filtro vuelva a pagina 1
- `setupPaginationSwap()` ahora intercepta tambien:
  - `input` events (debounce 250ms) en `<input>` dentro de
    `form[data-filter-form]` dentro de `[data-pagination-panel]`
  - `change` events (inmediato) en `<select>`
  - `submit` events (inmediato) sobre la form

Migracion del handler de `data-user-action`:

- Antes: `usersList?.addEventListener("click", ...)` (atado al div
  contenedor)
- Despues: `document.addEventListener("click", event => { const button =
  event.target.closest("#users-list [data-user-action]"); ... })`
  (delegado desde document, sobrevive a los AJAX swaps)

Verificacion E2E con 30 demo users seedeados: paginacion real
(`Mostrando 26-32 de 32`), filtros aplicables sin recarga, "Cambiar rol"
funcionando despues del swap, URL bookmarkeable.

**13 tests** nuevos (paginate filters + view rendering + filter
preservation).

#### `a839fe3` — Admin audit paginado + filtros + outcome

Mismo patron que admin users. El audit antes mostraba 20 entries fijos
sin forma de ver mas antiguos.

Backend:

- Service nuevo
  `paginate_audit_for_admin(*, page, per_page, actor, target, action, outcome) -> Page`:
  - `actor`, `target`, `action` son icontains substring
  - `outcome` ok/error mapea a `action__endswith="_failed"` (incluyendo o
    excluyendo)
  - Order by `-created_at, -id` para estabilidad cuando hay timestamps
    iguales
- `admin_panel` agrega lectura de filtros + page del request
- Soporta `?partial=audit` que devuelve solo `_audit_panel.html`
- Hero stat del admin ahora muestra `audit_pagination.total` en lugar
  de `audit_entries|length` (que solo veia la ventana actual)

Frontend (`_audit_panel.html`):

- Toolbar nueva con 3 inputs (Actor, Objetivo, Accion) + select
  Resultado (Todos/OK/Errores)
- Lista paginada de 30 por pagina
- Footer reutilizando el partial

El JS y la infraestructura de swap ya existian del commit anterior asi
que el nuevo panel funciona sin tocar `app.js`.

Verificacion E2E con 190 eventos reales (de los seeds del bloque
anterior): paginacion 7 paginas, filtros debounced visibles en network
panel (cada caracter en Actor dispara un partial fetch),
combinaciones funcionan
(`?audit_actor=admin&audit_target=test&audit_action=login`), outcome
Errores muestra solo `*_failed`, URL bookmarkeable.

Edge case validado: dos paneles paginados (users + audit) coexisten en
la misma pagina con estado independiente en la URL
(`?users_search=...&audit_page=2&...`).

**13 tests** nuevos.

#### `970b9d9` — Boton "volver arriba"

Helper global en `app.js`:

- `setupBackToTop()` inyecta un `<button class="back-to-top">` en el
  body con icono `keyboard_arrow_up` + label "Arriba"
- Escucha `scroll` y `resize` (passive) para mostrar/ocultar segun
  `window.scrollY > 400`
- Click → `window.scrollTo({ top: 0, behavior: "smooth" })` (o `"auto"`
  si `prefers-reduced-motion`)
- Idempotente (chequea si ya existe)

CSS:

- `position: fixed; bottom: 24px; right: 24px; z-index: 60`
- Estilo accent pill con icono + label
- En viewport <=600px colapsa al icono solo, bottom/right mas chicos

No requiere cambios en templates; cualquier pagina que carga `app.js` lo
hereda automaticamente.

### Snapshot del Template al cierre

| Frente | Cobertura |
|---|---|
| Auth basico | login/logout, sesiones persistentes, audit por accion |
| Password policy | 12 chars + politica visible + generador + barra |
| Profile | identidad, alias, email editable, tema, password change |
| Profile 2FA stacked | TOTP + Email coexistentes, per-method disable, recovery |
| Profile self-service email | edicion + correo de prueba + auto-disable 2FA email |
| Profile sessions | **paginadas** (20/pag) + AJAX swap + hash anchor |
| Admin metro | crear / habilitar / reset / rol / forzar cambio / eliminar |
| Admin 2FA granular | badges TOTP+Email / TOTP / Email / requerido / off |
| Admin users | **paginados** (25/pag) + filtros server-side + AJAX swap |
| Admin audit | **paginado** (30/pag) + filtros (actor/target/action/outcome) + AJAX swap |
| Self-guards backend | rejects self-disable, self-role-change, self-mfa-toggle |
| Login flow stacked | password -> selector si 2+ metodos -> codigo |
| Password recovery | `/login/forgot/` + email reset link |
| Dashboard | hero + summary + sidebar adaptativos |
| Docs | `/docs`, `/redoc`, `/openapi.json` |
| Operacion | install/update/backup + systemd multientorno |
| Email | console/smtp/file/locmem + `password_file` opcional |
| CLI | autodetect del env file en `/opt/<app>-<env>/` |
| UX listados | boton "volver arriba" en pantallas con scroll largo |
| Tests | **272** (pytest -v), Python 3.13 / Django 6.0.5 verificado |

### Numeros del dia

- 7 commits promocionados a `main`
- **272 tests pasando** (211 al inicio → 272 al cierre, +61 tests)
- 6 archivos nuevos:
  - `src/ameli_web/pagination.py`
  - `src/ameli_web/templates/_pagination_footer.html`
  - `src/ameli_web/templates/accounts/_sessions_panel.html`
  - `src/ameli_web/templates/admin/_users_panel.html`
  - `src/ameli_web/templates/admin/_audit_panel.html`
  - 5 archivos `tests/test_*pagination*.py`
- ~1200 lineas netas agregadas
- 0 migraciones nuevas
- 0 deps nuevas

### Decisiones tomadas (no re-discutirlas)

- **Patron uniforme** Prev/Next + contador (no paginas numeradas) en
  los 3 listados, para reducir variabilidad UX
- **Page sizes**: 20 (sessions), 25 (users), 30 (audit) — calibrados a
  volumenes operativos esperados
- **Filter scope**: cuando paginamos, tambien migramos los filtros a
  server-side en el mismo commit, para evitar UX rota intermedia
- **AJAX swap** antes de replicar a admin (no despues), para que el
  patron AJAX aplique a los 3 listados desde el primer dia
- **URL state** via query params + hash anchor para tab; bookmarkeable
  y compatible con back/forward del browser
- **Reset a pagina 1** al cambiar filtros (no preservar la pagina
  cuando el universo cambia)
- **Filter forms**: input debounce 250ms, select inmediato, submit
  inmediato
- **Boton volver arriba**: floating fijo, no en cada panel, no requiere
  opt-in por template
- **Migracion de event handlers** a delegacion desde `document` (no
  desde containers) para que sobrevivan AJAX swaps

### Proximos bloques abiertos

#### Estrategico: primera app heredada del Template

Pendiente desde varios handoffs. Requiere conversacion previa con el
equipo: que app concreta vamos a clonar, que extensiones especificas
necesita, como se renombra el slug y los paths systemd/etc.

#### TLS interno para el server de dev (chico, opcional)

Firefox marca los `<input type="password">` como inseguros porque el
server corre HTTP plano en `10.x.x.x`. Solucion: Caddy con
`tls internal` reverse proxy. ~10 minutos. Solo cosmetic / silencia el
warning del browser.

#### Subcomando `ameli-app shell` (chico)

Hoy los scripts ad-hoc `python -c "..."` requieren
`AMELI_APP_ENV_FILE=...` explicito. Una opcion es agregar
`ameli-app shell` que arranque un Python con Django setup hecho y el env
file autodetectado (reutilizando `_effective_env_file()`).

#### Ideas tacticas (open backlog)

- Mas filtros en audit (rango de fechas con date inputs, filtro por
  payload key/value)
- Export CSV/JSON del audit filtrado
- Boton "Limpiar filtros" en cada toolbar paginado
- Persistir el page size elegido por el user (cookie / preferencia)

### Orden recomendado para retomar

1. **Resync local + servidor** al hash de `main` post-promocion del dia
2. **Validar visualmente** el boton "volver arriba" si quedaron
   pruebas pendientes
3. **Primera app real heredada** (estrategico, conversacion previa)
4. **TLS interno con Caddy** (chico, despeja el warning de Firefox)

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Servidor (resync sin migraciones, solo Python/JS/CSS/templates):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Servidor con migraciones o deps:

```bash
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
```

Tests con DB en SQLite:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

Smoke test SMTP directo:

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from django.core.mail import send_mail
from django.conf import settings
send_mail('AMELI smoke', 'body',
          settings.DEFAULT_FROM_EMAIL, ['destino@example.com'],
          fail_silently=False)
print('OK')
"
```

Seed para probar paginacion (30 demo users):

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from ameli_web.accounts.services import create_user_account
for i in range(30):
    create_user_account(actor_username='admin', username=f'demo-{i:02d}',
                        password='DemoPass!12?', role='public')
print('seeded')
"
```

Cleanup:

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from ameli_web.accounts.models import User
deleted, _ = User.objects.filter(username__startswith='demo-').delete()
print(f'cleaned: {deleted}')
"
```

### Archivos clave del cierre

- [`src/ameli_web/pagination.py`](../src/ameli_web/pagination.py) — helper reutilizable
- [`src/ameli_web/templates/_pagination_footer.html`](../src/ameli_web/templates/_pagination_footer.html) — footer parcial
- [`src/ameli_web/templates/accounts/_sessions_panel.html`](../src/ameli_web/templates/accounts/_sessions_panel.html)
- [`src/ameli_web/templates/admin/_users_panel.html`](../src/ameli_web/templates/admin/_users_panel.html)
- [`src/ameli_web/templates/admin/_audit_panel.html`](../src/ameli_web/templates/admin/_audit_panel.html)
- [`src/ameli_app/static/js/app.js`](../src/ameli_app/static/js/app.js) — AJAX swap + back-to-top
- [`src/ameli_app/static/css/app.css`](../src/ameli_app/static/css/app.css) — `.pagination-footer`, `.back-to-top`
- [`tests/test_pagination.py`](../tests/test_pagination.py) — 23 tests helper
- [`tests/test_profile_sessions_pagination.py`](../tests/test_profile_sessions_pagination.py) — 12 tests
- [`tests/test_admin_users_pagination.py`](../tests/test_admin_users_pagination.py) — 13 tests
- [`tests/test_admin_audit_pagination.py`](../tests/test_admin_audit_pagination.py) — 13 tests

### Conversacion completa del 2026-06-06

En orden:

1. Pre-flight del server: confirmacion de 211 tests verde post-cierre
   2026-06-05, CLI autodetect funcionando, SMTP O365 OK.
2. Discusion de patron de paginacion: Prev/Next + contador, mismo en
   los 3, filtros server-side en el mismo commit, foundation primero.
3. Commit 1 (helper): `paginate_queryset`, `paginate_list`,
   `Page.as_context`, `_pagination_footer.html`, CSS, 23 tests.
4. Commit 2 (profile sessions): `paginate_user_sessions`, view update,
   footer en el panel, 9 tests.
5. Bug visual: paginar volvia al tab General. Fix `ede9669` con hash
   anchor + sincronizacion JS.
6. Decision: agregar AJAX swap ahora antes de admin. Commit `2d9e6fd`
   con extraccion de partial + `swapPanelTo` + intercepcion de clicks
   de paginacion, history.pushState, fallback.
7. Commit 3 (admin users): `paginate_users_for_admin`, filter form,
   refactor JS del admin (delegacion desde document para sobrevivir
   swaps), extension de `app.js` para interceptar filter forms con
   debounce, 13 tests. Verificacion con 30 demo users seedeados +
   cleanup.
8. Commit 4 (admin audit): `paginate_audit_for_admin`, toolbar con 4
   filtros incluyendo outcome ok/error, hero stat usa total real, 13
   tests. Verificacion con 190 eventos reales.
9. Commit 5 (back-to-top): `setupBackToTop()` global en `app.js`, CSS
   responsive.
10. Este handoff.
