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
| `<this>` | Item #7 — ASVS V12.4.1 AV scan opcional sobre avatares | 745 → 766 (+21) |

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
