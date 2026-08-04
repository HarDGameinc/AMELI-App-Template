## AMELI App Template handoff (sesion Claude, 2026-08-04)

Fecha: `2026-08-04`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `7db01c1` al cierre)
Rama estable: `main` — **promovida a `v0.5.11-django`** esta sesion
Sesion previa: [`CLAUDE_HANDOFF_2026-07-23_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-23_TEMPLATE_DEV.md)

## §1. Objetivo

1. Revisar los hallazgos que la app hija **AMELI Checklist** levanto contra
   el template (`AMELI Checklist/docs/UPSTREAM_TEMPLATE_FINDINGS_2026-08-04.md`,
   8 items T-1..T-8) y arreglar los primeros.
2. Con el CI de vuelta (el pause vencia el 2026-08-01), **promover `main`** y
   cortar **v0.5.11**.

## §2. Revision de los 8 hallazgos upstream

**Los 8 verificados uno por uno contra el codigo real del template** (no se
aceptaron del reporte). Todos legitimos; las correcciones de alcance del
propio doc resultaron correctas. Estado:

| # | Hallazgo | Estado |
|---|---|---|
| **T-1** | `admin_views/users.py`: 4× `_json_body` fuera de `try` → 500 no 400 | ✅ `bd781cd` |
| **T-2** | `email_queue.py`: el exito inline no audita (solo el fallo/cola) | ❌ **falso positivo** `22a963b` |
| **T-3** | guard de `MFA_ENCRYPTION_KEY` verifica presencia, no validez | ✅ `d4b6601` |
| T-4 | `capture@` `CAPTURE_MODE` que nadie lee → doble ejecucion | pendiente |
| T-5 | `throttle.py` sliding window inseguro con `max<3`, sin advertir | pendiente |
| **T-6** | `DATABASE_URL` vacio pasa `[OK]` → SQLite en silencio | ✅ `3e31090` |
| T-7 | `decrypt_secret` nunca lanza = contrato, sin documentar | pendiente |
| **T-8** | guarda de scheme/redirect/SSRF → helper compartido | ✅ `7db01c1` |

> **T-2 resulto un falso positivo** — verificado contra los tres llamadores
> (mfa/auth_alerts/password_reset): **todos auditan el exito inline ellos
> mismos** inspeccionando `result["status"]`. El `audit_action` que se pasa
> a `send_with_retry` es solo para la entrega diferida (worker). El finding
> leyo `send_with_retry` aislado. Se dejo un comentario en el codigo para
> que nadie re-introduzca el doble-audit (lo detecto un test existente de
> MFA). La verificacion inicial confirmo el mecanismo (`send_with_retry` no
> audita inline) pero no reviso los llamadores; recien al implementarlo se
> vio que ellos si auditan. Refuerza la regla: verificar cada finding
> **entero** (incluidos los call-sites), no aceptarlo del reporte.

## §3. Fixes de esta sesion

### T-3 — `MFA_ENCRYPTION_KEY` valida formato (`d4b6601`)

El guard chequeaba `not MFA_ENCRYPTION_KEY` (presencia). Una clave no vacia
pero no-Fernet arrancaba y moria al primer uso de MFA (400 confuso, cifrado
muerto). Nuevo helper **`require_fernet_key(name, value)`** en
`settings/auth.py` (reutilizable por hijas con su propia clave); valida
siempre que este presente (dev incluido), mantiene el guard de presencia
fuera de dev. 2 tests.

### T-6 — `DATABASE_URL` vacio en prod falla ruidoso (`3e31090`)

`validate_installation.sh`: si `APP_ENV != dev` y `DATABASE_URL` vacio →
`fail_check` con el comando de remedio, en vez del `[OK]` que dejaba prod
sobre SQLite. **Lo habiamos vivido nosotros** en la aceptacion del 07-23.
El fallback SQLite sigue valido en dev. Doc de FIRST_INSTALL actualizada
(el primer install prod sin DB ahora termina en FAIL a proposito). 3 tests.

### T-8 — `ameli_app.http_safe` (`7db01c1`)

Modulo nuevo `src/ameli_app/http_safe.py` con `fetch()`: allowlist de
scheme (https por defecto), opener sin file/ftp/data/proxy handlers,
redirects que **descartan Authorization/Cookie al cambiar de origen**, y
tope de tamaño. Cierra el mecanismo por el que **Starlink en prod reenvia
el Bearer en redirects** y el SSRF que copio Checklist. Stdlib only. Las
llamadas propias del template (HIBP, github-check) van a URLs fijas y
quedan como estan. 15 tests + doc en `BUILDING_NEW_APP.md` §3.

## §4. Release v0.5.11-django (promovido a `main`)

`chore(release)` `dc78246`, PR #14 `dev`→`main`, merge `7ef7058`, tag
`v0.5.11-django`, GitHub release publicado. `main` salto de `v0.5.9` a
`v0.5.11` (absorbe v0.5.10 que quedo tagueado en `dev` sin promover + B13 +
day-2 + puertos + T-3 + T-6). Bump de los 4 archivos.

**El CI actuo como gate y destapo 3 cosas — ninguna se forzo:**

- **pip-audit**: `cryptography 49.0.0` tenia **PYSEC-2026-3552** (CVE nueva,
  dependency drift durante el pause). Bump a `50.0.0` + regeneracion del
  bloque del lock con sus 46 hashes de PyPI (`cda738f`). Sin cambios
  transitivos (cffi>=2.0.0 ya satisfecho). `requirements-dev.lock` no tenia
  cryptography.
- **CodeQL** `py/clear-text-storage`: el wizard `configure` escribia la
  password SMTP al `app.env` en claro. Se movio a un **`password_file`**
  (`d231ce0`): mejora real (fuera del env/systemd logs), alineada con la
  guia del propio template. Pero revelo que el patron inherente
  (secret-files legibles por el servicio, permisos `0640 root:grupo`
  identicos a los de `app.env`) dispara CodeQL igual → **3 alertas
  descartadas como FP documentados** (18, 19, 20; y la 21 re-fingerprint
  tras el fix de Bandit).
- **Bandit** B103: `chmod 0750` del secrets dir → `# nosec B103`
  justificado (mismo permiso que `ETC_DIR`) (`7f27ecf`).

## §5. Estado y pendientes

- `main` = **`v0.5.11-django`**; `dev` 1 commit adelante (T-8, va al
  proximo corte). **0 alertas de code scanning abiertas.**
- **CI activo de nuevo** — `main` avanza por PR con CI verde. Se elimino la
  memoria "CI pausado".
- **Hijas**: pueden `git fetch template && merge v0.5.11-django` para
  heredar B13 + day-2 + T-3 + T-6 + cryptography. T-8 (`http_safe`) esta en
  `dev`, entra en el proximo release.
- **Upstream restantes** (3): T-4, T-5, T-7 — todos "documentar-contrato +
  candado de test" (T-4 `CAPTURE_MODE`, T-5 sliding-window `max<3`, T-7
  `decrypt_secret` no-lanza). T-1 cerrado; T-2 descartado (FP). Orden en el
  doc de findings de Checklist.
- **Red multi-app** (dev01 fase 2, WebFleet) sigue **fuera del template**,
  en `NETWORK_OPS_ha-report2_2026-07-22.md` (scratchpad → infra).
