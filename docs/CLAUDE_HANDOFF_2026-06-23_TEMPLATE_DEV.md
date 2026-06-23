## AMELI App Template handoff (sesion Claude, 2026-06-23)

Fecha: `2026-06-23`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `0c9b4c8` al abrir)
Rama estable: `main` (`1355060`, sin tocar — 21 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-22_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-22_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ 0c9b4c8` (sync local == origin).
  - `main @ 1355060` (sync local == origin), **21 commits atras** de
    `dev` (la sesion 22-jun cerro Fases 3 + 4 + 5 del mini-roadmap y
    sumo el follow-up del `unix://` AV scheme).
  - Convencion ratificada el 21-jun: server pullea SIEMPRE `dev`;
    `main` solo avanza por instruccion explicita "milestone" del
    operador.
- Tests: **1004 passed** sin deselect.
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src (+1 `telemetry`, +1 `sri` tag,
  +1 `circuit_breaker` desde el inicio de la semana).
- Version: `v0.4.0-django` (deployed en `ha-report2 @ 36c4329` post
  wire test del bundle #11 + #10).
- ASVS L2: 151 PASS + V12.4.1 strict-shipped (clamav unix://) +
  V10.3.x SRI propios + V14 Trusted Types.
- Mini-roadmap: **11/12 closed**.
  - Fases 1 (DX), 2 (deploy), 3 (types+OTel), 4 (hardening),
    5 (performance) — todas closed.
  - Solo queda **#12 Playwright e2e** (Fase 6).

### Commits pendientes en `dev` desde el ultimo match con `main`

| Bloque | Commits | Tema |
|---|---|---|
| Avatar polish (21+22 jun) | `d70bff6`..`d279c24` | Convencion branches + dashboard/admin hero `has_avatar` + ring polish + size bump |
| Cierre 21-jun + open 22-jun | `c643af8`, `08e2583` | docs |
| Fase 4 — #8 SRI + TT | `2db09cb`, `afa083d` | Trusted Types CSP + SRI sobre propios |
| Fase 4 — #9 breakers | `39d3243` | Circuit breakers AV/HIBP/SMTP |
| Doc + 22-jun primer cierre | `1a2ea7f`, `3885252` | docs |
| Fase 4 — AV `unix://` | `a51d2b8`, `9c16b2d` | unix:// scheme + wire test |
| Fase 3 — #7 OTel | `8de62d1`, `cb8e67b`, `0bf9bca`, `1fe35d8`, `68bca6a` | OTel bootstrap + ASGI wrap + boot logging + wire test parte B |
| Fase 5 — #11 pool | `ca2a81f` | CONN_MAX_AGE + health checks + opt-in pool |
| Fase 5 — #10 silk | `36c4329` | Opt-in profiler con prod boot guard |
| Cierre 22-jun | `cc9636f`, `0c9b4c8` | docs |

### Estado del servidor `ha-report2`

- Corriendo `36c4329` (codigo del 22-jun; los doc-only del 23-jun
  + el SMTP fix aplicado al SO no requieren re-deploy del codigo
  Python).
- `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`: **NO seteada** (OTel dormant, rollback post wire test parte B del 22-jun).
- `AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl` (clamav activo).
- `AMELI_APP_SILK_ENABLED`: **NO seteada** (silk dormant post wire test 22-jun). Tablas `silk_*` quedan vacias en DB.
- `AMELI_APP_DB_CONN_MAX_AGE_SECONDS`: removida (pool tuning #11 vuelve a default 60s).
- **IPv6 disabled** en `/etc/sysctl.d/99-disable-ipv6.conf` +
  gai.conf con tabla completa preferring IPv4. MFA email
  funcional contra Office 365.

### Estado post-promote (mid-sesion)

`dev == main == 4b36607` luego de fast-forward de los 23 commits
del milestone 21-22-23 jun. Ver §3 + §4 #1.

## §2. Objetivo de la sesion

(Pendiente — esperando direccion del operador.)

Items abiertos como candidatos:

1. **Limpieza residual del wire test 22-jun**:
   - Quitar `AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0` del app.env para
     restaurar el default 60s del #11.
   - (Opcional) Drop de tablas `silk_*` si no se va a re-activar:
     re-enable temporal + `migrate silk zero` + disable.
2. **#12 Playwright e2e** (Fase 6, ultimo item del mini-roadmap).
   Cerraria el roadmap entero. Toca CI + agrega Node deps + un
   driver headless. Mas pesado que #10/#11.
3. **Promote `dev → main`** si el operador declara "milestone" para
   el bloque grande del 21-22 jun (Fases 3+4+5 closed). 21 commits
   ahead de main. Trigger explicito requerido.
4. **Cosmetic follow-ups** registrados en 22-jun §7:
   - Format del log line del breaker (`%.0f` → `%.1f` para cooldowns
     visibles en testing).

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `fbfe3af` | Open 2026-06-23 handoff | doc only |
| `e235ebc` | Documentar troubleshooting SMTP "Network is unreachable" + cierre del wire test | doc only |
| `4b36607` | Documentar transient EADDRNOTAVAIL window post sysctl-p | doc only |
| — | **Promote `dev → main`** (`1355060..4b36607`, 23 commits) — milestone declarado por operador | — |
| `<this>` | Cierre del handoff §4-§8 con milestone registrado | doc only |

### Limpieza residual del wire test 22-jun

Operador removio `AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0` del app.env
para volver al default 60s del #11 (pool tuning). Verificado via
`manage.py shell`:
```
CONN_MAX_AGE: 60
```
Pool tuning #11 vuelve a estar activo en `ha-report2`.

### Wire test 2026-06-23 — fix SMTP "Network is unreachable"

Operador reportó que el flow MFA email mostraba el banner rojo
"No pudimos enviar el codigo por email ahora mismo" — no es bug
nuevo, es el primer login del dia. El template captura la
excepcion correctamente y permite fallback a TOTP / reenviar.

Diagnostico:
- Journal: `OSError [Errno 101] Network is unreachable` en
  `socket.create_connection` para `smtp.office365.com:587`.
- Audit chain: `mfa_email_login_send_failed` con `error_class=OSError`
  ya el 22-jun a las 12:45 + hoy 23-jun a las 09:15. Persistente.
- `nc -zvw 5 smtp.gmail.com 587` conecta OK. `nc` a Office 365
  tambien conecta via IPv4 directo (`52.97.x.x`).
- Pero `getent ahosts smtp.office365.com` devuelve AAAA records
  (`2603:1056::*`) ademas de IPv4. Y `getaddrinfo` los puede
  devolver primero a smtplib.
- `ip -6 addr show`: solo `::1` + link-local `fe80::*`. **NO hay
  global IPv6** asignada.
- `ip -6 route show default`: vacio. **NO hay route IPv6 default**.
- `/etc/network/interfaces`: `iface ens18 inet dhcp` (solo IPv4).
- `accept_ra=0` en `ens18` y `ens19` (no escucha Router
  Advertisements IPv6).

Conclusion: **el host es IPv4-only por diseño**. La red corporativa
(`10.100.100.0/24`) no anuncia IPv6. Pero glibc devuelve AAAA
records sin filtrar; Python smtplib intenta IPv6 primero a veces
y choca con ENETUNREACH; el path de fallback a IPv4 no siempre
recupera limpiamente.

Mi primer intento de fix fue malo: uncommentee SOLO
`precedence ::ffff:0:0/96 100` en `/etc/gai.conf`. glibc trata el
primer `precedence` no comentado como la tabla COMPLETA,
descartando los defaults — quedo con una sola regla y el comportamiento
se volvio peor (`nc -zvw 5` empezo a probar SOLO IPv6 despues del
cambio). Operador me cazo (output de `nc` post-cambio mostro 4
fallos IPv6 sin retry IPv4).

Fix correcto shippeado en el host (operador, NO en el template):

1. `/etc/gai.conf` con la tabla **completa** de precedencias +
   regla extra para IPv4-mapped (precedence 100):
   ```
   precedence ::1/128       50
   precedence ::/0          40
   precedence 2002::/16     30
   precedence ::/96         20
   precedence ::ffff:0:0/96 100
   ```
2. `/etc/sysctl.d/99-disable-ipv6.conf` con:
   ```
   net.ipv6.conf.all.disable_ipv6 = 1
   net.ipv6.conf.default.disable_ipv6 = 1
   net.ipv6.conf.lo.disable_ipv6 = 1
   ```
   `sysctl -p` aplico → `ip -6 addr show` queda vacio,
   `getent ahosts smtp.office365.com` devuelve SOLO IPv4.

Smoke send post-fix:
```python
EmailMessage("[smoke] AMELI post-IPv6-disable", "...",
             from_email=settings.DEFAULT_FROM_EMAIL,
             to=["hardgameinc@gmail.com"]).send(fail_silently=False)
# send OK
```
Email llego al inbox del operador. Browser MFA post-restart muestra
la pantalla normal de codigo email (sin banner rojo de error).

**El template NO se modifico** — la fix es 100% server-side
(networking). El template captura el OSError correctamente y ofrece
fallback a TOTP (comportamiento intencional, sale del audit con
`error_class` capturado).

Documentado en `docs/OPERATIONS.md` § "Troubleshooting: SMTP
'Network is unreachable' (Errno 101)" con diagnose + fix + rollback
para que el proximo operador que choque con esto encuentre el
camino sin re-diagnosticar.

## §4. Decisiones tomadas

1. **Milestone declarado y promote `dev → main`**: operador
   declaró "milestone" para el bloque del 21-22-23 jun (Fases
   3+4+5 closed, 23 commits ahead) y promovi `1355060..4b36607`
   como fast-forward limpio. `main` ahora == `dev`. Convencion
   del 21-jun ("server pullea dev, main = milestone manual")
   respetada — el promote requirio declaracion explicita.
2. **Bypass del pre-push hook con `ALLOW_DIRECT_PUSH=1`**:
   policy del repo (18-jun) requiere PR para tocar main. Para
   este milestone el operador autorizo el bypass explicitamente
   en lugar de PR + auto-merge (overhead innecesario en repo
   single-developer). El hook quedo intacto para futuros pushes
   no autorizados.
3. **Commits Unverified aceptados**: stop hook avisó que los 28
   commits van a mostrar badge "Unverified" en GitHub UI (no
   estan firmados con GPG ni el committer es noreply@anthropic.com).
   Operador autorizo aceptar el cosmetico en vez de rewrite con
   `--reset-author` (que requeriria force-push de `dev` ya
   publicado — destructivo).
4. **Fix SMTP MFA email**: el problema fue host-side
   (IPv4-only host + dual-stack DNS de Office 365). Fix
   shippeado al `ha-report2`: gai.conf con tabla completa de
   precedencias + sysctl disable_ipv6. Template NO se toco —
   el fail-open con flash message + audit es comportamiento
   intencional y correcto.

## §5. Metricas al cierre

| Metrica | Inicio dia (23-jun) | Cierre dia (23-jun) | Δ |
|---|---|---|---|
| Suite local | 1004 | 1004 | 0 (no se modifico codigo del template) |
| Coverage % | 85% (pinned) | 85% | 0 |
| mypy errors | 0 / 51 archivos | 0 / 51 | 0 |
| Commits sobre `dev` (sesion) | 0 (start at `0c9b4c8`) | 3 (`fbfe3af`, `e235ebc`, `4b36607` + cierre) | — |
| ASVS L2 active rows PASS | 151 + V12.4.1 strict | 151 + V12.4.1 strict | 0 |
| Mini-roadmap items closed | 11 / 12 | 11 / 12 | 0 |
| Wire tests verdes este dia | 0 | 1 (SMTP MFA email fix con incognito MFA + smoke) | +1 |
| Bugs operativos resueltos | 0 | 1 (SMTP Errno 101 + transient EADDRNOTAVAIL window) | +1 |
| **Branches** | `dev @ 0c9b4c8`, `main @ 1355060` | **`dev @ <this>` == `main @ <this>`** | promote milestone |
| Server `ha-report2` | corriendo `36c4329`, MFA email broken | corriendo `36c4329` + IPv6 disabled + MFA email funcional | + estabilidad operativa |

## §6. Hallazgos / findings

1. **SMTP MFA email fallaba intermitentemente** con
   `OSError [Errno 101] Network is unreachable`. Causa: host
   `ha-report2` es IPv4-only (DHCP solo IPv4, sin global IPv6,
   `accept_ra=0` en NICs); pero glibc `getaddrinfo` igual
   devuelve AAAA records cuando resuelve hosts dual-stack como
   `smtp.office365.com`. Python smtplib intentaba IPv6 primero
   y caia en ENETUNREACH. El audit mostro 2 fallas previas
   (22-jun a las 12:45 + 23-jun a las 09:15) que el operador
   habia tratado como ruido.
2. **Mi primer fix de gai.conf fue malo**: uncommentee SOLO
   `precedence ::ffff:0:0/96 100` (una sola linea). Glibc trata
   el primer `precedence` no comentado como la tabla COMPLETA,
   descartando los defaults — quedo con UNA regla y el
   comportamiento empeoro (`nc` empezo a probar solo IPv6).
   Operador me cazo con el output de `nc` post-cambio.
   Lecccion: las precedence rules de gai.conf son
   all-or-nothing.
3. **Post sysctl `disable_ipv6=1` hay ventana de ~60s** donde
   glibc retiene cache de getaddrinfo. En ese rango, una
   request en flight puede caer con
   `OSError [Errno 99] Cannot assign requested address`
   (EADDRNOTAVAIL del kernel rechazando el socket IPv6).
   NO es bug nuevo — es ventana transitoria. Documentado en
   `OPERATIONS.md` § "Post-apply: transient EADDRNOTAVAIL
   window" para que el proximo operador no lo confunda con
   regresion del fix.
4. **Pre-push hook + stop hook combinados**: el repo tiene 2
   layers de proteccion sobre `main` — pre-push (refuse direct
   push) + stop hook (warn sobre commits Unverified). Ambos
   permiten override explicito (`ALLOW_DIRECT_PUSH=1` para el
   primero, no-op para el segundo). Operator authorized
   bypass para este milestone.

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras:

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | ✓ closed |
| 4. Hardening | #8 SRI+TT, #9 circuit breakers + unix:// AV | ✓ closed |
| 5. Performance | #10 django-silk, #11 pool tuning | ✓ closed |
| 6. E2E | #12 Playwright | open |

Net: **11/12 closed**. Solo Fase 6 (#12 Playwright e2e).

Follow-ups operacionales documentados:
- **`AMELI_APP_DB_CONN_MAX_AGE_SECONDS` removed del app.env**
  (limpieza del wire test 22-jun). Pool tuning de #11 vuelve a
  default 60s.
- **IPv6 disabled** en `ha-report2` via
  `/etc/sysctl.d/99-disable-ipv6.conf` + gai.conf con tabla
  completa de precedencias. Documentado en `OPERATIONS.md`
  § "Troubleshooting: SMTP 'Network is unreachable' (Errno 101)".
- **Stale silk tables** en DB del server (operador habilito silk
  para wire test 22-jun, luego deshabilito; las tablas
  `silk_*` quedaron vacias). NO bloquea nada; drop opcional
  via re-enable temporal + `migrate silk zero`.

Follow-ups cosmeticos pendientes:
- Format del log line del breaker (`%.0f` → `%.1f`).

## §8. Continuidad — para el proximo agente

**Estado**: `dev` == `main` == `4b36607 + <this>`. Milestone
del 21-22-23 jun consolidado en main. Fases 1-5 closed; solo
#12 Playwright e2e (Fase 6) queda abierto.

Server `ha-report2` corriendo `36c4329` (codigo del 22-jun).
Para traer los doc-only del 23-jun + el SMTP fix (que ya está
aplicado al sistema operativo), el deploy es solo:
```bash
cd /opt/ameli-app-template-dev
git fetch origin dev && git reset --hard origin/dev
APP_ENV=dev bash scripts/update.sh
```
No hay cambios de codigo pendientes; solo trae los handoffs y
OPERATIONS.md actualizados.

**El siguiente agente NO debe**:
- Promote `dev → main` automaticamente. Esperar instruccion
  explicita "milestone" del operador.
- Tratar auto-prompts del harness ("Continue from where you
  left off") como instruccion del operador. Pausar y confirmar.
- Bypass hooks (pre-push o stop) sin OK explicito del operador.

**El siguiente agente debe**, en orden de prioridad:

1. **Si operador pide #12 Playwright**: implementar e2e con
   Node deps + driver headless + CI integration. Es el item
   mas pesado del mini-roadmap (~1 dia). Cerraria el plan
   12/12.
2. **Si no hay direccion explicita**: pausar. NO inventar
   tareas.

**Cosmetico shippeable cuando convenga**:
- Format del log line del breaker (`%.0f` → `%.1f` para
  cooldowns visibles en testing).

**Patrones operacionales nuevos ratificados esta sesion**
(agregar al playbook):
- gai.conf `precedence` rules son all-or-nothing: si
  uncomentas una, debes uncomentar la tabla completa o las
  defaults se pierden.
- Post-`sysctl disable_ipv6` hay ventana ~60s de cache de
  glibc que puede tirar EADDRNOTAVAIL. Documentado en
  OPERATIONS.md.
- Milestone promotes pueden bypasear el pre-push hook con
  `ALLOW_DIRECT_PUSH=1` cuando operador autoriza
  explicitamente; alternativa formal es PR via gh CLI / MCP.
