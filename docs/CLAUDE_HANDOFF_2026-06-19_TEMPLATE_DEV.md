## AMELI App Template handoff (sesion Claude, 2026-06-19)

Fecha: `2026-06-19`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del fix throttle ceil)
Rama estable: `main` (en `88cce00`; pendiente promote PT-1)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-18_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-18_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `dev @ d1f046b`, `main @ 88cce00`. Diferencia
  4 commits (`b94dfcc`, `d91ef8d`, `9df29c4`, `d1f046b`).
- Tests local: 882 passed sin deselect.
- CI: ultimo run `#93` sobre `d1f046b` rojo en Python 3.12 con
  `test_forgot_password_throttle_after_too_many_requests`
  (assert 200 == 429). CI `#92` sobre el parent `9df29c4` verde
  — el commit del fail es solo docs (handoff close), asi que
  NO es regresion introducida por el cambio: es un nuevo flake.
- ASVS L2: **151 PASS / 0 strict-tracked GAP**.
- Frente abierto del handoff 18-jun §8: **PT-1..PT-4** wire
  tests pendientes para retomar en otro equipo.

## §2. Objetivo de la sesion

Resolver el flake CI nuevo (lo primero, sin esto no se promueve
nada), retomar PT-1 (promote `dev → main`) y avanzar con
PT-2/PT-3/PT-4 segun lo que sea aplicable desde este entorno.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `67ae53a` | Fix CI flake — `_read_throttle_counter_sliding` cambia `int()` truncation por `math.ceil` (rate limiter no debe under-contar) + test guard | 882 → 883 (+1) |
| — | **PT-1** Promote `dev → main` (`88cce00..67ae53a`, 5 commits) — CI #94 verde | suite stays green |

### Wire validation 2026-06-19 — PT-1, PT-2, PT-3

Branch promote ejecutado desde el sandbox checkout que tenia el
pre-push hook instalado de ayer (PT-2 layer 1 ya activo).
Cadena de pruebas:

1. **PT-2 layer 1 (client hook) atrapa la version sin bypass**:
   ```
   $ git checkout main && git push origin main
   [pre-push] Direct push to 'main' refused.
   ...
   error: failed to push some refs
   ```
   El push regular se rechaza con el mensaje canonico del hook
   (`deploy/git-hooks/pre-push:36`). El operador queda forzado
   a usar bypass o PR.

2. **PT-2 bypass funciona como documentado**:
   ```
   $ ALLOW_DIRECT_PUSH=1 git push origin main
   [pre-push] ALLOW_DIRECT_PUSH=1 set; skipping branch-protection check
   To .../HarDGameinc/AMELI-App-Template
      88cce00..67ae53a  main -> main
   ```
   Push completado, hook reconoce el bypass.

3. **PT-3 layer 2 (audit workflow) detecta el direct push**:
   `Main push audit #1` corrio sobre `67ae53a`. Job
   `Audit direct pushes to main` exit 0, log:
   ```
   ##[warning]commit 67ae53a by Claude <noreply@anthropic.com>
       -- subject: fix sliding-window throttle: ceil prev contribution
   This commit landed on main without going through a PR merge.
   On a private + Free-plan repo, GitHub does not enforce branch
   protection server-side. The pre-push hook
   (scripts/install-pre-push-hook.sh) is the client-side guard;
   this job is the audit-log substitute.
   ```
   Anotacion `::warning::` greppable en Actions. **PT-3 layer 2
   wire-verified end-to-end**.

4. **PT-3 layer 3 (latente)**: Rulesets + classic rules siguen en
   repo settings sin enforce hasta upgrade a Team. NO se prueba
   en wire (ya documentado como inactivo).

**PT-1 status**: cerrado. `main == dev == 67ae53a`.
**PT-2 layer 1 status**: cerrado para este checkout (hook
instalado y verificado). Para Windows + ha-report2 sigue como
PT-pendiente — `bash scripts/install-pre-push-hook.sh`.
**PT-3 status**: cerrado (layer 2 wire-verified; layers 1 y 3
ya cubiertos).

### Fix CI flake — root cause distinto al "test-state isolation"

El test `test_forgot_password_throttle_after_too_many_requests`
hace tres POST a `/login/forgot/` con
`FORGOT_PASSWORD_IP_MAX=2`, `FORGOT_PASSWORD_IP_WINDOW=600`:

```python
for _ in range(2):
    response = client.post("/login/forgot/", ...)
    assert response.status_code == 200
response = client.post("/login/forgot/", ...)
assert response.status_code == 429
```

CI `#93` fallo en Python 3.12: el 3er request devolvio 200 en
lugar de 429. Local pasa 5/5 — no es leak de estado.

**Root cause**: `_read_throttle_counter_sliding` en
`services.py` calculaba:

```python
return cur_count + int(prev_count * prev_weight)
```

El `int()` trunca hacia 0. Cuando el test cruza la frontera de
un bucket de 600s entre el request 2 y el request 3:

- Request 1,2 caen en bucket A: count_A = 2, sliding = 2 (200 ✓).
- Bucket cruza.
- Request 3 cae en bucket B: count_B = 1. `elapsed ≈ 1ms`,
  `prev_weight ≈ 0.99999`. `int(2 * 0.99999) = int(1.99998) = 1`.
  sliding = 1 + 1 = 2. Test espera > 2 → falla con 200.

Probabilidad: `test_duration / window_seconds ≈ 3s / 600s = 0.5%`
por corrida. CI ~12 corridas/dia → flake cada ~17 dias. Acaba
de ocurrir.

**Fix**: cambiar `int()` por `math.ceil()`. Un rate limiter
NUNCA debe under-contar — el truncation era un bug de
seguridad latente, no solo un flake. Con `ceil(1.99998) = 2`,
sliding = 1 + 2 = 3 → 429 correcto. Costo: maximo 1 over-count
al edge (sesgo defensivo aceptable).

Tests: nuevo
`test_throttle_sliding_window_rounds_prev_contribution_up` en
`test_code_review_fixes_20260615.py` que mockea
`timezone.now` a 1ms post-boundary y verifica
`sliding == 3` (con `ceil`, vs `2` con `int()`). Pin contra
regresion futura.

### Leccion incorporada — flakes como bugs latentes

Un flake de 0.5% es **un bug de seguridad real** disfrazado de
"problema CI". Si el test que protege la propiedad de
rate-limiting puede pasar con un valor incorrecto el 0.5% del
tiempo, la propiedad NO esta enforced — el atacante real puede
explotar el mismo edge. **Regla**: no marcar un test como
"flake" sin entender el mecanismo de falla. Si el fix correcto
es en producto, hacerlo ahi.

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Heredado del 18-jun. Roadmap items: **0 abiertos**. Items con
operator-side validation pendiente:

- **PT-1** sync `dev`/`main` y promote (4 commits pre-fix +
  este).
- **PT-2** instalar `pre-push` hook en cada checkout.
- **PT-3** verificar branch protection layered.
- **PT-4** server-side: PG TCP localhost + backup timer +
  restore verify.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
