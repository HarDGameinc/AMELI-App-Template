## AMELI App Template handoff (sesion Claude, 2026-06-17)

Fecha: `2026-06-17`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del handoff mismo)
Rama estable: `main` (en `72c37e8`; al dia)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-16_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-16_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `main == dev == 72c37e8`. Sesion previa cerro 6
  items roadmap (#1..#6 + #17) + 7 ASVS controls promovidos a PASS.
- Tests: **745/745 green** local. CI: ultimos 12 runs verde.
  ruff clean (con `S` ruleset), bandit `-ll -ii` clean (Medium 0 /
  High 0 con 3 issues skipped por `# nosec`), pip-audit clean.
- ASVS L2: **142/149 active PASS = 95.3%**, 7 strict GAPs restantes,
  0 HIGH severidad.
- Frente abierto al cierre de ayer: items #7..#23 en el roadmap. El
  orden recomendado del 2026-06-16 §"Carry-over al 2026-06-17" sigue
  vigente.

## §2. Objetivo de la sesion

Arrancar con el item #7 — **ASVS V12.4.1 (AV scan opcional sobre
avatares)**, primer Medium del roadmap. La implementacion debe ser
opt-in (no forzar clamd como dep) y consistente con el patron
ya existente del template (helper en services.py, hook en el
upload flow, audit row + tests).

Despues del #7, si queda budget, atacar la fila de XS hygiene
(#15, #21, #22) que cierran las anotaciones operacionales del
roadmap sin esfuerzo arquitectural.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `8a45724` | Item #7 — ASVS V12.4.1 AV scan opcional sobre avatares | 745 → 766 (+21) |
| `bc9f1c9` | Hotfix CI rojo: `# nosec B310` faltante en `av.py` HTTP transport | suite stays green |
| `e873185` | Wire validation evidence + handoff updates | suite stays green |
| `f278ac1` | Items #15 + #21 + #22 — XS hygiene bundle (pip-audit hard-fail + actions bumps) | suite stays green |
| `f724e21` | Item #8 — ASVS V7.4.1 branded HTTP error handlers (404/500/403/400) | 766 → 776 (+10) |
| `c035c94` | Item #8 wire validation evidence | suite stays green |
| `425220a` | Fix flake CI #56 — defensive ThrottleCounter cleanup in test_auth_failures_alert.py | suite stays green |

### Wire validation 2026-06-17 — item #7

Smoke test en `ha-report2` con ephemeral user (sin
``must_change_password`` ni ``locked_at``) contra un mock HTTP AV
server in-process (ephemeral port):

| Path | Status | Audit Δ | Detalle |
|---|---|---|---|
| DISABLED | 302 | 0 | sin endpoint → AV block bypassed |
| CHECK_FAILED (TCP closed) | 302 | 1 | fail-open + audit `connectionrefusederror`, scheme=tcp |
| OK (HTTP mock) | 302 | 0 | clean scan, no audit |
| INFECTED (HTTP mock) | 400 | 1 | reject + body "rechazada por antivirus" + audit con sig `Wire-Test-EICAR`, scheme=http |

Propiedades verificadas:
- ``endpoint_scheme`` solo guarda el scheme, no la URL completa (no
  leak de hosts internos al audit chain).
- Body de error genérico, signature solo en audit chain (no
  fingerprint del catalog AV via response).
- ``request_id`` correlation en ambos audit paths (`_check_failed`,
  `_rejected`).
- Ephemeral user creado + eliminado en el mismo script — DB state
  matches pre-smoke snapshot.

### Lecciones operacionales del item #7

1. **Wire test users requieren estado limpio**. El primer intento
   uso el ``tester`` user que tenia ``must_change_password=True``
   + ``locked_at``. El ``MustChangePasswordMiddleware`` redirigia a
   ``/profile/#profile-tab-security`` antes que la view del avatar
   ejecutara, dando 302 sin que se llamara ``scan_bytes``. Fix:
   crear ephemeral user para cada wire test (patron ya usado en
   item #4). Lesson incorporada al S-04 del playbook.
2. **Annotation grammar discipline (lesson #6 del 16-jun ratificada)**.
   El commit `8a45724` shippeo solo ``# noqa: S310`` en el HTTP
   transport de av.py, sin el matching ``# nosec B310``. CI red
   en bandit. Confirma que la regla del 16-jun es vinculante: cada
   linea que dispara una regla de ruff S **debe** llevar tanto
   ``# noqa: SXXX`` como ``# nosec BXXX`` (cuando bandit tambien la
   marque). El doc del HANDOFF_TEMPLATE va a necesitar un checklist
   item explicito al respecto en la proxima revision.
3. **Tests que dependen de contador / reloj / random deben resetear
   estado explicitamente**. CI #56 caught a flake on
   ``test_first_threshold_crossing_queues_alert`` (mismo commit
   `f724e21` paso en dev #55, fallo en main #56). El test asumia que
   el ``ThrottleCounter`` empezaba en 0; un test anterior + el
   straddling del window boundary de 300s (1 en ~3000 runs) hacen
   que el bump retorne != ``LOGIN_LOCKOUT_USER_MAX`` y la condicion
   ``new_count == max`` no fire. Los otros tests del modulo ya
   defendian con ``ThrottleCounter.objects.filter(...).delete()``;
   los dos primeros no. Fix en `425220a`. Regla general: el
   isolation por transaccion de pytest-django NO garantiza
   no-leak de side-effects que dependen de timing/random/contadores
   — el reset explicito es obligatorio.

### Item #7 — V12.4.1 AV scan

- **Qué**: nuevo modulo `accounts/av.py` con dos transports (clamd
  INSTREAM TCP y HTTP POST), helper `scan_bytes(data, endpoint)`
  que devuelve `("ok"|"infected"|"check_failed"|"disabled", detail)`.
  Setting `AV_ENDPOINT` opt-in via `AMELI_APP_AV_ENDPOINT`. Hook en
  `views.py:update_avatar` corre el scan DESPUES de la validacion del
  form Pillow y ANTES del `replace_avatar`.
- **Por que**: ASVS V12.4.1 (uploaded content scanned). Cierra el
  residual risk R-05 cuando el operator opta in.
- **Decision policy clave**: **fail-open con audit visibility**
  cuando el endpoint esta configurado pero no responde. Precedente
  HIBP password validator (`validators.py:82-96`). Un timeout o
  endpoint caido NO bloquea al user; queda registrado en
  `avatar_upload_av_check_failed` para que el operator lo vea.
  INFECTED siempre rechaza con `avatar_upload_av_rejected` + mensaje
  generico al user (la firma queda solo en el audit chain, no en la
  respuesta HTTP — no leak del catalog de AV).
- **stdlib-only**: ``socket`` para clamd TCP, ``urllib`` para HTTP.
  Sin nuevas runtime deps; consistente con la politica del template.
- **Tests**: 21 nuevos en `tests/test_avatar_av_scan.py` cubriendo
  los 4 verdict shapes, ambos wire transports, URL credential
  redaction, defaults (port 3310 cuando no se especifica), HTML vs
  JSON response paths, fail-open vs reject vs disabled.
- **Doc**: `docs/OPERATIONS.md` agrega seccion "Avatar AV scan"
  con tabla de verdicts + comando EICAR de sanity check;
  `docs/SECURITY.md` R-05 marcado Closed; `docs/COMPLIANCE_ASVS_L2_2026-06-16`
  V12.4.1 promovido a PASS.

## §4. Decisiones tomadas

(Pendiente.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente.)

## §7. Roadmap actualizado

Heredado de la sesion del 2026-06-16, ver §"Carry-over al
2026-06-17" en ese handoff. Items se marcan
`closed-2026-06-17 <commit>` a medida que se cierran.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
