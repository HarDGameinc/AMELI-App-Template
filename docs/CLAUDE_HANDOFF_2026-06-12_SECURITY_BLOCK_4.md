## AMELI App Template handoff (sesion Claude, 2026-06-12, Bloque 4)

Fecha: `2026-06-12`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCKS_1_2_3.md`](CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCKS_1_2_3.md).

Despues de cerrar bloques 1-3 + H6 el usuario pidio "dejemos lo mejor
posible este template lo mas seguro confiable a pruebas de errores y/o
intervencion de algun atacante" — no para agregar features sino para
consolidar la base.

Esta sesion ataca esa peticion con dos sub-bloques:

- **4A — Defense in depth chico pero acumulativo** (M5, headers
  modernos, honeypot, SMTP boot guard, banner de alertas en perfil).
- **4B — Backlog del audit + ops de H6** (N3 lockout permanente,
  admin unlock endpoint, systemd timer + doc para `verify-audit`).

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- **539 tests pasando** (`pytest -v`)
- **0 regresiones**
- Nuevos archivos de tests: `test_security_hardening_block4.py`

### Resumen ejecutivo

| Frente | Antes (bloque 1-3) | Despues (bloque 4) |
|---|---|---|
| `/django-admin/` | Solo password + MFA al login inicial | Sudo grant explicito requerido; via panel pasa por el modal sudo |
| Headers HTTP | CSP + X-Frame + X-Content-Type + Referrer-Policy | + `Permissions-Policy` + `Cross-Origin-Opener-Policy` + `Cross-Origin-Resource-Policy` |
| Login form | Sin proteccion contra bots automatizados | Honeypot field + audit `login_bot_detected` |
| Outbound email en prod | Operador podia arrancar con backend console (no-op) | Boot guard: refuse si backend no es smtp/file o smtp sin host |
| Perfil al cargar | Sin pista de items de seguridad pendientes | Banner que lista MFA off, sin email, password >90d con CTA por item |
| Lockout por user | Temporal, atacante espera y reintenta | Permanente tras N ventanas consecutivas; admin desbloquea |
| Audit chain | Verificacion manual via CLI | Systemd timer horario + alert hook documentado |

### Bloque 4A — Defense in depth (3 commits)

| Commit | Item |
|---|---|
| `21f3d20` | M5 + headers + honeypot + SMTP guard + alerts |
| `fadb043` | CSP relajado solo en `/django-admin/*` (fix de la UI rota) |

**Detalle por item**:

#### M5 — MFA gate explicito en `/django-admin/`

El framework admin es muy poderoso y bypasea cualquier check de
business logic. Una cookie superadmin robada antes daba acceso
directo. Ahora:

- `DjangoAdminSudoGateMiddleware` intercepta cualquier path bajo
  `/django-admin/`. Si el usuario es staff pero la sesion no tiene
  sudo activo: redirige a `/admin/` con flash warning y audit
  `django_admin_blocked_no_sudo`.
- Endpoint nuevo `POST /admin/django-admin/enter/` con
  `@sudo_required`. La UI del panel cambia el viejo `<a href=django-
  admin>` por un `<button>` que postea ahi — el wrapper `requestJson`
  ya maneja el 401 `need_sudo` y abre el modal. Al confirmar, el
  endpoint responde `{ok, redirect: /django-admin/}` y el JS navega.
- Audit `django_admin_entered` cada vez que un superadmin completa el
  flow.

#### Headers HTTP modernos

`SecurityHeadersMiddleware` agrega tres headers a toda response:

- `Permissions-Policy`: turn-off explicito de camera, microphone,
  geolocation, payment, USB, accelerometer, gyroscope, magnetometer,
  el viejo interest-cohort de FLoC.
- `Cross-Origin-Opener-Policy: same-origin`: bloquea que otra
  ventana de origen distinto pueda hablar con `window.opener` de la
  app.
- `Cross-Origin-Resource-Policy: same-origin`: bloquea que otra
  pagina cargue recursos nuestros como `<img>` o `<script>` (defensa
  contra Spectre-class side-channels que necesitan cross-origin
  loading).

`setdefault`-style: si un view ya seteo un valor especifico (ej.
`/docs`) no se sobrescribe.

#### CSP relajado para `/django-admin/*`

Bug que aparecio al verificar M5: la CSP estricta sin `'unsafe-
inline'` rompe los inline scripts del admin nativo (theme switcher,
autocompletes, sortables). Como `/django-admin/` ya esta gated por
sudo + MFA + audit, la relajacion controlada es el trade-off correcto.

- `_django_admin_csp()` retorna una CSP con `'unsafe-inline'` solo en
  esa path.
- El middleware elige policy por prefix; el resto del sitio sigue con
  nonces.

#### Login honeypot

- Template inyecta un input `name="hp_company"` off-screen via inline
  style + `aria-hidden="true"` + `tabindex="-1"` + `autocomplete="off"`.
- `TemplateLoginView.post()` si recibe valor no-vacio: responde con el
  mismo mensaje generico de wrong-credentials (no revela que detectamos
  el bot) y audita `login_bot_detected` con `ip` + `user_agent`.

#### SMTP boot guard

Antes el deploy podia arrancar fuera de dev con `email.backend =
console` y los flows de password reset + MFA email fallaban
silenciosamente. Ahora `settings.py` refuse:

```python
if not _IS_DEV_ENV:
    if email_backend not in {"smtp", "file"}:
        raise RuntimeError("email.backend must be 'smtp' or 'file'...")
    if email_backend == "smtp" and not EMAIL_HOST:
        raise RuntimeError("email.backend is 'smtp' but email.host is empty...")
```

#### Banner de seguridad en `/profile/`

`profile_view` ahora pasa `security_alerts: list[dict]` al template.
La lista se computa por `_security_alerts_for(user)`:

- **2FA no activado**: si `not user.mfa_enabled`.
- **Sin email registrado**: si `not user.email` (sin email no hay path
  de recovery de password).
- **Tu contrasena tiene N dias**: si la edad excede
  `PROFILE_PASSWORD_MAX_AGE_DAYS` (default 90, configurable).

Cada item tiene `icon`, `title`, `detail` y un boton que dispara
`data-tab-trigger="profile-tab-security"` para llevar al user al fix.

### Bloque 4B — N3 + ops H6 (1 commit)

| Commit | Item |
|---|---|
| `5286ed1` | N3 lockout permanente + admin unlock + verify-audit timer |

#### N3 — Lockout permanente

`User` gana dos campos:

- `locked_at: DateTimeField(null=True)` — marca de cuando se aplico el
  lock duro.
- `locked_reason: CharField(64)` — texto operativo
  (`"throttle:3_consecutive_lockouts"`).

Migration `accounts/0008_user_locked_at_user_locked_reason`.

Logica:

- `_consecutive_lockouts_for(username, window)` consulta el audit log
  (no el throttle counter, que se resetea) y cuenta los
  `login_locked_out` con timestamp en ventanas distintas dentro de un
  rango. Una ventana = `>= window * 0.5` de gap entre eventos.
- `maybe_permanently_lock(username)` se llama desde la login view
  justo despues de recordear `login_locked_out`. Si los consecutivos
  >= `LOCKOUT_PERMANENT_CONSECUTIVE` (default 3), set `locked_at = now()`
  y audita `user_locked_permanently`.
- `check_login_throttle` ahora chequea PRIMERO si el usuario tiene
  `locked_at` set y raise `AccountLocked` con mensaje hard-lock
  (`retry_after=0` — no es temporal).
- `admin_unlock_user(actor_username, username)`: clear `locked_at`,
  audit `user_unlocked_by_admin`. Endpoint
  `POST /admin/users/<username>/unlock` sudo-gated.

#### Systemd timer para `verify-audit`

Dos templates nuevos en `deploy/systemd/`:

- `ameli-app-verify-audit.service`: oneshot que corre
  `ameli-app verify-audit`. Hardening estandar (`NoNewPrivileges`,
  `ProtectSystem=full`, `ReadOnlyPaths=APP_DIR`).
- `ameli-app-verify-audit.timer`: `OnCalendar=*-*-* *:07:00` (horario,
  minuto 7 para no chocar con otros timers).

`scripts/install.sh` ya renderiza todos los .service/.timer del
directorio asi que la nueva pareja se instala automaticamente en el
proximo deploy.

#### Doc en `OPERATIONS.md`

Nueva seccion "Audit chain verification (H6)" con:

- Como activar (`AMELI_APP_AUDIT_HMAC_KEY`).
- Comando manual + flags de range.
- Como agendar el timer + hook de alerta (`OnFailure=`).
- Recipe (con caveats) para rotar la key.

### Bloque 4C — Bug fix de static + backlog post-bloque (6 commits)

Despues del 4B aparecieron tres situaciones a resolver: un bug visual
en el django admin nativo, y cinco items del backlog que el usuario
pidio cerrar para "dejar el template lo mas solido posible".

| Commit | Item |
|---|---|
| `ce55160` | Bug fix: `/static/` ahora usa el finder pipeline (admin assets cargan) |
| `144792d` | Backlog #1: UI unlock en `/admin/` |
| `34a972d` | Backlog #5 + #7: Argon2 tuning + timing pad forgot-password |
| `f6a601a` | Backlog #4: Suite e2e de seguridad (14 tests) |
| `403c69f` | Backlog #6: `rotate-audit-key` CLI + recipe operativo |

#### Bug fix `/static/` finder pipeline

Verificacion del fix CSP de django-admin destapo un segundo problema:
los assets del admin nativo (`/static/admin/css/*.css`, `/static/admin/
js/*.js`) devolvian 404 HTML, y `X-Content-Type-Options: nosniff`
bloqueaba el render porque el MIME no matcheaba. La pagina del django
admin se veia "rota" — sin estilos, sin theme switcher.

Causa: `django.views.static.serve` solo mira `STATICFILES_DIRS[0]`. El
admin nativo trae sus assets en `django/contrib/admin/static/admin/`,
que ese serve no consulta.

Fix: `_serve_static` ahora usa `staticfiles.finders.find(path)` que
recorre tanto `STATICFILES_DIRS` como cada app instalada. Asi el admin
resuelve sin necesidad de `collectstatic`. Production con Caddy/nginx
delante no toca este handler.

3 tests pinean el bug-fix: admin css resuelve, app.css del proyecto
sigue, paths inexistentes 404.

#### Backlog #1 — UI unlock en `/admin/`

El backend de N3 ya estaba (`POST /admin/users/<username>/unlock`),
pero faltaba la UI. Cambios:

- `serialize_user` ahora expone `locked`, `locked_at`,
  `display_locked_at`, `locked_reason`.
- `_users_panel.html` muestra badge **"Bloqueado"** (rojo) junto a los
  otros badges del user, con `title=` apuntando al `locked_reason`.
- Boton **"Desbloquear"** condicional, solo aparece cuando
  `user_item.locked` es true. Reusa el `requestJson` wrapper asi que
  abre el modal sudo automaticamente si el grace expiro.
- 4 tests pinean: serializer, render del badge, render del boton solo
  en locked, endpoint clearing the flag.

#### Backlog #5 — Argon2 tuning configurable

`ConfigurableArgon2Hasher` subclasses el bundled de Django y lee
`time_cost` / `memory_cost` / `parallelism` desde settings, alimentados
desde env vars `AMELI_APP_ARGON2_*`. Defaults igualan los de Django
(no cambia nada para deploys actuales).

El operador puede bumpear cualquier factor en hardware mas potente
sin tocar codigo; Django re-encodea cada hash en el siguiente login
exitoso (`UPDATE_LAST_LOGIN_ENCODING`), asi el bump aplica
opportunisticamente sin downtime.

3 tests: settings propagate, defaults fallback, password hash sigue
saliendo argon2.

#### Backlog #7 — Timing pad forgot-password

Antes el response body era identico para found vs not-found pero el
flow de SMTP tomaba mas tiempo en el found case, dejando un canal de
enumeracion via wall-clock.

`forgot_password_view` ahora mide el tiempo total y holda hasta
`FORGOT_PASSWORD_MIN_RESPONSE_MS` (default 1000) + jitter `~80ms`.
Verificado en server dev: tanto `identifier=admin` como
`identifier=nada` retornan en ~1.03s con la diferencia bien por
debajo del umbral medible offsite.

`FORGOT_PASSWORD_MIN_RESPONSE_MS=0` desactiva el pad (para tests que
necesitan medir velocidad).

2 tests: pad enforces the floor, pad respeta el disable a 0.

#### Backlog #4 — Suite e2e de seguridad (14 tests)

Donde los tests por-bloque pinean una feature aislada, esta suite
camina escenarios de atacante completos y pinea invariantes
observables — sobrevive a refactors porque no esta atada a la
implementacion.

Tests del archivo `tests/test_security_e2e.py`:

1. **Headers**: CSP + X-Frame + nosniff + Referrer + Permissions +
   COOP + CORP en toda response.
2. **CSP nonce**: script-src tiene nonce-, no tiene 'unsafe-inline'.
3. **Session cookie**: HttpOnly + SameSite=Lax post-login.
4. **CSRF cookie**: HttpOnly + SameSite=Lax.
5. **CSRF middleware**: POST sin token = 403.
6. **Session rotation**: session_key cambia post-login (anti-fixation).
7. **Honeypot**: bot con hp_company filled = wrong-credentials +
   audit `login_bot_detected`.
8. **N3 lockout**: user locked no autentica.
9. **Sudo escape**: cambio de password evapora el sudo de la sesion
   (joya de la corona del diseño sudo).
10. **`/django-admin/` gate**: staff sin sudo = redirect a `/admin/`.
11. **`must_change_password` trap**: flag intercepta `/admin/`,
    preferences, MFA start, session revoke.
12. **Anti-enumeration**: forgot-password body identico para found vs
    not-found (descontando el identifier echo).
13. **Audit chain**: trafico normal = OK, tampering = falla con
    `broken_id` correcto.
14. **Health/metrics allowlist**: off-list = 403, forwarded-for
    correcta = 200.

La suite corre en ~2 segundos y queda como **smoke test de seguridad
post-deploy** — green = invariantes preservadas.

#### Backlog #6 — Rotacion segura de `AUDIT_HMAC_KEY`

Antes la doc decia "no rotes" porque rotar invalidaba la chain
historica. Si la key se comprometia o la policy pedia rotacion
periodica, el operador tenia que descartar la verificabilidad del
historial. Ahora hay un path limpio.

`rotate_audit_key(from_key, to_key)`:

1. **Refuse si el chain bajo `from_key` ya esta roto**. No es
   defensa contra tampering — la rotacion no debe enmascarar
   un audit corrupto.
2. **Re-stampar cada fila chained** en orden de id dentro de un
   `transaction.atomic`. Recomputa el HMAC con la key nueva
   preservando la secuencia `prev_hmac`. Filas legacy
   (`hmac=""`) se dejan intactas.
3. **Audit-of-audit**: escribe un `audit_key_rotated` como cola
   nueva, ya firmado con la key nueva (primera fila del chain
   post-rotacion).
4. **Re-verifica** bajo la nueva key antes de retornar el
   resultado.

Si algo falla mid-walk, el `transaction.atomic` rollbackea — el
chain queda intacto bajo la key vieja.

`verify_audit_chain` ahora acepta un kwarg `key_override=` para
verificar bajo una key arbitraria sin tocar settings (lo usa el
rotate flow internamente).

Comando CLI nuevo: `ameli-app rotate-audit-key --from-key OLD
--to-key NEW`. Exit 0 si rotacion OK, exit 2 si falla. Documentado
en `OPERATIONS.md` con el recipe completo de 5 pasos (verify ->
generate -> rotate -> restart -> verify) y el caveat sobre
guardar la key vieja para verificar exportaciones historicas.

4 tests: walk limpio bajo nueva key, refuse en chain rota,
audit-of-audit emitido, identical-keys rechazado.

### Numeros del bloque

- **9 commits promocionados a `main`** (3 del 4A/4B + 6 del 4C)
- **569 tests pasando** (525 al inicio del bloque -> +44 nuevos
  tests netos)
- 2 archivos de tests nuevos
  (`test_security_hardening_block4.py` + `test_security_e2e.py`)
- 1 migracion nueva: `accounts/0008_user_locked_at_user_locked_reason`
- 0 deps Python nuevas
- 2 systemd units nuevas
- 1 modulo nuevo: `accounts/hashers.py`
- ~1500 lineas netas agregadas

### Decisiones tomadas (no re-discutirlas)

- **CSP relajada solo en `/django-admin/*`**: el admin nativo usa
  inline scripts del framework que no podemos nonce-stamp. Como ya
  esta gated por sudo + MFA + audit y solo lo usa el operador, la
  relajacion ahi es el trade-off correcto.
- **Locked-at NO es time-based**: una vez puesto, solo un admin lo
  saca. Un sustained brute-force no puede esperar a que pase y
  reintentar.
- **Threshold default 3 ventanas consecutivas**: un user real que
  realmente olvido su pass corre contra una o dos ventanas como
  maximo; tres seguidas es senial fuerte de ataque sostenido.
- **Honeypot field name `hp_company`**: lo bastante banal para que
  un bot lo intente llenar sin sospechar. No esta en la lista de
  campos comunes de password manager.
- **SMTP boot guard incluye `file` como valido**: algunos deploys
  internos quieren un outbox local en disco para review. No es
  console (que descarta a stdout) y permite el flow.
- **Permissions-Policy con `interest-cohort=()`**: el header anti-
  FLoC ya esta deprecated en Chrome pero el cost de incluirlo es
  cero y protege contra implementaciones legacy.

### Snapshot al cierre — superficie de seguridad consolidada

| Frente | Cobertura |
|---|---|
| Auth / login | Argon2 + throttle atomico por IP/user + lockout temporal + **honeypot anti-bot** |
| **Lockout** | Temporal por throttle + **permanente tras 3 ventanas; admin unlock** |
| `/django-admin/` | **Gate sudo via middleware + CSP relajada solo ahi** |
| Force change password | Middleware + modal bloqueante + redirect post-login |
| Sesion | HttpOnly + Secure + SameSite + idle renewal + cycle_key on MFA + disabled-user kick + revoke on password change |
| Sudo-mode admin | Re-auth password + MFA, grace 5 min, revoke en logout/pw-change |
| MFA | TOTP + email + recovery codes, throttle atomico, notif al titular en admin disable |
| Password change forgot | Throttle atomico por IP, mensaje en espanol, audit pre-SMTP |
| Cambio de email | Double-opt-in con confirm + alert + cancel link |
| HIBP password check | Opcional via toggle, k-anonymity |
| Audit log | Actor consistente + HMAC chain + **systemd timer horario con alert hook** |
| **Profile UX** | **Banner de alertas para MFA off, sin email, password viejo** |
| Webhooks | Removidos del Template |
| API tokens | Removidos del Template |
| Avatares | Format whitelist + pixel cap + byte cap |
| Static/media | DEBUG-gated + media auth gate |
| Headers / CSP | Nonces per-request en script-src (+ relax en `/django-admin/*`) |
| **Browser features off** | **Permissions-Policy + COOP/CORP** |
| /docs /redoc | Pin version + SRI opcional + CSP per-page con nonce + jsdelivr |
| /health /metrics | Allowlist IP opcional |
| Config | Boot guards (SECRET_KEY, ALLOWED_HOSTS, DEBUG, TRUSTED_PROXIES, **email.backend**) |

### Lecciones de la verificacion operativa de #6 (rotacion HMAC)

Durante la verificacion del recipe documentado en `OPERATIONS.md` el
operador llego a un estado donde `AUDIT_HMAC_KEY` quedo vacio en el
env file y la chain dejo de verificar. Reproducimos el desglose para
que el proximo agente / operador entienda los hallazgos y los items
de mejora pendientes.

#### Lo que paso (cronologia)

1. `verify-audit` inicial devolvio `{"ok": false, "broken_id": 482,
   "broken_reason": "hmac mismatch"}`. La chain ya estaba rota desde
   la prueba de tampering del **H6** al cierre del bloque 3 (esa
   prueba modifico el payload del row 482 a proposito y nunca se
   limpio). El operador NO advirtio esto y siguio al paso 2.

2. **Typo critico al copy-pastear**: el operador tipeo `EW_KEY=$(...)`
   en lugar de `NEW_KEY=$(...)`. La variable `$NEW_KEY` quedo vacia.
   `echo "Nueva key: $NEW_KEY"` imprimio vacio pero no se chequeo.

3. `rotate-audit-key --to-key "$NEW_KEY"` rechazo correctamente con
   `{"error": "to_key is required", "ok": false}`. **El helper se
   defendio**, no creo una chain con key vacia. Pero el operador
   tampoco se detuvo aca.

4. `sed -i "...AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY..."` se ejecuto con
   `$NEW_KEY` vacio. El env file quedo con la linea
   `AMELI_APP_AUDIT_HMAC_KEY=` (sin valor).

5. Restart del service. `verify-audit` post-restart devolvio
   `{"error": "AUDIT_HMAC_KEY is not configured; cannot verify
   chain.", "ok": false}` — la app esta corriendo sin chain
   activa (escribiendo audit rows sin hmac, las nuevas se vuelven
   "legacy" rows).

#### Hallazgos operativos

- **El helper de rotacion hizo lo correcto**: defendio contra
  `to_key` vacio y contra chain rota como pre-condicion. Si el
  operador hubiera tipeado `$NEW_KEY` con valor real, el rotate
  habria igual rechazado porque el chain bajo `from_key` ya estaba
  roto en row 482 (precondicion documentada).

- **El recipe del `OPERATIONS.md` no defiende contra `$NEW_KEY`
  vacio en el paso 4** (el sed). La rotacion fallida es transparente,
  pero el cambio del env file es "fire-and-forget". El recipe debe
  imponer un check explicito entre el rotate y el sed, y no seguir
  hasta que el operador confirme.

- **La regla "verify antes de cualquier cosa" no se aplico**. El
  recipe dice "verify the chain is clean first", pero un operador
  apurado puede saltearlo. El comando `rotate-audit-key` es el que
  defiende; el wrapper de shell del operador no.

#### Cierre del #8 (mejoras al recipe + helper)

Items 1–4 quedaron resueltos en el commit del #8. Item 5 (cleanup
del row 482) sigue en el backlog como item 9 — es operativo, no
requiere desarrollo.

1. ✅ **`rotate-audit-key` ahora reporta `next_steps`** en el JSON
   de salida cuando la rotacion sale OK. El array enumera los pasos
   exactos: actualizar el env file, restart, re-verificar.

2. ✅ **`OPERATIONS.md` reescrito con guards bash defensivos**.
   El recipe captura `OLD_KEY` desde el env file, aborta si alguna
   variable queda vacia, y enmarca la rotacion con `|| { exit 1; }`
   para que nadie siga al sed cuando el rotate fallo.

3. ✅ **Nuevo flag `--apply-env <path>`** en `rotate-audit-key`.
   Tras una rotacion OK, reescribe atomicamente la linea
   `AMELI_APP_AUDIT_HMAC_KEY=` en el archivo dado (write a tempfile
   en el mismo directorio + `fsync` + `os.replace`). Rechaza correr
   si el `to_key` esta vacio. Nuevo exit code `4` = la rotacion del
   DB salio OK pero el escribir del env file fallo (el operador
   sabe que no debe restart aun).

4. ✅ **Nuevo flag `--strict-precondition`** en `verify-audit`.
   Cuando el chain esta roto, sale con exit code `3` en vez del `1`
   generico. Permite pipelines tipo:
   ```bash
   .venv/bin/ameli-app verify-audit --strict-precondition && \
     .venv/bin/ameli-app rotate-audit-key --from-key ... --to-key ... --apply-env ...
   ```

5. ✅ **Limpieza del chain (item 9) — resuelto colateralmente**.
   Como la `OLD_KEY` se perdio cuando el env file quedo en blanco,
   no habia forma de verificar la chain historica. Se opto por el
   wipe-and-restart documentado, ver "Verificacion operativa de
   #8 + #9 en server dev" abajo.

#### Verificacion operativa de #8 + #9 en server dev (2026-06-12)

Server: `ha-report2`, ruta `/opt/ameli-app-template-dev`, commit
`321b6fa`.

Estado inicial:
- Env file con `AMELI_APP_AUDIT_HMAC_KEY=` (vacia, secuela de la
  verificacion #6).
- Chain con 516 rows firmadas bajo la `OLD_KEY` perdida, mas la
  legacy de row 482 del H6.

Pasos ejecutados y resultado:

```text
# 1. Sync al commit del #8
git fetch origin dev && git reset --hard 321b6fa
.venv/bin/ameli-app version   → AMELI App Template v0.2.0-django

# 2. Wipe completo (item 9 — ya no hay key para verificar la chain vieja)
shell -c "AuditEvent.objects.update(hmac='', prev_hmac='')"
  → wiped=516

# 3. Generar NEW_KEY y aplicar al env real
NEW_KEY=nc8sBTYrofLVESyJ1KbRWj2j2VCRCpa3RjqTnGz_ivb84rWHs6z1Rc-D5ZSeq8V7
sed -i "...AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY..."
systemctl restart ameli-app-template-dev-api.service

# 4. Verificar chain limpia
verify-audit --strict-precondition   → {"checked": 0, "ok": true}, exit=0

# 5. Forzar la primera row de la chain nueva
record_audit('block4_post_wipe_test')
verify-audit   → {"checked": 1, "ok": true}

# 6. Probar rotacion completa con --apply-env contra un env de TEST
TEST_ENV=/tmp/test-rotate.env (copia del real)
OLD_KEY=$NEW_KEY   # capturado desde el env real
NEW_KEY2=iOUTfMN9UDn8lct1FNBn9kS_e4GoceZVevbNEQnvJCzGXQRo8-N4bRttb-HQSAlb
guards OK
rotate-audit-key --from-key $OLD_KEY --to-key $NEW_KEY2 --apply-env $TEST_ENV
  → {
      "ok": true,
      "rotated": 2,
      "env_file": {"appended": false, "env_path": "/tmp/test-rotate.env", "ok": true},
      "next_steps": [4 pasos en castellano: update env, restart, verify],
      "verify_result": {"checked": 2, "ok": true}
    }
grep AMELI_APP_AUDIT_HMAC_KEY /tmp/test-rotate.env
  → AMELI_APP_AUDIT_HMAC_KEY=<NEW_KEY2>     # reemplazo atomico OK

# 7. Sincronizar el env real con la rotacion + restart + verify final
sed -i "...AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY2..."
systemctl restart ameli-app-template-dev-api.service
verify-audit   → {"checked": 2, "ok": true}
```

Hallazgos:

- `verify-audit --strict-precondition` se comporto como esperado:
  exit 0 con chain limpia, exit 3 con chain rota o sin key.
- `--apply-env` reemplazo la linea atomicamente, sin tocar el resto
  del env file ni alterar permisos (`chmod 600` se preservo).
- El JSON con `next_steps` quedo visible para el operador y elimina
  el "OK silencioso" que motivo la fuga del #6.
- Item 9 cerrado de paso: la chain en server dev queda firmada bajo
  `NEW_KEY2` desde 2 rows verificables (la primera del wipe + la
  rotacion).

Items pendientes post-verificacion: ninguno. #8 y #9 cerrados.

#### Como devolver el server dev al estado anterior (sin re-desplegar)

```bash
# Restaurar la key vieja en el env file
sudo sed -i "s|^AMELI_APP_AUDIT_HMAC_KEY=.*|AMELI_APP_AUDIT_HMAC_KEY=$OLD_KEY|" \
  /etc/ameli-app-template-dev/app.env
systemctl restart ameli-app-template-dev-api.service

# verificar — sigue saliendo "broken_id: 482" por el tampering
# original del H6, pero la chain al menos esta activa
.venv/bin/ameli-app verify-audit
```

Para limpiar el row 482 (opcional, descarta verificabilidad del
historial anterior a esa row):

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.audit.models import AuditEvent
AuditEvent.objects.filter(id__lte=482).update(hmac='', prev_hmac='')
"
.venv/bin/ameli-app verify-audit
# ahora deberia decir ok: true sobre los rows post-482
```

### Proximos bloques abiertos

Items 1, 4, 5, 6 y 7 del backlog del bloque 4 quedaron resueltos en el
4C (ver arriba). Lo que queda son items operativo/UX que no afectan la
postura de seguridad, mas las mejoras al recipe de rotacion que
aparecieron al verificarlo en el server:

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 2 | Selector de idioma en header (i18n loop) — descartado por el usuario | UX | — |

Items cerrados en esta sesion:
- **Item 8** — endurecer recipe + helper de rotacion HMAC:
  `next_steps` en la respuesta del rotate, bash guards en
  `OPERATIONS.md`, `--apply-env` en `rotate-audit-key`,
  `--strict-precondition` en `verify-audit`. Commit `321b6fa`.
- **Item 9** — wipe del chain legacy del H6 en server dev
  ejecutado durante la verificacion del #8 (la `OLD_KEY` se habia
  perdido, asi que no quedaba mejor camino). Chain ahora firmada
  bajo una nueva key con 2 rows verificables.
- **Item 3** — retry queue para emails fallidos. Nuevo modelo
  `OutboundEmail`, helper `services.send_with_retry`, worker
  `notify-once` que procesa la cola con backoff exponencial
  (1m, 5m, 15m, 1h, 6h; max 5 intentos), drop de filas
  expiradas (token de reset vencido), audits
  `email_queued_for_retry` + `email_failed_permanent`.
  Migrados a la cola: password reset y notificacion de
  `mfa_disabled_by_admin`. Los flujos que necesitan
  retroalimentacion inmediata al usuario (profile test email,
  codigos MFA durante login) siguen con `.send(fail_silently=False)`.
  Documentacion en `OPERATIONS.md` -> "Outbound email retry queue".

#### Verificacion operativa de #3 en server dev (2026-06-12)

Server: `ha-report2`, commit `b066ce5`, migracion
`accounts.0009_outboundemail` aplicada.

```text
# 1. Migracion OK
Applying accounts.0009_outboundemail... OK
OutboundEmail.objects.count() = 0

# 2. Inline success (SMTP smtp.office365.com OK)
request_password_reset('admin') -> {'ok': True, 'status': 'requested'}
queue: pendientes=0, enviados_via_cola=0   (envio inline, no toca cola)

# 3. Forzar failure: AMELI_APP_EMAIL_HOST=smtp.invalid.local
request_password_reset('admin') -> {'ok': True, 'status': 'requested'}
OutboundEmail row 1:
  status=pending, attempts=1,
  to=['hardgameinc@gmail.com'],
  last_error='gaierror: [Errno -2] Name or service not known',
  next_retry +60s

AuditEvent 527 email_queued_for_retry admin
  payload: { queue_id: 1, audit_action: password_reset_email_delivered,
             to: [hardgameinc@gmail.com], reason: 'gaierror...' }
AuditEvent 528 password_reset_requested admin
  payload: { status: 'email-sent' }   # respuesta al usuario sin alarmas

# 4. Restaurar SMTP + force next_retry=now + notify-once
notify-once -> queue: { considered:1, sent:1, requeued:0, failed:0, expired:0 }
OutboundEmail row 1 -> status=sent, attempts=1
AuditEvent 529 password_reset_email_delivered admin
  payload: { queue_id: 1, delivered_after_attempts: 2 }
verify-audit -> { checked: 7, ok: true }

Mail real con link de reset entregado a la inbox.

# 5. Programacion permanente: notifier.service
El install.sh ya renderiza ameli-app-template-dev-notifier.service
(no se enable por default — el profile dev es 'api-worker-maintenance').
Habilitado a mano:
  systemctl enable --now ameli-app-template-dev-notifier.service

Status:
  Active: active (running)
  Tasks: 2 (bash loop + sleep 30)
  journal: notify-once cada 30s con queue:{considered:0, sent:0}
```

Hallazgos:
- helper inline-then-queue funciona end-to-end con un fallo de DNS
  real (`gaierror` desde el resolver del SMTP backend);
- la respuesta al usuario nunca cambia (`status: requested`), la
  cola es completamente invisible al flow web;
- el unit notifier persistente (loop con `AMELI_APP_NOTIFIER_INTERVAL=30`)
  es la programacion recomendada — mas barato que un timer porque
  Python ya esta cacheado entre iteraciones;
- el chain audit sigue verificable post-rotate y post-drenado:
  `{ checked: 7, ok: true }`.

Considera enable-by-default del notifier en futuros installs (item
operativo, no de seguridad).

### Revision final de seguridad y calidad (cierre bloque 4)

Antes de cerrar el bloque corrimos dos pasadas independientes
(security review + code quality review) sobre los cambios de #8
y #3. Cero hallazgos criticos o altos. Aplicamos los hallazgos de
nivel medio + should-fix en un commit de hardening:

| # | Frente | Fix aplicado |
|---|---|---|
| SEC-1 | newline injection en `apply_audit_key_to_env_file` | rechazar `to_key` con `\n`/`\r`/`=` |
| SEC-2 | symlink swap en env path | rechazar `os.path.islink(env_path)` |
| SEC-4 | excepcion SMTP cruda en audit chain | solo `error_class` (nombre de la clase) en audit; el texto completo queda en `OutboundEmail.last_error` |
| SEC-5 | bodies con tokens persisten post-delivery | `body=""` y `to_emails=[]` en transicion a `STATUS_SENT`; idem para expirados |
| SEC-6 | `mfa_disabled_by_admin` sin TTL en cola | `expires_at = now+2h` |
| QUAL-1 | monkey-patch en `django._setup_complete_for_notify` | usar `django.apps.apps.ready` como sentinela canonica |
| QUAL-3 | `select_for_update(skip_locked=True)` no-op en SQLite | guard con `connection.features.has_select_for_update_skip_locked` + docstring de "1 worker on SQLite" |
| QUAL-4 | `mfa_disabled_notify_sent` pierde `actor`/`email` cuando va por cola | nuevo `OutboundEmail.audit_payload` (JSONField, migracion 0010), `send_with_retry` lo persiste, el worker hace merge al delivery audit |
| QUAL-5 | `_PasswordResetEmail` definido despues de sus callers | movido arriba del bloque de cola |
| QUAL-6 | type hints faltantes (`expires_at`, `now`) | anotados |
| QUAL-10 | thundering herd post-outage SMTP | `_email_retry_delay_seconds` con jitter `random.uniform(0.8, 1.2)` |
| QUAL-11 | magic numbers en exit codes del CLI | constantes `EXIT_OK=0 / EXIT_GENERIC_ERROR=1 / EXIT_ROTATION_REFUSED=2 / EXIT_CHAIN_BROKEN_STRICT=3 / EXIT_ENV_WRITE_FAILED=4` |
| QUAL-12 | subject sin truncar (`CharField(max_length=255)` rompe en PG) | clamp explicito en `send_with_retry` |

Diferidos (no afectan postura de seguridad, registrados como backlog
tecnico post-revision):

- Keys via env/stdin en lugar de argv (visible en `ps`/history)
- O_NOFOLLOW + lstat para env file (alternativa al refuse-symlink actual)
- Structured logging / metricas Prometheus en el worker
- Admin UI para `OutboundEmail`
- Tests adicionales: unicode bodies, concurrencia 2 workers, timezone naive en `expires_at`, `to_emails` grandes
- fsync del directorio post-`os.replace` (durabilidad ante power-loss)

Tests post-hardening: **589 verde** (1 deselected pre-existente).

### Orden recomendado para retomar

1. Resync local + servidor al hash `5286ed1`
2. Aplicar migracion:
   ```bash
   .venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
   ```
3. Si vas a deploy de prod, verificar que el env tenga:
   - `AMELI_APP_EMAIL_BACKEND=smtp`
   - `AMELI_APP_EMAIL_HOST=<server>`
   - `AMELI_APP_AUDIT_HMAC_KEY=<secret>` (opcional pero recomendado)
   - `AMELI_APP_TRUSTED_PROXIES=...` (ya obligatorio desde bloque 1)
4. Activar el timer de verify-audit:
   ```bash
   systemctl daemon-reload
   systemctl enable --now ameli-app-template-prod-verify-audit.timer
   ```
5. Si seguis: UI para desbloquear users en `/admin/` (boton en cada user
   con `locked_at`). El endpoint ya existe.

### Comandos utiles de continuidad

Verificar la chain manualmente:

```bash
.venv/bin/ameli-app verify-audit
.venv/bin/ameli-app verify-audit --from-id 1000 --to-id 2000
```

Probar el lockout permanente (cuidado, es destructivo):

```bash
# Forzar el flag
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.models import User
from django.utils import timezone
u = User.objects.get(username='tester')
u.locked_at = timezone.now()
u.locked_reason = 'manual_test'
u.save()
"
# Intentar login (debe fallar con el mensaje hard-lock)
curl -i http://10.100.100.16:18080/login/ -d 'username=tester&password=Whatever12!?'
# Desbloquear
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.services import admin_unlock_user
print(admin_unlock_user(actor_username='admin', username='tester'))
"
```

Probar el honeypot:

```bash
curl -i http://10.100.100.16:18080/login/ \
  -H 'Cookie: csrftoken=<token>' \
  -d 'csrfmiddlewaretoken=<token>&username=admin&password=AdminPass!12?Secure&hp_company=AcmeCorp'
# Esperado: misma respuesta que con password mal + audit row login_bot_detected
```

Tests:

```bash
DATABASE_URL= APP_ENV=dev .venv/bin/pytest tests/test_security_hardening_block4.py -v
```

### Archivos clave del cierre

- [`src/ameli_web/accounts/middleware.py`](../src/ameli_web/accounts/middleware.py) — `DjangoAdminSudoGateMiddleware`, headers modernos, CSP por-path
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `maybe_permanently_lock`, `admin_unlock_user`, `check_login_throttle` chequea `locked_at`
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — `_security_alerts_for`, honeypot en `TemplateLoginView.post`, `maybe_permanently_lock` despues del lockout
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — `User.locked_at`, `User.locked_reason`
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — `admin_django_admin_enter`, `admin_unlock_user`
- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — boot guard de SMTP, registro del middleware
- [`src/ameli_web/templates/accounts/login.html`](../src/ameli_web/templates/accounts/login.html) — honeypot field
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html) — banner `Alertas de seguridad`
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html) — boton `Admin nativo Django` con sudo flow
- [`deploy/systemd/ameli-app-verify-audit.service`](../deploy/systemd/ameli-app-verify-audit.service) + `.timer`
- [`docs/OPERATIONS.md`](OPERATIONS.md) — seccion "Audit chain verification (H6)"
- [`tests/test_security_hardening_block4.py`](../tests/test_security_hardening_block4.py) — 18 tests
