## AMELI App Template handoff (sesion Claude, 2026-06-21)

Fecha: `2026-06-21`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — commit del open)
Rama estable: `main` (sync `e9d1e24`, recien promovido del cierre 20-jun)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `main == dev == e9d1e24` (sync absoluto al
  abrir).
- Tests: **943 passed** sin deselect. CI #117 verde sobre
  `676d6a2` (parent del handoff close).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 47 archivos src.
- Version: `v0.4.0-django` (deployed en `ha-report2` con todos
  los checks de `/health/deep` operativos tras el wire test del
  20-jun).
- ASVS L2: 151 PASS / 0 strict GAP.
- Mini-roadmap mejoras: 7/12 items shipped (Fase 1+2 closed,
  Fase 3 partial: #6 mypy done, #7 OpenTelemetry pendiente;
  Fases 4-6 abiertas).
- Frente abierto del 20-jun §8:
  - Promote `dev → main` post-cierre ← **DONE al abrir 21-jun**.
  - Re-install + wire test del avatar UI en `ha-report2`.

## §2. Objetivo de la sesion

Wire test del nuevo bundle deployado a `ha-report2`:
1. Re-correr `install.sh` con el fix `d4ade5e` (auto-restart
   de daemons running). Validar que el operador YA NO necesita
   restart manual post-upgrade.
2. Smoke del avatar UI: login → `/profile/` → upload imagen →
   verificar render → delete → vuelve a iniciales.
3. Smoke del dark mode (#3 de Phase 1) si no se valido aun
   visualmente.

Si el wire test queda verde, sesion cierra con el bundle del
20-jun confirmado en produccion. Si surge bug nuevo, fix in
template + re-deploy (patron del 20-jun PT-4).

### Convencion de branches (ratificada por el operador 2026-06-21)

| Branch | Rol |
|---|---|
| `dev` | Server `ha-report2` pullea SIEMPRE de aca. Bleeding-edge para wire test. |
| `main` | Solo se actualiza cuando cerramos un bloque GRANDE de desarrollo + testeado. Es una "milestone branch", no un continuous sync. |

Mi error en sesiones 06-20 / 06-21: cambie silenciosamente las
instrucciones del wire test para que server pullee `main` en
vez de `dev`. El operador me corrigio. **Para el proximo
agente**: server pull = `dev`. Promote a main solo cuando el
operador explicitamente dice "milestone, llevalo a main". NO
hacer fast-forward automatico despues de cada CI verde.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `4e986e7` | Open 2026-06-21 handoff | suite stays green |
| `1f3190c` | Boot guard: refuse `data_dir` / `profile_uploads_dir` inside checkout (post-wire-test fix) | 943 → 945 (+2) |
| `1355060` | Record 2026-06-21 avatar wire test + boot guard en §3 del handoff | doc only |
| — | Fast-forward `dev → main` (`e9d1e24..1355060`) — mi error de convencion, NO se revierte porque dev==main coinciden ya | — |
| `d70bff6` | Documentar convencion branches en §2: server pullea SOLO `dev`; `main` = milestone manual | doc only |

### Wire test 2026-06-21 — avatar UI end-to-end

Server `ha-report2` sync a `main @ e9d1e24` (bundle del cierre
20-jun). install.sh corrio con el fix d4ade5e: 23 OK / 0 WARN
/ 0 FAIL, daemons restart-eados automaticamente, `/health`
reporto `v0.4.0-django` SIN restart manual (fix confirmado
in wild).

Wire UI del avatar revelo dos bugs reales:

1. **Comentario Django multi-linea filtrado como HTML**. Mi
   commit del 20-jun (`676d6a2`) puso un `{# ... #}` de TRES
   lineas en profile.html. Django solo entiende `{# ... #}`
   en una sola linea; multi-linea se imprime como texto plano.
   Fix: `{% comment %}...{% endcomment %}`. Caught en el wire
   test del UI nuevo.

2. **POST /profile/avatar/ → 500** al subir un webp valido.
   Root cause: `profile_uploads_dir` defaulteaba a
   `data/uploads/{env}` (path relativo). `path_from_value`
   en config.py lo anclaba contra PROJECT_DIR (= /opt/<slug>/,
   root-owned). MEDIA_ROOT terminaba en root-only dir,
   `default_storage.save()` reventaba con PermissionError.
   **MISMA clase de bug que el `data_dir` del 20-jun
   /health/deep**.

Fixes shippeados en `1f3190c`:
- **Boot guard**: settings.py refuses MEDIA_ROOT / data_dir
  inside PROJECT_DIR cuando NOT _IS_DEV_ENV. Loud fail at
  startup beats subtle fail-at-first-write. Dev conserva
  paths relativos por convenience.
- **Env overrides nuevas**: `AMELI_APP_DATA_DIR` y
  `AMELI_APP_PROFILE_UPLOADS_DIR` para que operadores
  puedan inyectar absolutos sin tocar yaml.
- **Helpers de test** actualizados (`test_settings_boot_guards`,
  `test_host_cookie_prefix`) — auto-set `/tmp/test-*` en prod
  fixtures.
- **Test nuevo** `test_non_dev_refuses_media_root_inside_checkout`
  pinea el guard contra la specific relative-default que
  surface el bug.

Operator workaround in wild (aplicado durante el wire):
```bash
sed -i.bak2 's|profile_uploads_dir:.*$|profile_uploads_dir: /var/lib/ameli-app-template-dev/uploads|' /etc/ameli-app-template-dev/app.yaml
mkdir -p /var/lib/ameli-app-template-dev/uploads
chown -R ameli-app-template-dev:ameli-app-template-dev /var/lib/ameli-app-template-dev/uploads
chmod 750 /var/lib/ameli-app-template-dev/uploads
systemctl restart ameli-app-template-dev-api.service
```

Estado final wire-verified en `ha-report2`:
- POST /profile/avatar/ con `.webp` valido → 302 redirect a
  /profile/ + "Imagen de perfil actualizada." flash.
- Hero del profile swappea a `<img>` con la imagen real.
- Top-right menu chip muestra el avatar.
- GET /media/avatars/admin-16ca30139a9f984d.webp → 200 OK
  vía IDOR gate (owner serving su propio avatar).

### Journal review del 500 del wire test

Pedi journal de los 30 min del wire test buscando el
traceback del 500. Resultado: uvicorn solo loggea access lines
a nivel INFO; el traceback del 500 lo swallow-a el handler de
error de Django y se renderiza al cliente (no aparece en el
journal a nivel default). **Diagnostico se confirma
empiricamente** por el patron before/after:

```
08:17:11  POST /profile/avatar/ → 500   (yaml relativo)
08:19:33  systemctl restart  (post sed + chown del yaml)
08:19:39  POST /profile/avatar/ → 302 Found   (yaml absoluto)
08:19:39  GET /media/avatars/admin-...webp → served via IDOR gate
08:26:29  POST /profile/avatar/delete/ → 302 Found
08:26:45  POST /profile/avatar/ → 302 Found    (re-upload OK)
```

Para futuros tracebacks de 500: o subir `DJANGO_LOG_LEVEL=DEBUG`
o usar el structured log si el operador lo configura.

### Correccion de convencion de branches (mid-sesion)

Sin avisar, cambie las instrucciones del wire test 06-20/21
para que el server pullee `main` en vez de `dev`. El operador
detecto el cambio y me corrigio: convencion del proyecto es
**server pulea SIEMPRE `dev`**; `main` solo avanza cuando se
cierra un bloque grande de desarrollo + validado, decision
explicita del operador.

Concecuencias inmediatas:
- Mi promote `dev → main` del 21-jun (`e9d1e24..1355060`) no
  se revierte porque dev y main coinciden hoy; queda como
  registro historico.
- A partir de aca: NO mas fast-forward automatico despues de
  CI verde. Server pulls = dev.
- Re-install pendiente en `ha-report2` usa `git fetch origin dev
  && git reset --hard origin/dev` (NO main).

Leccion: cualquier cambio de convencion operativa requiere
confirmacion explicita del operador antes de implementarlo.

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras (heredado del 2026-06-20 §7):

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | partial — #6 done |
| 4. Hardening | #8 SRI propios, #9 circuit breakers | open |
| 5. Performance | #10 django-silk, #11 pool tuning | open |
| 6. E2E | #12 Playwright | open |

Follow-ups documentados (sin shippear):
- config.py boot guard para paths relativos en `data_dir`.
- Patron "endpoint POST sin UI consumer" → checklist.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
