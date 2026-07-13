## AMELI App Template handoff (sesion Claude, 2026-07-13)

Fecha: `2026-07-13`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.4-django`)
Rama estable: `main` (promoviendo `v0.5.4` en esta sesion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-11_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-11_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Local `dev` estaba **33 commits detras** de `origin/dev` (ahead=0, arbol
  limpio) → **fast-forward** seguro. origin/dev traia el trabajo de las
  sesiones 10-jul y 11-jul (v0.5.2 Django 5.2.16 CVEs, v0.5.3 M3 throttle
  atomico + template-check, TLS/SSH cerrados en el host, SBOM, rotacion de
  secretos, CSP style-src).
- `dev` y `main` en `v0.5.3`, con **7 commits en `dev` sin promover** — el
  relevante: `96f6bec feat(security): drop 'unsafe-inline' from CSP
  style-src`. CI verde en el HEAD de dev; sin PRs abiertos.

## §2. Objetivo de la sesion

**Promover `dev → main` como `v0.5.4-django`** para cerrar el loop del feat
de CSP `style-src` (mejora de seguridad sin versionar ni promover) + los
docs SBOM/ops "ground-truth".

## §3. Trabajo realizado

### 3.1. Fix de test flaky (`test(sri)`, commit `4977edc`)

`test_sri_for_caches_until_mtime_changes` fallaba **solo en Windows** (pasaba
aislado y en CI Linux). Causa: `os.utime()` seguido de `write_bytes()`
reseteaba el mtime a "ahora", que en un filesystem de resolucion gruesa podia
igualar el `cached_mtime` y no invalidar la cache. Fix determinista: escribir
primero, forzar mtime distinto despues. 5/5 ×3 estable. Verificado como flake
ambiental, no regresion (solo hice fast-forward).

### 3.2. Bump `v0.5.4` + validacion en server

Contenido del release (los 7 commits sin promover + el fix del test):
- **CSP `style-src` sin `'unsafe-inline'`** (`96f6bec`): 46 `style=""` de 11
  templates → clases utilitarias en `app.css` (cero cambio visual), ultimo
  token inseguro fuera del CSP principal.
- Docs: OPERATIONS "Deployed instance — ground truth", SBOM CycloneDX,
  prompts S-09/S-10.

**Validado en `ha-report2`** (deploy a `4977edc`): `/health` →
`v0.5.3-django` OPERATIVO; `check` 0 issues; **CSP header responde
`style-src 'self' https://fonts.googleapis.com`** (sin `'unsafe-inline'`);
render 2FA/login intacto. El unico error en consola era de una **extension
del navegador** (autofill overlay) — el CSP bloqueando inyeccion de estilos
de terceros, comportamiento correcto, no de la app.

### 3.3. Pillow CVE detectado por el gate + parchado en server (`a11a897`)

Al abrir el **PR #4** (`dev → main`), el gate **`pip-audit`** detecto **5
CVEs en `pillow==12.2.0`** (PYSEC-2026-2253..2257), fix en **12.3.0** (dentro
del rango `Pillow>=11.3,<13`). Se bumpeo `requirements.lock` a `pillow==12.3.0`
con hashes frescos de PyPI (87 archivos) — **edicion manual del bloque**
(pip-compile no corre en Windows por uvloop; mismo procedimiento que el bump
de Django en v0.5.2). El `test_lockfile_hashes` valida la estructura; la
correccion de hashes se **probo en el re-deploy del server**: el
`pip install --require-hashes` descargo/instalo `pillow-12.3.0` manylinux
(hash coincidio) → edicion del lock correcta. Server ahora corre
`Pillow 12.3.0`, `/health` `v0.5.4-django` OPERATIVO. **Las 5 CVEs quedaron
parchadas en la instancia viva (que es publica sobre TLS).**

### 3.4. Promocion a `main` — DIFERIDA (billing de CI)

El re-run del CI del PR #4 (tras el fix de Pillow) fallo con **todos** los
jobs abortando en <10s: anotacion de GitHub = *"The job was not started
because recent account payments have failed or your spending limit needs to
be increased"* → **Actions bloqueado por billing** (probable: agotados los
2000 min/mes del plan Free en repo privado). **No es fallo de codigo.**

Por la regla "`main` solo por PR con CI verde", la promocion queda
**PAUSADA**. Billing confirmado: **2000/2000 min de Actions agotados**,
spending limit $0 (plan Free), **reset en ~19 dias (≈ 1-ago-2026)**.

**Decision del operador (13-jul): esperar el reset — costo $0**, sin subir
spending limit ni pagar overage. Estado: **`dev` en `v0.5.4`** (CSP + Pillow,
verde local, corriendo en server); **`main` en `v0.5.3`**; PR #4 abierto.

**Accion pendiente (proximo agente / operador, tras el reset ~1-ago o si se
sube el limite antes):** `gh run rerun` del PR #4 → esperar verde → merge
commit + tag/release `v0.5.4-django` → sync del server. Ningun agente debe
forzar el merge sin CI.

### 3.5. Hardening de la instancia dev publica — HSTS override (`8ddb0bb`)

Revision de postura de `ha-report2` (corre `APP_ENV=dev` pero **expuesto a
internet sobre TLS**). Ya estaba bien: `DEBUG=false`, cookies Secure, proxy
SSL header, claves audit+MFA reales (verificado con dump de settings). **Unico
gap: HSTS** (default `0` en dev).

**Feature en el repo (`8ddb0bb`, semántica corregida + default flip después):**
añadido `AMELI_APP_HSTS_INCLUDE_SUBDOMAINS` en `security_headers.py` — permite
controlar `includeSubDomains` app-side. **Corrección importante:** la primera
redacción decía que un host emitiendo `includeSubDomains` "rompe a los
hermanos" del dominio compartido — **es falso**. Por RFC 6797, `includeSubDomains`
extiende la política solo a los **subdominios del host que lo emite** (`dev03`
→ `*.dev03.ameli.cl`), no a hermanos (`dev02`) ni al padre (`ameli.cl`). El
footgun real es un host **padre/apex** con hijos HTTP-only, o el **preload**.
Por eso se **cambió el default a OFF (opt-in)**, igual que Django (que también
lo defaultea a False); se activa con `=true` solo si el host es dueño de todo
su subárbol. Valor no-booleano falla cerrado (raise); nunca se emite con HSTS
off. **+5 tests**, ruff limpio. Feature útil para deploys **sin** reverse-proxy
que gestione HSTS.

**Realidad en `ha-report2` (importante):** HSTS **NO lo maneja la app, lo maneja
Caddy**, por-sitio. El Caddy del host sirve tres sitios bajo `ameli.cl`
(`dev01/02/03`), cada uno con su bloque. Al intentar aplicar HSTS por `app.env`
descubrimos que el header lo inyecta Caddy (su directive `header` **reemplaza**
el del upstream), asi que el knob app-side queda sombreado en este host.

- **dev02**: ya tenia `Strict-Transport-Security "max-age=31536000; includeSubDomains"`
  (solo alcanza `*.dev02.ameli.cl`, nunca tocó a dev03).
- **dev03** (nuestra app): **no tenia HSTS**. **Cerrado 2026-07-13**: agregada la
  linea `header Strict-Transport-Security "max-age=31536000"` (SIN
  `includeSubDomains`: dev03 es hoja, no tiene subdominios propios que forzar)
  **al bloque de dev03 del Caddyfile** — solo esa linea, para no pisar los
  headers propios de la app
  (`Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, nosniff, CSP, todos
  verificados intactos post-cambio). `caddy validate` OK, `systemctl reload caddy`
  graceful. `app.env` quedo **sin** vars HSTS (fuente de verdad = Caddy).

> Cualquier cambio de HSTS en `ha-report2` va en el **bloque Caddy del sitio**
> (`/etc/caddy/Caddyfile`), no en la app. Backups con timestamp en
> `/etc/caddy/Caddyfile.bak.*`.

### 3.6. Limpieza ufw + default flip de HSTS (`2f6aeb9`)

- **Host**: borradas las 3 reglas ufw vestigiales del `18080` (LAN
  `192.168.111.0/24` + `10.100.100.0/24`, VPN `10.11.2.1`). Verificado antes
  con `ss -tlnp`: `18080` es loopback-only (`127.0.0.1`), así que eran no-ops.
  `ufw status` → sin reglas 18080.
- **Repo (`2f6aeb9`)**: revisando el feature HSTS detecté que el fundamento que
  había escrito ("includeSubDomains rompe a los hermanos") **era falso** (RFC
  6797: alcanza solo subdominios del host emisor). Corregido en código,
  mensaje de error, docstrings de tests, `SERVER_HARDENING §9` y §3.5 arriba.
  Además, por decisión del operador, **flip del default a OFF (opt-in)**, igual
  que Django. 5 tests, suite **1106 passed / 57 skipped**, ruff limpio.

### 3.7. Tests de migraciones — drift + reversibilidad (`3761d9b`)

Cerrado el gap "No Django migration tests" de `AGENTS.md`. CI ya cubría
forward-apply + drift; faltaba **reversibilidad**. `tests/test_migrations.py`:
- `test_no_missing_migrations`: `makemigrations --check` dentro de la suite
  (drift en todo entorno, no solo el job de CI).
- `test_first_party_migrations_reverse_and_reapply_cleanly`: revierte `audit`
  + `accounts` a `zero` (ejercita todos los reverse, incl. las 3 `RunPython`)
  y vuelve forward. `transaction=True` + `finally` que re-migra a head → deja
  la DB compartida limpia.

Hallazgo: **descartado** el approach de DB secundaria aislada porque las
data-migrations consultan `User.objects` sobre la conexión **default** sin
`.using()` (son single-DB, correcto para la app; no se reescriben migraciones
aplicadas). Round-trip corre sobre la default. Sin cambio de workflow (viven
en la suite pytest).

**Ampliación** (`tests/test_migration_mfa_backfill.py`): el round-trip solo
ejercita las 3 `RunPython` como no-op (dev sin clave). Agregado test directo de
la lógica de backfill de `0012_mfa_secret_encrypt` con clave: encripta filas
plaintext, salta ya-encriptadas (idempotente), reverse desencripta, no-op sin
clave. Es código sensible (secretos TOTP at-rest). Suite **1114 passed**.

### 3.8. Auditoría aria-live + anuncio de swaps de paginación

Auditada la cobertura de anuncios screen-reader (gap `AGENTS.md`). Ya estaba
bien: flash messages + banner de mantenimiento (`role=status`) y los feedbacks
JS de MFA/email/sudo. **Gap encontrado**: los swaps de paginación/filtro del
admin (`swapPanelTo`) reemplazan `innerHTML` con `aria-busy` pero **sin anunciar**
el resultado. Agregado: región live global `#a11y-live` (`role=status`,
`aria-live=polite`, `aria-atomic`) en `base.html` + helper `announce()` en
`app.js` que anuncia el resumen del panel tras cada swap. Tests:
`tests/test_a11y_live_region.py` (template, en suite normal) +
`tests/e2e/test_a11y_announce.py` (e2e, job dedicado). **Segundo gap** (misma
clase): los 4 feedbacks de acción del panel admin (mantenimiento, crear
usuario, cambiar/resetear password) actualizan `textContent` vía
`admin-panel.js` pero **no eran regiones live** → agregado `role=status
aria-live=polite` a los cuatro (sudo/perfil ya lo tenían). Verificado en vivo.
Diferido a propósito: hints de fuerza/match de password (serían ruido por
cada tecla).

> **Nota e2e**: el e2e no corre en Windows local (`SynchronousOnlyOperation`
> en el setup de DB — afecta a **todos** los e2e existentes, no solo el nuevo;
> es ambiental, corre en el job de CI Linux). Verificación local vía el test
> de template + suite completa **1109 passed / 58 skipped**, ruff limpio.

> **Verificación en vivo (browser real, runserver + 31 usuarios seed):** el
> click en "Siguiente" anuncia `"Mostrando 26–31 de 31"` en `#a11y-live`;
> volver a pág. 1 anuncia `"Mostrando 1–25 de 31"`. **La verificación atrapó
> un bug**: la primera versión usaba `requestAnimationFrame`, que **no dispara
> en tabs sin pintado/en fondo** (el anuncio se perdía). Cambiado a
> `setTimeout(50)` — más robusto para live regions y verificado funcionando.

## §4. Continuidad / backlog (opcional)

- ~~Host: limpiar reglas ufw vestigiales del 18080.~~ **HECHO** (§3.6).
- ~~Testing gap: tests de migraciones Django.~~ **HECHO** (§3.7, `3761d9b`).
- ~~Testing gap: auditoría aria-live / anuncios SR.~~ **HECHO** (§3.8).
- **Promoción `v0.5.4 → main`**: DIFERIDA hasta el reset de CI (~1-ago) o subir
  el spending limit. PR #4 abierto, MERGEABLE, checks fallando por billing (no
  código). No forzar merge sin CI verde.
- **Roadmap restante (opcional, per `DECISIONS.md` + `AGENTS.md`):**
  - Testing gaps abiertos: auditoría de `aria-live`/screen-reader; unit tests
    JS de DOM-wiring (jsdom); visual regression. Todos **low priority** (ver
    `TECH_EVOLUTION.md`).
  - **Model C** del update-channel (`ameli-core` + Dependabot, `DECISIONS.md`
    #7): el canal más fuerte pero refactor grande; diferido hasta que la flota
    lo justifique.
  - Django LTS: revisitar en 6.2 (~dic-2026), `DECISIONS.md` #1.

## §5. Restricciones criticas (vigentes)

- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde +
  merge commit + tag (flujo en `RELEASE.md`).
- Deploy/ground-truth del server en `OPERATIONS.md` → "Deployed instance —
  ground truth" (servicio `ameli-app-template-dev-api.service`, loopback
  `127.0.0.1:18080` detras de Caddy TLS en `dev03.ameli.cl:18480`). No hay
  `sudo` (root).
- Tests requieren `APP_ENV=dev`. Suite completa + ruff antes de push. Bump
  solo tras validar en server.
