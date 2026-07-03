## AMELI App Template handoff (sesion Claude, 2026-07-03)

Fecha: `2026-07-03`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `dd910cc` al abrir → `3889fbd`+bump al cerrar)
Rama estable: `main` (default en GitHub; `dev` va muy adelante)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-02_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-02_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

### Estado del repo / entorno

- El repo local (Windows) estaba en un checkout viejo de `main`
  (commit inicial, huerfano tras un force-update de `origin/main`).
  Se creo `dev` local rastreando `origin/dev` (`dd910cc`) y se borro
  `main` local. `origin/main` intacto en GitHub.
- **Entorno local reconstruido**: no habia `.venv`. Se creo con
  `py -3.14` e instalo desde los **rangos** (no el lock — ver §6.1).
  Stack local: Django **6.0.6** / Pillow **12.3** / Python **3.14.6**.
  El server sigue en Django 5.2.15 / Pillow 12.2 / Python 3.13 via lock.
- Version al abrir: `v0.4.7-django`.

### Metricas al abrir (Windows local)

| Indicador | Valor |
|---|---|
| Unit tests | 1067 pass / 28 skip / **1 fail** (Windows-only, ver §6.2) |
| Ruff | 0 errores |
| Node JS tests | 13 pass |

## §2. Objetivo de la sesion

Elegido por el operador: **D-2 — UX de prompts MFA** (el `window.prompt`
/ `confirm` / `alert` nativo → input inline tipo `mfa_disable`).

## §3. Trabajo realizado

### 3.1. D-2 — re-auth MFA inline (commit `fb8e9e1`, v0.4.8)

`templates/accounts/profile.html`: las 3 acciones endurecidas contra
robo de sesion (PHASE_B A1/A2) que pedian la contrasena via
`window.prompt` pasan a **campo de contrasena inline** con toggle de
visibilidad, replicando el flujo de desactivacion que ya estaba bien:

- **Activar 2FA (app)**: input `#profile-mfa-totp-activate-password`.
- **Activar 2FA (email)**: input inline, renderizado **solo cuando hay
  email** (si no, el boton queda `disabled` como antes).
- **Regenerar codigos**: input inline + leyenda de advertencia +
  feedback `aria-live`, reemplazando el trio `confirm()`+`prompt()`+
  `alert()`.

Cada campo se limpia al exito, valida vacio con foco y muestra errores
en linea. **IDs de boton preservados** (`profile-mfa-activate`,
`profile-mfa-email-activate`) → los tests de render apilado siguen
verdes. +3 tests en `test_mfa_stacked_views.py` (campos inline
presentes, `window.prompt` ausente del body, input email oculto sin
email). El unico `confirm()` restante es el de cancelar cambio de email
(fuera de scope MFA).

### 3.2. Fix — tools de recuperacion tras regenerar (commit `9a9d7d8`)

Bug **pre-existente** aflorado en el smoke de D-2: el handler de
regenerar pintaba los codigos pero **nunca llamaba
`setupRecoveryTools()`**, dejando Copiar / Descargar / Imprimir muertos
tras un regenerado (solo funcionaban en el path de enrolamiento). Fix:
reusa `showRecoveryOrReload()`, el mismo helper que ya usan
enrolamiento app/email, para cablearlos consistente.

### 3.3. Fallback de copia en HTTP (commit `3889fbd`)

El boton Copiar usaba solo `navigator.clipboard`, gateado a **contexto
seguro** (HTTPS / localhost). En el dev server HTTP degradaba a "copia
manual". Se agrego un fallback legacy (`<textarea>` temporal +
`document.execCommand('copy')`) que corre **solo** cuando
`window.isSecureContext === false`. Un deploy HTTPS/Caddy toma la rama
de la Clipboard API moderna y **nunca ejecuta `execCommand`** → el path
viejo se auto-desactiva en prod sin flag (respuesta a la duda de
seguridad del operador).

### 3.4. Docs — quitar `sudo` de comandos de deploy (commit `4bfcaab`)

El server corre como **root** sin binario `sudo` (`sudo: orden no
encontrada`). Se quito el prefijo `sudo` de los comandos de
deploy/install/ops en los 4 docs operativos vivos: `OPERATIONS.md`,
`TLS_WITH_CADDY.md`, `BUILDING_NEW_APP.md`, `FIRST_INSTALL_DJANGO.md`
(este ultimo: `sudo -u postgres psql` → `su - postgres -c psql`). **NO**
se toco el feature "sudo mode" de la app (`services/sudo.py`, sudo
grants, `@sudo_required`, prompt de re-auth admin) ni los handoffs con
fecha / snapshots de compliance/threat.

## §4. Decisiones tomadas

1. **Bump `v0.4.7` → `v0.4.8-django`** tras validacion en servidor
   (`VERSION` + `pyproject.toml` + CHANGELOG + linea de estado de
   AGENTS.md). D-2 + los 2 fixes de recuperacion van juntos.
2. **Fallback de copia gateado por `isSecureContext`** en vez de un
   flag de config: el path legacy se apaga solo en HTTPS.
3. **Fix del regenerado** aunque era pre-existente: estaba en el handler
   que D-2 tocaba y el operador lo detecto en el smoke.
4. **Docs sudo**: solo comandos shell, no el feature. Solo docs vivos,
   no historicos.

## §5. Metricas al cierre (Windows local)

| Indicador | Valor |
|---|---|
| Unit tests | **1070 pass / 29 skip / 0 fail** |
| Ruff | 0 errores |
| Node JS tests | 13 pass |
| Mypy | limpio salvo 1 falso positivo Windows (`socket.AF_UNIX`, ver §6.1) |
| Version | `v0.4.8-django` |
| HEAD | `3889fbd` + commit del bump |

## §6. Hallazgos / findings

### 6.1. Entorno Windows del operador (nuevo)

- **mypy**: la DLL compilada (mypyc) la bloquea "Control de aplicaciones"
  de Windows (`ImportError: DLL load failed ... Una directiva de Control
  de aplicaciones bloqueo este archivo`). Fix por-venv: reinstalar puro
  Python — `pip install --no-binary mypy --force-reinstall --no-deps
  "mypy==2.1.0"`. Tras eso corre; queda **1** falso positivo
  Windows-only: `accounts/av.py: Module has no attribute "AF_UNIX"`
  (`socket.AF_UNIX` es POSIX-only; el CI Linux da 0 errores).
- **venv**: instalar desde los rangos, NO desde `requirements.lock`
  `--require-hashes` — el lock fija `uvloop` sin marcador de plataforma
  y no compila en Windows (desde los rangos, uvicorn lo omite). Los
  rangos traen Django 6/Pillow 12; suite verde en ambos stacks.

### 6.2. `test_restore_verify_rejects_corrupted_manifest` — win32 skip

El unico fail Windows-only que quedaba del 02-jul: `restore.sh` pasa a
`tar` una ruta con letra de unidad (`C:\...`) que GNU tar interpreta
como host remoto (`Cannot connect to C:`). Se le puso `skipif
sys.platform == "win32"` puntual (no de modulo: varios tests del archivo
si corren y aportan en Windows). Validado en CI Linux. Suite Windows
local ahora **0 fail**.

## §7. Roadmap actualizado

**D-2 cerrado y validado en servidor.** Version: `v0.4.8-django`.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| ~~D-2~~ | ~~UX MFA prompts~~ | — | **CERRADO 2026-07-03** (§3.1) — validado smoke navegador en `ha-report2`; bump v0.4.8 |
| Templates | Split inline JS `admin/panel.html` (~650) + `profile.html` (~500) | 2-3h | Deuda frontend (no backend) |
| D-1 | Identidad visual | 6-8h | Solo si operador decide |
| Promote | `dev → main` v0.5.0 | — | Requiere instruccion explicita |

### Pendiente OPS (sigue del 02-jul)

Sumar `Lint + Test (Python 3.13)` y `(Python 3.14)` a los required
status checks de branch protection de `main` (ver `OPERATIONS.md`
§"Branch protection"). Los 3.11/3.12 siguen gateando; los 2 nuevos aun
no. (Nota: branch protection es no-op en el plan Free privado — ver la
misma seccion.)

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama: **`dev`** (D-2 + 2 fixes de recuperacion + docs sudo; version
  `v0.4.8-django`). `main` local no existe; `origin/main` es el default.
- D-2 validado end-to-end en `ha-report2` (HTTP): activar app/email
  inline sin prompts, regenerar + Copiar/Descargar/Imprimir OK.
- `/health` en server: OK (DB, SMTP, audit chain tail 768, disco 26%).
- Entorno de dev es Windows nativo — ver §6.1 antes de correr checks.

### 8.1. Primer paso (siguiente agente)

1. **Split inline JS** de `admin/panel.html` + `profile.html`, o
2. **D-1** identidad visual (si el operador lo decide), o
3. **Promote `dev → main`** (requiere instruccion explicita).

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` solo avanza por instruccion
  explicita "milestone".
- Deploy en el server (root, sin sudo): `git fetch && git reset --hard
  origin/dev` → `.venv/bin/pip install --require-hashes -r
  requirements.lock` (no-op si no cambiaron deps) → `manage.py migrate`
  → `manage.py check` → `systemctl restart
  ameli-app-template-dev-api.service`. Solo template → el restart basta.
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self`.
- No romper la API publica de `services/` ni de `views/`.
- Correr ruff + mypy + pytest + node tests antes de cada push.
- Bump solo por cierre de fase validado en servidor.
