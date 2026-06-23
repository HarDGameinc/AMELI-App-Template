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

- Corriendo `36c4329`.
- `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`: **NO seteada** (OTel dormant, rollback post wire test parte B).
- `AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl` (clamav activo).
- `AMELI_APP_SILK_ENABLED`: **NO seteada** (silk dormant post wire test). Tablas `silk_*` quedan vacias en DB (no graban porque silk salio de INSTALLED_APPS).
- `AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0` ← residuo del test del rollback path. **Vale la pena confirmar con operador si lo mantiene o lo quita** para volver al default 60s. Mientras este seteado, pool tuning #11 esta efectivamente OFF (per-request connections, comportamiento Django original).

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
| `<this>` | Documentar troubleshooting SMTP "Network is unreachable" + cierre del wire test | doc only |

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

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

(Pendiente al cierre del dia.)

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
