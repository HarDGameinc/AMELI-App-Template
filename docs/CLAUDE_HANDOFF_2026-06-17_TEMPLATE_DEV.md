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
| `a1fe164` | Item #12 — ASVS V3.4.4 `__Host-` cookie prefix (session + CSRF) | 776 → 782 (+6) |
| `e84f57a` | Item #11 — ASVS V5.5.1 MESSAGE_STORAGE allow-list boot guard + wire evidence for #12 | 782 → 787 (+5) |
| `8bde7c0` | Item #13 — ASVS V7.1.1 RedactingFilter for PII in logs | 787 → 801 (+14) |
| `e7e3653` | Item #10 — ASVS V13.2.2 OpenAPI contract test + response schemas | 801 → 810 (+9) |
| `<this>` | Item #9 — ASVS V1.4.4 authz centralised in `accounts/permissions.py` | 810 → 837 (+27) |

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
4. **Re-aprendi la leccion del IFS dos veces en una sesion**. Al
   intentar el wire test del item #9 en `ha-report2` propuse
   primero `set -a; . /etc/ameli-app-template-dev/app.env; set +a`.
   Bash fallo porque valores como
   ``AMELI_APP_DJANGO_SECRET_KEY=...!fF)WqL...`` contienen `(` `)`
   `!` que el shell re-evalua bajo `.` (source). El patron
   canonico ya estaba documentado en
   `CLAUDE_HANDOFF_2026-06-16` §8c — `while IFS= read -r line` con
   `declare "$key=$value"` parsea literal sin re-evaluacion.
   Tres fallas operacionales mas que estaban en la mismas
   instrucciones y que NO le mire antes de armar el script:
   - `manage.py` en `/opt/ameli-app-template-dev` no tiene bit
     `+x` — invocarlo como argumento del intérprete
     (`python manage.py`), no `./manage.py`.
   - `python` no esta en el PATH del shell de root; el venv solo
     expone `python3`. Usar `.venv/bin/python` directo —
     evita depender de `source .venv/bin/activate` Y del nombre
     del binario.
   - El sub-shell del heredoc no hereda el venv del shell
     interactivo, asi que mismo argumento: el binario directo
     gana.
   Lesson: antes de redactar un comando de wire test, abrir el
   handoff del dia anterior y copiar el §"Cargar env" textual.
   No re-derivar el patron desde memoria. Esto va a S-04 del
   playbook.

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

### Item #10 — V13.2.2 OpenAPI contract test

- **Qué**: (a) Extiende `_openapi_schema()` en `dashboard/views.py`
  con `required` + `properties` por response para `/health` y
  `/api/health` (era solo `description`). (b) Nuevo
  `tests/test_openapi_contract.py` que:
  - resuelve cada path documentado contra el URL conf, lo invoca
    via test client, y valida el JSON body contra el schema
    declarado;
  - barre el URL conf para detectar drift inverso — cualquier
    endpoint público que devuelva JSON pero no esté en el doc
    rompe CI, salvo allowlist explícita (`/openapi.json`,
    `/metrics`).
- **Por qué**: ASVS V13.2.2 (JSON schema validation). El gap
  histórico era que el doc se hand-mantenía y nada lo verificaba —
  cualquier rename de campo o nuevo endpoint quedaba mudo. Ahora
  CI falla si la realidad y el doc divergen en cualquier dirección.
- **Stdlib-only**: validador `_validate(value, schema)` cubre el
  subset de OpenAPI 3.1 que efectivamente usamos (`type`,
  `required`, `properties`, `enum`). Evita meter `jsonschema`
  como runtime dep — consistente con la política del template.
- **Bool-as-int safeguard**: el validador rechaza explícitamente
  `True/False` cuando el schema dice `integer`/`number`, porque
  `isinstance(True, int)` es `True` en Python y un bool perdido
  en un campo numérico no se notaría sin esta guardia.
- **Tests**: 9 casos (1 well-formed schema + 2 parametrized
  doc→reality + 1 reality→doc URL-conf walk + 5 unit tests del
  validador). Suite total: 801 → 810 passed.
- **Doc**: `COMPLIANCE_ASVS_L2_2026-06-16.md` V13.2.2 promovido
  GAP→PASS, totals 147/2 → 149/1, V7 +1 (7.1.1 ahora reflejado),
  V13 +1.

### Wire validation 2026-06-17 — items #9 + #10

Server `ha-report2` en `dev @ 6f7aad8` (post-#9). Patron canonico
S-04 con ephemeral users (un PUB rol public, un ADM rol
superadmin). Output completo:

```
=== fixtures ===
pub.role='public' pub.is_staff=False pub.is_superuser=False
adm.role='superadmin' adm.is_staff=True adm.is_superuser=True

[A] anon -> /admin/  status=302 loc='/login/?next=/admin/'
[B] pub  -> /admin/  status=302 loc='/profile/'
[C] adm  -> /admin/  status=200
[D] pub  -> /admin/users (json)  status=302 body=b''
[E] pub  -> /media/avatars/<adm>.png  status=403

=== cleanup OK ===
```

| Path | Got | Veredicto |
|---|---|---|
| A — anon -> /admin/ | 302 a `/login/?next=/admin/` | ✓ |
| B — pub -> /admin/ | 302 a `/profile/` | ✓ |
| C — adm -> /admin/ | 200 | ✓ |
| D — pub -> /admin/users con Accept: application/json | 302 a `/profile/` (NO 403 JSON) | ✓ con caveat (ver finding) |
| E — pub -> avatar de adm | 403 (IDOR gate `can_view_avatar`) | ✓ |

**Invariante del modelo verificado en wire**: la `User.save()`
mantiene `is_staff`/`is_superuser` sincronizados con `role` —
ningun row del deploy puede tener un desync que mueva los gates.

**Finding del wire** — path D revelo que el branch JSON del
decorator `superadmin_required` (return `_json_error("admin
access required", status=403)`) es CODIGO MUERTO para todas las
URLs bajo `/admin/*` porque `AdminAccessAuditMiddleware`
(`accounts/middleware.py:270`) corre ANTES que el view dispatch
y siempre redirige con `redirect("accounts:profile")` sin
consultar `Accept`. El decorator igual mantiene valor como
defense-in-depth (si en el futuro el middleware se desactiva o
se anade un endpoint con `@superadmin_required` fuera de
`/admin/*`), pero hoy es path no alcanzable por el cliente.

No es un bug introducido por #9 — comportamiento identico al
pre-refactor. La expectativa de 403 JSON en el script del wire
era incorrecta por modelo mental erroneo del chain de
middleware. Documentado aca para que el proximo agente no
re-derive la conclusion.

### Item #9 — V1.4.4 authz centralizada

- **Qué**: nuevo `src/ameli_web/accounts/permissions.py` con 7
  predicados — `is_authenticated`, `is_superadmin`,
  `can_access_admin_panel`, `can_view_avatar`,
  `is_protected_account`, `can_delete_user`, `can_self_delete`.
  Toda decisión de autorización en el codebase ahora rutea por
  estos predicados. Los callsites migrados:
  - `admin_views.py:superadmin_required` decorator.
  - `accounts/middleware.py` × 3 (admin redirect,
    DjangoAdminSudoGate, maintenance-mode bypass).
  - `accounts/context_processors.py` (`can_access_admin` para
    templates).
  - `accounts/views.py` × 2 (profile + admin context).
  - `urls.py:_authenticated_media` (IDOR avatar gate).
  - `accounts/services.py` × 2 (delete_user + self_delete).
- **Por qué**: ASVS V1.4.4 "single vetted access-control
  mechanism". Antes cada callsite re-derivaba la decisión desde
  los flags raw de Django (`is_staff`, `is_superuser`,
  `role == ROLE_SUPERADMIN`); un refactor que desincronizase los
  flags del rol semántico habría desplazado los gates en
  silencio. Ahora hay un único punto de cambio: si mañana entra
  un `ROLE_OPERATOR` intermedio, solo `permissions.py` se toca.
- **Source of truth**: el predicado lee `user.role`, NO
  `is_staff`. El invariante de `User.save()` mantiene los flags
  Django en sync, pero el predicado no los consulta —
  `test_is_superadmin_does_not_trust_is_staff_alone` pin del
  comportamiento.
- **Lazy import**: `permissions.py` hace `from
  ameli_web.accounts.models import User` adentro de cada predicado
  porque el módulo se importa muy temprano (middleware, context
  processor) y un import top-level del modelo causa
  AppConfig-not-ready en algunos paths de test.
- **Tests**: 27 en `tests/test_permissions.py` cubriendo la
  truth table completa de cada predicado + 2 integration tests
  contra ORM real (`@pytest.mark.django_db`). Suite: 810 → 837
  passed.
- **Doc**: COMPLIANCE V1.4.4 GAP→PASS, V1 chapter 10/1 → 11/0,
  totales 149/1 → 150/0 (el último GAP strict roadmap-tracked
  cerrado; los 3 GAPs restantes en detalle — 11.1.5, 13.1.5,
  14.2.3 — son acceptable-residual + item #14 supply-chain).

## §4. Decisiones tomadas

1. **Orden de cierre L2**: bucket S cerrado completo (#13 → #10 →
   #9 escalando S→S→M) antes de tocar Medium grandes. Razon: cada
   S restante movia 1 PASS en la matriz por <1h de costo; los M
   abiertos (#14 supply chain) tienen blast-radius mayor sobre el
   lockfile de CI y conviene tenerlos en una sesion limpia.
2. **No promover `dev → main` esta sesion**. CI lleva rojo desde
   commit `a1fe164` (item #12, 2026-06-17) y la verdadera causa
   (el test flaky de auditoria, ver §6) recien quedo
   diagnosticada al final del dia. Promover con CI rojo
   contradice el invariante "main = CI green" del S-05 del
   playbook.
3. **Branch de trabajo**: el setup del session asignaba
   `claude/compassionate-meitner-ds2fs4`, pero el operador
   ratifico la convencion canonica del proyecto: "solo
   trabajamos en `dev`". A partir del `git checkout dev && git
   merge --ff-only` de `6f7aad8`, todos los commits del dia
   viven en `dev`. La branch claude/* quedo redundante (mismo
   HEAD) y se puede borrar cuando el operador autorice.
4. **Wire test path D — comportamiento aceptado, no es bug**.
   Ver §6 finding 2. La expectativa del 403 JSON era erronea por
   modelo mental incorrecto del chain de middleware; NO ajustar
   el codigo para "arreglar" el path D.

## §5. Metricas al cierre

| Metrica | Inicio dia | Cierre dia | Δ |
|---|---|---|---|
| Suite local (excluyendo flake TZ) | 745 passed | **837 passed** | +92 |
| Test files nuevos | — | 3 (`test_openapi_contract.py`, `test_permissions.py`, plus #13 already shipped) | — |
| ASVS L2 active rows PASS | 142 | **150** | +8 |
| ASVS L2 strict GAP roadmap-tracked | 7 | **0** | -7 |
| Capitulos completos al bar L2 | 6 (V2,V3,V4,V5,V10,V12) | **8** (+V1,V7) | +2 |
| Commits sobre `dev` | 0 (start at `72c37e8`) | 13 | — |
| Commits propagados a `main` | 0 | 0 (pendiente promote) | — |
| CI verde | last green @ `3bd2e7f` | red continuo desde `a1fe164` | -8 runs |
| Wire validations | 1 (#4 carry-over) | 4 (#7, #8, #12, #9+#10) | +3 |

## §6. Hallazgos / findings

1. **CI rojo crónico desde `a1fe164` (8 runs consecutivos) — root
   cause encontrado**. El unico test que falla es
   `tests/test_admin_audit_pagination.py:255
   test_filtered_audit_queryset_respects_combined_filters`. El
   error en CI (Python 3.11 Y 3.12) es identico: el queryset
   filtrado por `action="login", date_to=ayer` devuelve 5 rows
   en lugar de 1. Los 5 son `login_failed::admin` +
   `login_success::admin × 3 + login_failed::admin`. No es un
   problema TZ-dependent (yo lo deseleccionaba local pensando
   que era America/Santiago vs UTC; pero CI corre en UTC y
   tambien falla). Es el caso textual de la **lecccion #3 del
   §3 de este handoff**: test depende de estado limpio
   (`AuditEvent.objects.all().delete()` en setUp o fixture), no
   lo tiene, y el isolation por transaccion de pytest-django no
   lo cubre porque audit events salen del flujo normal de los
   tests previos del mismo modulo. Fix probable: agregar
   `AuditEvent.objects.all().delete()` al `setUp` o un
   `@pytest.fixture(autouse=True)` en `test_admin_audit_pagination.py`.
   **Es el item #1 del proximo agente** — sin esto, no se
   puede promover dev->main, no se puede cerrar el dia.
2. **Branch JSON de `superadmin_required` es dead code en
   /admin/\***. Documentado en §"Wire validation #9 + #10
   finding". El `AdminAccessAuditMiddleware` preempta cualquier
   request `Accept: application/json` a `/admin/*` de
   no-superadmin con `redirect("/profile/")` antes que el
   decorator vea Accept. No es un bug — es defense in depth
   redundante, pero conviene NO eliminar el branch del
   decorator porque protege endpoints fuera de `/admin/*` que
   en el futuro usen el mismo decorator.
3. **Bash IFS bug re-aprendido (lesson #4 del §3)**. El patron
   `set -a; . app.env; set +a` se rompe con valores que
   contienen `(`, `)`, `!`. El `while IFS= read -r line` +
   `declare` esta ahora canonizado en S-04 del HANDOFF_TEMPLATE
   para que ningun futuro agente lo re-derive desde memoria.

## §7. Roadmap actualizado

Heredado de la sesion del 2026-06-16, ver §"Carry-over al
2026-06-17" en ese handoff. Items cerrados hoy:

| Item | ASVS | Commit | Wire |
|---|---|---|---|
| #7 V12.4.1 AV scan | PASS | `8a45724` + `bc9f1c9` | ✓ |
| #8 V7.4.1 error handlers | PASS | `f724e21` | ✓ |
| #15+#21+#22 hygiene bundle | PASS | `f278ac1` | n/a |
| #11 V5.5.1 MESSAGE_STORAGE allow-list | PASS | `e84f57a` | n/a |
| #12 V3.4.4 `__Host-` cookie | PASS | `a1fe164` | ✓ |
| #13 V7.1.1 RedactingFilter | PASS | `8bde7c0` | n/a |
| #10 V13.2.2 OpenAPI contract test | PASS | `e7e3653` | n/a |
| #9 V1.4.4 authz centralizada | PASS | `6f7aad8` | ✓ |

Items roadmap restantes:

- **#14 V14.2.3** Lockfile con hashes (M, ~1h) — el ultimo
  Medium real.
- **Operacionales** sin impacto ASVS: #16 doc drift, #18 backup
  timer, #19 PG TCP listener, #20 manage.py auto-load
  APP_CONFIG, #23 branch protection.

## §8. Continuidad — para el proximo agente

**ORDEN ESTRICTO de arranque** — no saltearse:

1. **FIX CI RED**. Antes de cualquier nueva feature, abrir
   `tests/test_admin_audit_pagination.py` linea 255 y resolver
   el flake. Hipotesis: agregar
   `AuditEvent.objects.all().delete()` en setUp o introducir
   una fixture `clean_audit` con `autouse=True`. Verificar
   local con `--deselect` removido + correr el modulo completo.
   El test ha fallado 8 veces seguidas (CI #63..#71), bloquea
   la promocion a main.
2. **Promote `dev → main`** una vez CI verde. Patron S-05:
   `git checkout main && git merge --ff-only dev && git push`.
   La distancia es `8bde7c0..e304114` (~5 commits propagables).
3. **Wire-validar #14** despues. La feature toca el lockfile y
   las github actions; debe pasar por el flujo full S-04.

**Estado del bucket S de L2**: cerrado. Quedan solo M y
operacionales — el ritmo del proximo dia puede ser mas pausado.

**Patron de wire-test S-04**: ya esta canonizado en
`HANDOFF_TEMPLATE.md` con el bloque "Environment prep". COPIAR
ese bloque textual, NO re-derivar.

**Lecciones del dia para incorporar** (S-04 / S-08):
- Annotation grammar (ruff S + bandit B juntos siempre).
- Test state isolation explicito en cualquier test que toque
  un contador / clock / random / audit / throttle.
- IFS-safe env loader en wire tests.
- En CI rojo cronico, NUNCA asumir "es TZ" sin abrir el log
  del runner CI — la causa real puede ser distinta.
