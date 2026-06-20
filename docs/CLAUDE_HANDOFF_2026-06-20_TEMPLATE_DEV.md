## AMELI App Template handoff (sesion Claude, 2026-06-20)

Fecha: `2026-06-20`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit que abre la sesion)
Rama estable: `main` (pendiente promote desde `dev @ af6667e`)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-19_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-19_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `dev @ af6667e`, `main @ 67ae53a` (8 commits
  detras de dev, pendiente promote — ver §8 del 19-jun).
- Tests: **898 passed** sin deselect. CI verde sobre `d785518`
  (ultimo cambio de seguridad pre-handoff-close).
- Version: `v0.3.1-django` (bumped 18-jun para los 3 fixes
  materiales — throttle ceil + slug autodetect + pg_url
  normalizer + boot guards AUDIT/AV).
- ASVS L2: **151 PASS / 0 strict-tracked GAP**. 2 GAPs
  documentadas como `GAP-accepted` (V11.1.5 R-09, V13.1.5 R-10).
- Sprint 2026-06-15..06-19 cerrado: roadmap 100%, 6 wire tests
  verdes, 5 bugs latentes encontrados via wire test + auditor
  independiente.
- Frente abierto del 19-jun §8: PT-pendientes operativas
  (verificar backup automatico 04:11, promote dev→main, hook
  en Windows). Plus el operador pidio un analisis de
  oportunidades de mejora post-sprint — vive abajo.

## §2. Objetivo de la sesion

Mini-roadmap de mejoras propuesto al cierre del 19-jun. El
operador aprobo ver el orden con dependencias. Sin desarrollo
arrancado todavia — cuando el operador autorice un bucket,
seguimos.

### Mini-roadmap de mejoras post-sprint (ordenado por ROI)

Categoria: **DX** = developer experience, **OPS** = operaciones,
**SEC** = seguridad, **PERF** = performance, **UX** = frontend
UX. **Esfuerzo**: XS<1h, S<4h, M<1d, L>1d.

| # | Bucket | Item | Esfuerzo | Impacto | Depende de |
|---|---|---|---|---|---|
| 1 | DX | `pre-commit` hooks (ruff + ruff-format + detect-secrets) | XS | alto | — |
| 2 | DX | `coverage.py` en CI con threshold 85% | S | medio-alto | — (paralelo a #1) |
| 3 | UX | a11y audit + dark-mode wiring (theme_preference ya existe) | S | alto | — |
| 4 | OPS | Backup `restore` automatic test en CI contra DB efimera | M | alto | — |
| 5 | DX | `mypy --strict` sobre `src/` | M | alto | #1 (pre-commit) |
| 6 | OPS | OpenTelemetry tracing (auto-instrument django + psycopg) | M | alto si crece | — |
| 7 | UX | SRI sobre static propios + Trusted Types directive | S | medio | — |
| 8 | SEC | Circuit breakers (AV / SMTP / HIBP) | M | alto | — |
| 9 | PERF | django-silk en dev + query auditor opt-in | S | medio | — |
| 10 | OPS | Deep health endpoint (`/health/deep`) | S | medio | — |
| 11 | UX | Playwright e2e (login → profile → admin → logout) | M | alto | — |
| 12 | PERF | psycopg connection pool tuning | S | medio | — |

### Orden recomendado para arrancar (si se aprueba)

**Fase 1 — DX foundation (~1.5d total)**

1. (XS, ~1h) Pre-commit hooks. Cierra el ultimo loophole entre
   "tests pasan local" y "CI reproduce". Bloquea secret leaks al
   commit. NO bloquea nada del trabajo subsecuente.
2. (S, ~3h) Coverage en CI con threshold. Da metrica clara de
   regresion futura. Paralelo a #1.
3. (S, ~3h) Accessibility audit. Hereda el theme_preference
   que ya esta en el modelo pero no se honra; dark mode + ARIA
   labels + keyboard nav. Es UX no SEC pero es high-visibility.

**Fase 2 — Validar el deploy (~1.5d total)**

4. (M, ~6h) Backup restore automation. Un backup que nunca se
   restauro NO es un backup. Test en CI contra Postgres
   efimero (services en GH Actions).
5. (S, ~3h) Deep health endpoint. `/health` actual es
   liveness; `/health/deep` ejecuta una query + write a tmp
   table. Operadores piden esto en general.

**Fase 3 — Type safety + observabilidad (~2d total)**

6. (M, ~1d) mypy --strict. Hay type hints, falta ratificar.
   Encuentra clases enteras de bugs. Depende de #1 (pre-commit
   ya tiene mypy plugin).
7. (M, ~1d) OpenTelemetry. Solo si el deploy escala mas alla
   de 1 instancia o el operador necesita correlation
   cross-service. Marca con un flag opt-in en config.

**Fase 4 — Hardening incremental (~1d total)**

8. (S, ~3h) SRI sobre static propios + Trusted Types CSP.
9. (M, ~4h) Circuit breakers en AV/SMTP/HIBP. Patron simple
   con backoff exponencial + half-open probe.

**Fase 5 — Performance baseline (~1d total)**

10. (S, ~3h) django-silk opt-in en dev.
11. (S, ~3h) psycopg pool tuning + benchmarks.

**Fase 6 — E2E (~1d total)**

12. (M, ~1d) Playwright. Las 4 jornadas criticas:
    login → profile, login → admin → revoke session,
    forgot password → reset, MFA enrollment → verify.

### Items deliberadamente NO en este plan

- WebAuthn / passkeys (L esfuerzo, alto ROI pero alta inversion).
- DRF / GraphQL (la API es minima; introducir framework antes de
  necesitarlo es over-engineering).
- i18n setup (single-locale por ahora; sin valor a corto plazo).
- Build pipeline frontend (esbuild/rollup) — premature hasta que
  el JS crezca mas alla del file actual.
- Kubernetes manifests (single-server template; agregar K8s sin
  multi-tenant claro es scope creep).

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `<this>` | Open 2026-06-20 handoff + close 2026-06-19 §8 con continuidad | suite stays green |

(Pendiente segun decisiones del operador.)

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos** (cerrado en sprint
06-15..06-19).

Mini-roadmap de mejoras propuesto: ver §2.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
