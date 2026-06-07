## AMELI App Template handoff (sesion Claude, 2026-06-08)

Fecha: `2026-06-08`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-07_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-07_TEMPLATE_DEV.md).

Cierra el frente de mejoras tacticas del audit log (4 commits chicos a
medianos) y deja abierta la discusion estrategica de multi-tenancy.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **321 tests pasando** (`pytest -v`)
- **0 regresiones**
- Audit log completo: filtros por actor / target / action / outcome /
  fechas / payload + presets de fecha + export CSV/JSON + limpiar
  filtros con un click

### Contexto al arrancar

El cierre del 2026-06-07 dejo el backlog operativo con 4 tacticos
chicos + el bloque estrategico de multi-tenancy. El usuario pidio una
explicacion concreta de items 2 (shell), 3 (limpiar filtros) y 4
(filtros adicionales en audit), mas un panorama de como integrar
multi-tenancy. La conversacion incluyo las 3 estrategias clasicas
(shared DB filter-based / schema-per-tenant / DB-per-tenant) con sus
tradeoffs. La decision fue cerrar primero el bloque tactico (items 2 +
3 + 4 completo, incluyendo payload search) y dejar multi-tenancy para
un bloque posterior con conversacion de diseno previa.

### Bloque tacticos + audit completo: 4 commits

| Commit | Item |
|---|---|
| `28b21b7` | `ameli-app shell` subcommand con bootstrap Django |
| `d027195` | Boton "Limpiar filtros" en users y audit con AJAX swap |
| `784d27d` | Presets de rango de fechas en audit (Hoy / Ayer / 7 / 30) |
| `4d4bc7a` | Filtro por substring en payload (portable Postgres + SQLite) |

#### `28b21b7` — `ameli-app shell`

Nuevo subcomando con 3 modos:

- Interactivo: `ameli-app shell` arranca un Python con Django setup y
  un namespace pre-poblado (`User`, `AuditEvent`, `UserSession`,
  `MFAEmailChallenge`, `MFARecoveryCode`, `settings`, `connection`)
- Snippet: `ameli-app shell -c "User.objects.count()"` ejecuta una
  linea inline
- Script: `ameli-app shell path/to/script.py` ejecuta un archivo

Aprovecha el `_effective_env_file()` que ya tenemos para autodetectar
`/etc/<slug>-<env>/app.env` cuando se corre desde `/opt/<slug>-<env>/`.

Bug subtle resuelto en el camino: el parent parser usaba `dest="command"`
para el subcomando, asi que `-c/--command` interno colisionaba. Renombre
a `--snippet` (`-c` queda como alias corto) usando `dest="shell_snippet"`.

**6 tests** (snippet ok / namespace tiene los modelos / errores se
propagan / script archivo ok / script missing devuelve 2 / namespace
completo).

#### `d027195` — Limpiar filtros

Link nuevo `<a data-clear-filters>` en los toolbars de users y audit:

- Visible solo cuando hay al menos 1 filtro activo
- Su href reconstruye la URL actual quitando los params del panel
  correspondiente (`users_*` o `audit_*`) pero preservando los del
  panel hermano (asi limpiar users no rompe el estado de audit)
- Usa el mismo AJAX swap que la paginacion — sin recarga completa

JS: extendi el handler para que matchee
`.pagination-footer a, [data-clear-filters]` en el mismo
`closest()`. Cualquier link nuevo que quiera ese comportamiento solo
agrega el atributo.

**7 tests** (visibilidad condicional / drop de params propios /
preservacion de params del otro panel / audit version).

#### `784d27d` — Presets de fecha

4 botones nuevos arriba de los inputs de fecha en audit:

- Hoy / Ayer / 7 dias / 30 dias
- Click → setea ambos inputs a las fechas correspondientes y dispara
  `input` events para que el handler debounced de filter-form re-fetch
  el panel
- ISO `YYYY-MM-DD` para que el parser del backend acepte sin tocar

CSS chico (`.audit-date-presets`) para botones compactos en linea con
los inputs.

**2 tests** (botones renderizan / inputs tienen los data-hooks).

#### `4d4bc7a` — Payload search

Filtro nuevo `payload` en `_audit_queryset_for_filters`:

- Cast del `JSONField` a `TextField` con `Cast` annotation
- `__icontains` sobre el texto resultante
- Funciona identico en Postgres y SQLite (mismo SQL plan, mismo
  resultado)
- En Postgres a escala se podria mejorar con un GIN index sobre la
  columna JSON, pero el icontains baseline es suficiente para el caso
  operativo tipico

Toolbar: input nuevo "Payload contiene..." con `name="audit_payload"`.

Tambien actualice:

- El "Limpiar filtros" para que tambien drop el `audit_payload` param
- El export (`_audit_export_filters`) para que respete el nuevo filtro
- `filtered_audit_queryset` y `paginate_audit_for_admin` con el nuevo
  kwarg

**8 tests** (substring / case insensitive / matchea keys y values /
empty ignored / combina con otros filtros / input render / e2e via
view / clear filters drop).

### Snapshot audit log al cierre

| Filtro | Origen | Notas |
|---|---|---|
| Actor | `audit_actor` | icontains substring |
| Objetivo | `audit_target` | icontains substring |
| Accion | `audit_action` | icontains substring |
| Resultado | `audit_outcome` | OK / Errores (basado en `_failed` suffix) |
| Desde | `audit_date_from` | ISO `YYYY-MM-DD`, gte (00:00:00) |
| Hasta | `audit_date_to` | ISO `YYYY-MM-DD`, lte (23:59:59) |
| Payload contiene | `audit_payload` | Cast a text + icontains (PG/SQLite) |

UX extras:

- Botones de preset (Hoy / Ayer / 7d / 30d) que setean los date inputs
- Boton "Limpiar filtros" cuando hay al menos uno activo
- Botones de Export CSV / JSON que respetan los filtros activos
- Selector "Mostrar: 10/20/50/100" persistido por cookie

### Decisiones tomadas (no re-discutirlas)

- **`-c` corto + `--snippet` largo** en lugar de `--command` para
  evitar la colision con el `dest` del subparser parent
- **Cast a text** en payload search (cross-DB) en lugar de SQL especifico
  por motor. Ganamos portabilidad, perdemos un poco de performance en
  Postgres (asumible)
- **Presets de fecha como botones** en lugar de un dropdown (mas
  visibles + 1 click) — operativamente preferible
- **Limpiar filtros como link AJAX** y no boton de form reset porque el
  reset de form no notifica la swap helper
- **Cada panel limpia solo sus propios filtros** — el panel hermano
  preserva estado

### Numeros del dia

- 4 commits promocionados a `main`
- **321 tests pasando** (298 al inicio → 321 al cierre, +23 tests)
- 4 archivos de tests nuevos
- ~500 lineas netas agregadas
- 0 migraciones nuevas
- 0 deps nuevas

### Discusion estrategica de multi-tenancy (pendiente)

Tres opciones evaluadas:

| Opcion | Aislamiento | Costo operativo | Ideal para |
|---|---|---|---|
| **A. Shared DB filter-based** | FK + middleware | Bajo (1 DB) | SaaS chico-medio, mismo dueno |
| **B. Schema-per-tenant** | Schema Postgres | Medio (migraciones x N) | 10-200 tenants, Postgres |
| **C. DB-per-tenant** | DB separada | Alto (DBs x N) | Compliance / tenants premium |

Recomendacion para AMELI: **Opcion A** porque son "areas operativas"
del mismo grupo (Metro, Notifier, etc.) y no SaaS externo. Plan
tentativo de 8 commits si se aprueba:

1. Modelo `Tenant` + migracion + panel `/global-admin/`
2. FK `tenant` en User + backfill (default tenant para users existentes)
3. `TenantMiddleware` con resolucion por path-prefix `/t/<slug>/`
4. Refactor de URLs operativas bajo `/t/<slug>/`
5. FK `tenant` en AuditEvent / UserSession / MFA*
6. Querysets default-scoped a `request.tenant`
7. Panel `/global-admin/` para superadmins globales
8. Selector de tenant en header

**Tamaño**: 2-3 dias concentrados. Requiere conversacion previa con el
equipo: que tenants concretos vamos a tener, branding por tenant si/no,
roles globales.

### Proximos bloques abiertos

- **Multi-tenancy** (estrategico, ver arriba)
- **TLS interno con Caddy** (chico, silencia warning Firefox)
- **Primera app real heredada** (estrategico)

### Orden recomendado para retomar

1. Resync local + servidor al hash de `main` post-promocion del dia
2. Conversacion de diseno multi-tenancy con el equipo
3. Decidir entre arrancar multi-tenancy O cerrar TLS Caddy primero

### Comandos utiles de continuidad

Server resync:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Nuevo: shell interactivo de Django:

```bash
.venv/bin/ameli-app shell
# >>> User.objects.count()
# >>> AuditEvent.objects.filter(action__contains="login").count()
```

Nuevo: snippet inline (reemplaza los `python -c "..."` ad-hoc):

```bash
.venv/bin/ameli-app shell -c "print(User.objects.filter(is_active=True).count())"
```

Nuevo: script archivo:

```bash
.venv/bin/ameli-app shell scripts/cleanup_demo_users.py
```

Tests:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

### Archivos clave del cierre

- [`src/ameli_app/cli.py`](../src/ameli_app/cli.py) — `_handle_shell`, `_shell_namespace`
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `payload` kwarg en `_audit_queryset_for_filters`
- [`src/ameli_web/templates/admin/_users_panel.html`](../src/ameli_web/templates/admin/_users_panel.html) — link clear filters
- [`src/ameli_web/templates/admin/_audit_panel.html`](../src/ameli_web/templates/admin/_audit_panel.html) — presets + payload + clear filters
- [`src/ameli_app/static/js/app.js`](../src/ameli_app/static/js/app.js) — `setupAuditDatePresets`, clear filter selector
- [`tests/test_cli_shell.py`](../tests/test_cli_shell.py) — 6 tests
- [`tests/test_clear_filters.py`](../tests/test_clear_filters.py) — 7 tests
- [`tests/test_audit_date_presets.py`](../tests/test_audit_date_presets.py) — 2 tests
- [`tests/test_audit_payload_search.py`](../tests/test_audit_payload_search.py) — 8 tests

### Conversacion completa del 2026-06-08

En orden:

1. Pregunta del usuario: revisar items 2 + 3 + 4 + integrar multi-tenant.
2. Respuesta tecnica detallada de cada item + panorama de las 3
   opciones de multi-tenancy con tradeoffs y plan tentativo para
   Opcion A.
3. Decision: cerrar tacticos + audit completo, multi-tenancy queda
   para conversacion de diseno previa.
4. Commit 1 (shell): subcomando + fix de la colision `dest="command"`.
5. Commit 2 (clear filters): link AJAX + extension del selector.
6. Commit 3 (date presets): botones + JS handler.
7. Commit 4 (payload search): Cast cross-DB + actualizacion de todas
   las superficies que tocan filtros.
8. Este handoff.
