## AMELI App Template handoff (sesion Claude, 2026-07-02)

Fecha: `2026-07-02`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `f0b750b` al abrir)
Rama estable: `main` (default en GitHub; `dev` va 67 commits adelante)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-01_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-01_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

### Estado del repo

- `dev @ f0b750b` (sync local == `origin/dev`). Cierre del 01-jul: los 4
  splits estructurales (PC-1..PC-4) cerrados; version `v0.4.4-django`.
- **Limpieza de ramas**: se borro la rama `main` **local** (estaba 248
  commits atras de `origin/main`, contenida por completo en `dev`).
  `origin/main` intacto en GitHub como rama por defecto. Quedaron `dev`
  (actual) + `backup/pre-rollback-2026-06-25-1530` locales.
- Version: `v0.4.4-django` (sin bump esta sesion — ver §4).

### Metricas al abrir

| Indicador | Valor |
|---|---|
| Unit tests | 1060 pass / 0 fail / 18 skip (baseline 01-jul, Linux CI) |
| Ruff | 0 errores |
| Mypy | 0 errores en paquete |
| ASVS L2 | 151 PASS / 0 strict GAP |

## §2. Objetivo de la sesion

Elegido por el operador: **D-5 — pipeline de transformacion de avatar**
(resize + WebP + strip EXIF), el item top del roadmap con diseno
completo en el handoff 01-jul §7.1.

## §3. Trabajo realizado

### 3.1. D-5 — pipeline de transformacion de avatar

Nuevo `services/images.py` llamado desde `services/user.py:replace_avatar`
**despues del AV scan, antes del `.save()`**. Cada avatar guardado ahora
se normaliza:

1. `ImageOps.exif_transpose` — aplica la orientacion EXIF del celular a
   los pixeles (y quita el tag) para que se vea derecho.
2. `img.thumbnail((MAX, MAX))` — reduce a un cuadrado configurable
   preservando aspect ratio. `thumbnail` solo achica, nunca agranda.
3. Strip explicito de metadata (`exif`/`xmp`/`icc_profile`) antes del
   encode — **este paso es el que realmente elimina el GPS/PII** (ver
   §6.1) — y re-encode a WebP.

Resultado: un PNG 3 MB / 4000px → WebP ~512px de decenas de KB, sin
EXIF/GPS. Transparente para templates (`avatar_url` ya apunta al archivo).

| Archivo | Cambio |
|---|---|
| `settings/media.py` | **Nuevo** — `AVATAR_FORMAT` (`webp`/`keep`), `AVATAR_MAX_DIMENSION` (512, clamp 64-2048), `AVATAR_WEBP_QUALITY` (82, clamp 1-100). Env vars `AMELI_APP_AVATAR_*` con clamp defensivo (un valor basura no rompe un upload). |
| `settings/__init__.py` | Registra `media.py` en el orquestador (paso 6b, tras `i18n_static`). |
| `services/images.py` | **Nuevo** — `transform_avatar(uploaded_file, *, filename)` → `(ContentFile, name)` o `None`. `None` = "guardar verbatim" (operador puso `keep`, o el transform fallo → fallback sin regresar el upload). |
| `services/user.py` | `replace_avatar` pasa por el pipeline; si `transform_avatar` devuelve `None`, guarda el archivo original. |
| `services/__init__.py` | Re-exporta `transform_avatar` en la fachada plana. |
| `tests/test_avatar_transform.py` | **Nuevo** — 8 tests: resize ≤ MAX + WebP, strip EXIF/GPS (con guard anti-vacuo), orientacion aplicada, `keep` → None, no-upscale, alpha preservado, `replace_avatar` guarda `.webp` + `avatar_url` resuelve, `keep` preserva extension original. |

### 3.2. Migracion de entorno a Python 3.14

El `.venv` del proyecto estaba **roto**: su interprete base
`pythoncore-3.12-64` fue eliminado del sistema. Unico Python presente:
**3.14** (`C:\Python314`). Se reconstruyo el venv con 3.14 (renombrando
el roto a `.venv-broken-312`, borrable) e instalando desde los rangos de
`requirements.txt` + `requirements-dev.txt`.

**Consecuencia no trivial**: pip resolvio los mayores mas nuevos que los
rangos permiten (`Django<7`, `Pillow<13`): **Django 6.0.6** y **Pillow
12.3.0**, en vez de los pins del lock (5.2 / 11) que usa CI/deploy. La
suite corrio verde en ese stack — buena senal de forward-compat, pero
**se verifico contra un stack distinto al de produccion**. Ver §7 (D-6).

## §4. Decisiones tomadas

1. **Sin bump de version**. D-5 es codigo nuevo no probado en servidor
   (S-08 pendiente). Igual que PC-2, el bump espera validacion runtime en
   `ha-report2`. Version sigue en `v0.4.4-django`.
2. **Strip de metadata explicito** en vez de confiar en que el re-encode
   la borre (ver §6.1). Se elimina `exif`/`xmp`/`icc_profile` de
   `img.info` antes de `save`.
3. **Fallback a verbatim** ante cualquier fallo del transform — un
   avatar nunca se pierde por un edge case de Pillow (el form ya valido
   que decodifica).
4. **`AVATAR_FORMAT=keep`** como escape hatch para operadores que
   quieran preservar el archivo original sin re-encode.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests (Windows local, Django 6/Pillow 12) | **1061 pass / 7 fail / 18 skip / 1 error** |
| — de los cuales D-5 | 8 pass |
| Fails/error | **todos Windows-only pre-existentes, ajenos a D-5** (ver §6.2) |
| Ruff | 0 errores |
| Mypy (services/ + settings/, 26 files) | 0 errores |
| HEAD al cierre | (commit de esta sesion) |

## §6. Hallazgos / findings

### 6.1. `exif_transpose` NO borra el EXIF — el WebP encoder lo re-incrusta

`ImageOps.exif_transpose` aplica la orientacion pero **re-adjunta el
bloque EXIF (ya sin el tag de orientacion) a `img.info['exif']`**. El
encoder WebP de Pillow copia `info['exif']` / `info['xmp']` al output si
estan presentes. O sea: sin intervencion, el GPS del celular
**sobrevive** al re-encode. El fix es el `pop` explicito de esas claves
antes de `save`. El test `test_strips_exif_including_gps` lo pinnea (con
un guard que confirma que el source SI traia EXIF, para no pasar de
forma vacua).

### 6.2. 7 fails + 1 error son Windows-only pre-existentes

En Windows local (no en el CI Linux) fallan por portabilidad, no por
D-5:

| Test | Causa |
|---|---|
| `test_common_sh_slug_autodetect.py` (4) | Ejecutan scripts `.sh` via subprocess — `bash` no esta en Windows |
| `test_systemd_profile.py` (3) | Idem, dependen de shell |
| `test_backup_restore.py` (error de coleccion) | `os.geteuid()` a nivel de modulo — no existe en Windows |

Candidatos a `pytest.mark.skipif(sys.platform == "win32", ...)` en una
pasada de limpieza (mismo patron que las sesiones 30-jun/01-jul aplicaron
a otros 14). No se toco esta sesion (fuera de scope D-5).

## §7. Roadmap actualizado

**D-5 implementado** (pendiente S-08 en servidor para bump). Version:
`v0.4.4-django`.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| ~~S-08~~ | ~~Validar D-5 en `ha-report2`~~ | — | **CERRADO 2026-07-02** — `WEBP (512,512) EXIF: {}`, audit ok. Bump `v0.4.5-django`. Ver §8.05 |
| **D-6** | Migracion runtime Django 5.2→6 (+ Python 3.14 en dev) | 1-2h | Pillow ya es 12 en el lock; solo falta Django. La app YA pasa la suite en Django 6 local. Falta regen locks (hashes), subir floor `Django>=6`, CI matrix a 3.14, `pip-audit`. Ver §7.1 |
| Win-skip | `skipif` a los 7 tests Windows-only de §6.2 | 30 min | Limpieza; deja verde el run local en Windows |
| D-2 | UX MFA prompts | 45 min | Polish |
| D-4 | JS test framework | 2h | |
| Templates | Split inline JS `admin/panel.html` + `profile.html` | 2-3h | Deuda frontend |
| D-1 | Identidad visual | 6-8h | Solo si operador decide |
| Promote | `dev → main` v0.5.0 | — | Requiere instruccion explicita |

### §7.1. D-6 — migracion runtime (diseno)

El venv local ya corre `Django 6.0.6 + Pillow 12.3.0 + Python 3.14.6`
con la suite verde (salvo Windows-only). Retirado el riesgo grande
("¿arranca la app?"), falta lo mecanico:

1. `pip-compile --generate-hashes` para `requirements.lock` y
   `requirements-dev.lock` con las versiones nuevas.
2. Subir floors en `requirements.txt` (`Django>=6.0`, `Pillow>=12`) y
   `pyproject.toml` si se quiere comprometer el mayor.
3. CI matrix: anadir Python 3.14 (hoy 3.11/3.12).
4. `pip-audit` sobre los locks nuevos (0 CVEs).
5. Docs (`AGENTS.md` requires-python + testing) + verde en CI Linux.

**Riesgo**: bajo — la validacion empirica (suite verde en 6/12) ya
cubre lo que suele romper. Pillow 12 y Django 6 no rompieron ninguna
API que la app usa.

### 8.05. S-08 — ejecutado y aprobado (2026-07-02)

Ejecutado por el operador en `ha-report2 @ /opt/ameli-app-template-dev`
tras `git reset --hard origin/dev` a `da239cd`:

- **Stack real del server**: `Django 5.2.15 + Pillow 12.2.0 + Python
  3.13`. El lock YA estaba en Pillow 12 — el delta pendiente de D-6 es
  solo Django 5.2→6 (ver §7.1, actualizado).
- **Deps**: `pip install --require-hashes` → all satisfied (no-op).
  `migrate --check` sin pendientes. `check` → 0 issues.
- **Servicio**: `active` tras restart; boot sin traceback.
- **Upload en wire** (journalctl): `POST /profile/avatar/ → 302`,
  luego `GET /media/avatars/admin-f9f0275a20ff24f5.webp → 200`.
- **Archivo transformado** (el criterio central):
  `WEBP (512, 512) EXIF: {}`, 29 KB. Resize + WebP + strip GPS
  confirmados en el stack de produccion.
- **`verify-audit`**: `{"checked": 242, "ok": true}` (+17 filas vs
  baseline S-07 de 225).

**Veredicto**: D-5 preserva integridad y transforma correctamente.
Runtime aprobado → bump aplicado a `v0.4.5-django`.

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama: **`dev`** (D-5 `da239cd` + bump `v0.4.5-django` + este handoff).
- `main` local borrado; `origin/main` intacto (default GitHub).
- Version: **`v0.4.5-django`** (bump aplicado tras S-08 verde).
- D-5 validado en servidor: `WEBP (512,512) EXIF: {}`, audit ok.
- Nota dev-local: el venv del dev se reconstruyo en Python 3.14 y
  trajo Django 6.0.6 (el server sigue en 5.2.15 via lock). Suite verde
  en ambos stacks.

### 8.1. Primer paso (siguiente agente)

1. **D-6** — migracion runtime Django 5.2→6 (Pillow ya es 12 en el
   lock). Ver §7.1. La app ya pasa la suite en Django 6 local.
2. O **Win-skip** / D-2 / D-4 / templates del roadmap §7.

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` solo avanza por instruccion
  explicita "milestone".
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self`.
- No romper la API publica de `services/` ni de `views/`.
- Correr ruff + mypy + pytest antes de cada push.
- Bump solo por cierre de fase/roadmap completo validado en servidor.
- Nuevo settings module → registrarlo en `settings/__init__.py` en el
  orden correcto (D-5 lo puso en paso 6b, tras `i18n_static`).
