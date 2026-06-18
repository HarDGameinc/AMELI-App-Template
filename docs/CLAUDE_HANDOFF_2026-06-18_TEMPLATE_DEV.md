## AMELI App Template handoff (sesion Claude, 2026-06-18)

Fecha: `2026-06-18`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del fix CI)
Rama estable: `main` (en `8bde7c0`; rezagada por CI rojo del dia previo)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-17_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-17_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `dev @ aa869be`, `main @ 8bde7c0`.
- Tests: 837 passed / 1 failed (CI rojo cronico desde `a1fe164`).
  El test que rompia era
  `tests/test_admin_audit_pagination.py:244
  test_filtered_audit_queryset_respects_combined_filters`. Mi
  diagnostico previo "es TZ flake" era incorrecto.
- ASVS L2: **150 PASS / 0 strict-tracked GAP** — bucket S del
  roadmap cerrado completo en sesion previa.
- Frente abierto al cierre de ayer (§8 del handoff 17-jun, orden
  estricto): (1) fix CI rojo, (2) promote dev→main, (3) #14
  lockfile con hashes.

## §2. Objetivo de la sesion

Resolver la primera prioridad del §8 del 2026-06-17 — el test
flaky que tiene CI rojo desde hace 8 runs consecutivos —
desbloquear la promocion a `main`, y arrancar #14 V14.2.3
(lockfile con hashes) si queda budget. Mantener disciplina:
NO promover a main hasta ver el run verde post-fix.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `<this>` | Fix CI rojo — test combined-filters TZ-stable | 837 → 838 (+1 cubierto, suite verde sin deselect) |

### Fix CI rojo — root cause distinto al diagnosticado ayer

**Lo que dije ayer**: "test-state isolation rota, agregar
`AuditEvent.objects.all().delete()` en setUp".

**Lo que es en realidad**: time-of-day-dependent, no
state-leak. El test pedia `date_to=yesterday` (calculado como
`(timezone.now() - timedelta(days=1)).date().isoformat()`). En
CI:

| Variable | Valor en run #71 |
|---|---|
| `TIME_ZONE` Django | `America/Santiago` (UTC-3/-4) |
| OS de CI | UTC |
| Hora del run | `2026-06-18T02:30:51Z` = `2026-06-17 22:30:51` Santiago |
| `yesterday` calculado (UTC date) | `"2026-06-17"` |
| Filtro: `make_aware("2026-06-17 23:59:59", TIME_ZONE=Santiago)` | `2026-06-18 02:59:59 UTC` |
| Eventos seedeados a `timezone.now()` (02:30 UTC) | < `02:59:59 UTC` → **incluidos por error** |

Ventana de falla: cuando UTC esta entre 00:00 y 03:00 (~3h al
dia), el `yesterday 23:59:59 Santiago` cae DENTRO del "hoy" UTC
y los eventos seedeados a `timezone.now()` pasan el filtro
cuando no deberian.

Fix: cambiar el cutoff a 7 dias atras — fuera de la ventana
ambigua sin importar la hora del wall-clock. La intencion del
test es validar la composicion de filtros (`action` AND `date_to`),
no la frontera exacta del corte de fecha; el cutoff lejano
mantiene la semantica pero hace el test deterministico.

```python
cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
queryset = filtered_audit_queryset(action="login", date_to=cutoff)
```

### Leccion incorporada — diagnostico de CI rojo

Ayer asumi "es flake TZ" sin abrir un solo log de CI. La causa
real estuvo a un `mcp__github__get_job_logs` de distancia, e
incluso DESPUES de tener el log seguia diciendo "test-state
isolation" porque no calcule el shift TZ en la cabeza. **Regla
nueva**: antes de afirmar la naturaleza de un flake, abrir el
log del runner Y reproducir la asercion ofensora con sus
valores numericos. Sin eso, cualquier hipotesis es especulacion.
Esta leccion se agrega al S-04 / S-07 del playbook en la
siguiente promocion.

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Heredado del 2026-06-17 §7. Items que arranca el dia abiertos:

- **#14 V14.2.3** Lockfile con hashes (M, ~1h).
- Operacionales: #16, #18, #19, #20, #23.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
