## AMELI App Template handoff (sesion Claude, 2026-06-07)

Fecha: `2026-06-07`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-06_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-06_TEMPLATE_DEV.md).

Cierra mejoras operativas del audit log (filtros de fecha + export
CSV/JSON streaming) y persistencia por panel del page size elegido por
el operador via cookie.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **298 tests pasando** (`pytest -v`)
- **0 regresiones**
- Verificado end-to-end visual: date pickers funcionando, export CSV y
  JSON descargando archivos con los headers y body esperados (incluyendo
  rangos invalidos que devuelven payload vacio correcto), selector
  10/20/50/100 modificando el page size con URL `?<panel>_per_page=N`,
  cookie persistiendo entre requests

### Contexto al arrancar

El cierre del 2026-06-06 dejo el bloque de paginacion 100% cerrado y el
backlog operativo abierto. El usuario eligio combinar dos items
tacticos medianos (filtros de fecha + export del audit) con un item
chico de DX (persistir page size). La validacion visual del boton
"volver arriba" tambien quedo confirmada al inicio de la sesion.

### Pre-flight (validacion del bloque anterior)

- Server resync al `503d6ec` post-promocion 2026-06-06.
- **Botón "volver arriba"** validado visualmente en `/admin/` (visible
  al hacer scroll), `/profile/` (visible), `/login/` (oculto, contenido
  corto), responsive viewport 436px (colapsa a solo icono).
- 272 tests verde en Python 3.13.

### Bloque audit + page size: 3 commits

| Commit | Item |
|---|---|
| `b383556` | filtros de fecha en audit (from/to) + helper queryset reusable |
| `d825787` | export CSV/JSON streaming del audit filtrado |
| `e6f4f32` | persistir page size por panel via cookie + selector en footer |

#### `b383556` — Filtros de fecha en audit

Refactor del service que extrae la logica de filtros a un helper
reusable:

- Nuevo helper privado `_audit_queryset_for_filters(...)` que recibe
  `actor`, `target`, `action`, `outcome` + nuevos `date_from`, `date_to`
  (strings ISO `YYYY-MM-DD`) y devuelve el QuerySet filtrado
- `paginate_audit_for_admin(...)` ahora delega a ese helper
- Nuevo wrapper publico `filtered_audit_queryset(...)` que el endpoint
  de export reutiliza para garantizar identidad de filtros
- Fechas invalidas (parseo falla) se ignoran silenciosamente (no 500)
- `date_from` mapea a `created_at__gte` (00:00:00 timezone-aware)
- `date_to` mapea a `created_at__lte` (23:59:59 timezone-aware)

Template:

- Dos `<input type="date">` agregados al toolbar del audit
  (`audit_date_from`, `audit_date_to`)
- Valores precargados desde `audit_filters` para que sobrevivan al
  refresh

View:

- `admin_panel` lee `audit_date_from` / `audit_date_to` del request y
  los pasa al service como dos campos mas del dict de filtros

El JS de paginacion ya escuchaba `input` events sobre `HTMLInputElement`
asi que los date inputs disparan AJAX swap automatico sin tocar codigo
de cliente.

**5 tests** nuevos (date_from / date_to / invalid date silently ignored
/ combined filters / inputs render).

#### `d825787` — Export CSV/JSON

Endpoint nuevo `/admin/audit/export/?format=<csv|json>&<filters>` que
respeta exactamente los mismos filtros que el panel.

Implementacion:

- Uses `StreamingHttpResponse` con generators (`_iter_audit_csv_rows`,
  `_iter_audit_json_rows`) y `queryset.iterator(chunk_size=200)` para
  evitar cargar todo el log en memoria
- CSV columns: `id, created_at, actor_username, target_username,
  action, display_result_label, payload`
- Payload se serializa con `json.dumps(..., ensure_ascii=False,
  sort_keys=True)` en la celda CSV
- JSON output: array unico, items con la misma forma del CSV pero como
  diccionario
- Content-Disposition fuerza descarga: `audit.csv` o `audit.json`
- Reutiliza `filtered_audit_queryset()` del commit anterior (los
  filtros del panel y del export tienen identidad garantizada por
  construccion)

Template: dos botones nuevos arriba del listado, "Exportar CSV" y
"Exportar JSON". Sus href se reconstruye preservando todos los filtros
actuales pero sin `partial` ni `audit_page` (para que el export incluya
todo el set filtrado, no solo la pagina visible).

**8 tests** nuevos (auth required / non-admin rejected / CSV default
format / JSON format / actor filter respected / outcome filter
respected / empty filter / buttons render).

#### `e6f4f32` — Persistir page size

Tres niveles de resolucion para cada panel:

1. Query string explicito (`?<panel>_per_page=N`) — gana siempre
2. Cookie persistida (`ps_<panel>_per_page=N`) — fallback
3. Default hardcodeado por panel (20/25/30) — ultimo fallback

Helpers nuevos en `pagination.py`:

- `PAGE_SIZE_CHOICES = (10, 20, 50, 100)`
- `resolve_per_page(request, cookie_name, *, default, query_param)`:
  implementa la precedencia, clampea con `coerce_per_page` (max 200)
- `persist_per_page_cookie(response, request, cookie_name, *,
  query_param)`: si el request trae el query param explicito, escribe
  la cookie con `max_age=1 año, SameSite=Lax`. No-op si no hay query
  explicito (no re-escribe la cookie en bookmarks/shares).
- `Page.as_context(...)` ahora acepta `per_page_param` opcional; cuando
  esta presente el footer renderiza el selector

Views (`profile_view`, `admin_panel`):

- Usan `resolve_per_page` para determinar el size efectivo
- Pasan `per_page_param` al `as_context()`
- Llaman `persist_per_page_cookie` justo antes de retornar la response

Template (`_pagination_footer.html`):

- Cuando `pagination.per_page_param` esta presente, renderiza:
  `Mostrar: <select data-page-size data-per-page-param="...">` con
  options de `PAGE_SIZE_CHOICES`

JS (`app.js`):

- Helper `buildPageSizeUrl(select, panel)` que construye la URL nueva
  preservando todos los query params, agrega el `<panel>_per_page=N`
  nuevo, y resetea el `<panel>_page` para no apuntar a una pagina
  inexistente con el size nuevo
- Nuevo listener de `change` que matchea `[data-page-size]` y dispara
  `swapPanelTo(panel, buildPageSizeUrl(...))`

Cookies usadas:

- `ps_sessions_per_page` (profile)
- `ps_users_per_page` (admin)
- `ps_audit_per_page` (admin)

Las tres son independientes. Cambiar el tamaño de uno **no afecta** los
otros (verificado por test
`test_admin_panel_per_page_cookies_are_independent`).

**13 tests** nuevos (resolve precedence / clamp / cookie persistence /
independent cookies per panel / select rendered).

### Decisiones tomadas (no re-discutirlas)

- **Patron uniforme** para los 3 listados (mismas keys, mismo flujo)
- **Cookie por panel** en lugar de campo en User model:
  - Cero migraciones, cero UI adicional
  - Cambia por browser (no sincroniza entre devices); aceptable para
    una preferencia operativa
- **Export streaming** con `iterator(chunk_size=200)` para escalar a
  audit logs grandes sin agotar memoria
- **Filtros identicos panel/export**: misma funcion
  `filtered_audit_queryset` consumida por ambos. El operador filtra,
  ve el subset en el panel, exporta exactamente eso.
- **`payload` en CSV serializado a JSON inline** (no flatten a
  columnas) porque el shape varia por accion
- **`date_to` incluye el dia completo** (23:59:59) para que el rango
  sea inclusivo de fechas en lenguaje natural
- **Cookie max_age 1 año + SameSite=Lax** balancea persistencia razonable
  con seguridad (no se manda en cross-site requests)
- **No-op cuando el request no trae el query explicito**: previene
  que un bookmark sin `?_per_page=N` resetee el cookie del user

### Numeros del dia

- 3 commits promocionados a `main`
- **298 tests pasando** (272 al inicio → 298 al cierre, +26 tests)
- 3 archivos nuevos:
  - `tests/test_admin_audit_export.py` (8 tests)
  - `tests/test_page_size_persistence.py` (13 tests)
  - (los 5 tests de date filters se agregaron al archivo existente)
- ~700 lineas netas agregadas
- 0 migraciones nuevas
- 0 deps nuevas (csv + json son stdlib)

### Snapshot del Template al cierre

| Frente | Cobertura |
|---|---|
| Profile sessions | paginadas con AJAX swap + **page size persistente** |
| Admin users | paginados + filtros server-side + **page size persistente** |
| Admin audit | paginado + filtros + **fechas + export CSV/JSON + page size persistente** |
| Back to top | floating button global > 400px scroll |
| Tests | **298** (pytest -v), Python 3.13 / Django 6.0.5 verificado |

### Proximos bloques abiertos

#### Estrategico: primera app heredada del Template

Sigue pendiente desde varios handoffs. Requiere conversacion previa con
el equipo: que app concreta vamos a clonar, que extensiones especificas
necesita, como se renombra el slug y los paths systemd/etc.

#### Tacticos chicos disponibles

- TLS interno con Caddy (silencia warning de Firefox sobre formularios
  inseguros)
- Subcomando `ameli-app shell` (autodetect del env para scripts ad-hoc)
- Boton "Limpiar filtros" en cada toolbar paginado
- Mas filtros en audit (search por payload key/value, filtros por dia
  especifico)

### Orden recomendado para retomar

1. Resync local + servidor al hash de `main` post-promocion del dia
2. Empezar la **primera app real** si hay claridad sobre que app va,
   o bien sumar tacticos chicos mientras se planea
3. TLS Caddy si el warning de Firefox empieza a molestar

### Comandos utiles de continuidad

Server resync:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Tests:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

Smoke export audit (con autenticacion via curl):

```bash
# 1) Login y guardar cookies
curl -c /tmp/ck -b /tmp/ck -L \
    -d "username=admin&password=...&csrfmiddlewaretoken=..." \
    http://127.0.0.1:18080/login/

# 2) Export filtrado
curl -b /tmp/ck \
    "http://127.0.0.1:18080/admin/audit/export/?audit_actor=admin&format=csv" \
    -o audit.csv
```

### Archivos clave del cierre

- [`src/ameli_web/pagination.py`](../src/ameli_web/pagination.py) — `resolve_per_page` + `persist_per_page_cookie` + `PAGE_SIZE_CHOICES`
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `_audit_queryset_for_filters` + `filtered_audit_queryset`
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — `admin_audit_export` + lectura de cookie/query en `admin_panel`
- [`src/ameli_web/templates/_pagination_footer.html`](../src/ameli_web/templates/_pagination_footer.html) — selector page size
- [`src/ameli_web/templates/admin/_audit_panel.html`](../src/ameli_web/templates/admin/_audit_panel.html) — date inputs + export buttons
- [`src/ameli_app/static/js/app.js`](../src/ameli_app/static/js/app.js) — handler para `[data-page-size]`
- [`tests/test_admin_audit_pagination.py`](../tests/test_admin_audit_pagination.py) — +5 tests de fechas
- [`tests/test_admin_audit_export.py`](../tests/test_admin_audit_export.py) — 8 tests del export
- [`tests/test_page_size_persistence.py`](../tests/test_page_size_persistence.py) — 13 tests de page size

### Conversacion completa del 2026-06-07

En orden:

1. Validacion del cierre 2026-06-06: boton "volver arriba" verificado
   visualmente en server.
2. Decision del usuario: combinar audit (fechas + export) + persistir
   page size (en lugar del bloque estrategico de primera app real).
3. Commit 1 (filtros de fecha): refactor del service a helper
   reusable, date inputs en toolbar, 5 tests.
4. Commit 2 (export): endpoint streaming con CSV/JSON, botones en
   toolbar, 8 tests, fix del scope (filtrar por seed-action especifica
   para no contaminar con audit del bootstrap/login).
5. Commit 3 (page size): helpers, footer selector,
   cookie por panel, 13 tests.
6. Verificacion E2E en server: 21 + 298 tests verde, screenshots de
   date pickers / export descargado / selector funcionando con 50 y
   100 / paginas recalculadas correctamente (219 events / 50 = 5 pags,
   / 100 = 3 pags).
7. Este handoff.
