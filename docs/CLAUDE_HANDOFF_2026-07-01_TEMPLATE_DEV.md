## AMELI App Template handoff (sesion Claude, 2026-07-01)

Fecha: `2026-07-01`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `699303a` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 47 commits atras)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-30_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-30_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

### Estado del repo

- `dev @ 699303a` (sync local == origin). Cierre del 30-jun: PC-1 cerrado
  completo (steps 2-8), bump a `v0.4.1-django`, servidor `ha-report2`
  corriendo la nueva version, S-04 aprobado.
- `main @ 4b36607`, **47 commits atras** de `dev`.
- Version: `v0.4.1-django`.
- `services/` package: 10 modulos por dominio; `__init__.py` residual con
  retention/reporting/auth-alerts/email-change (1104 lineas).

### Metricas al abrir

| Indicador | Valor |
|---|---|
| Unit tests | 1013 pass / 11 fail (Windows pre-existentes, no regresion) |
| E2E tests | 4/4 (no tocado) |
| Coverage | 85% (floor pinned) |
| Ruff | 0 errores |
| Mypy | 0 errores en codigo del paquete (`av.py` reporta 1 error Windows-only pre-existente) |
| ASVS L2 | 151 PASS / 0 strict GAP (sin cambios desde 2026-06-16) |
| Servidor `ha-report2` | `v0.4.1-django`, healthchecks verdes, audit chain integro |

### Archivos con deuda estructural conocida

| Archivo | Lineas | Estado |
|---|---|---|
| `services/__init__.py` | 1104 | Residual PC-1 — dominios candidatos a extraer |
| `accounts/views.py` | 1267 | PC-2 pendiente |
| `admin_views.py` | 745 | PC-3 pendiente |
| `settings.py` | 746 | PC-4 pendiente (mecanico) |

## §2. Objetivo de la sesion

> **Nota de scope**: la sesion arranco con A+B y se extendio a lo largo
> del dia hasta completar los 4 splits estructurales. Alcance final:
> **A (PC-1 cleanup) → B (PC-2 views) → coverage/CI cleanup → PC-3
> admin_views → PC-4 settings → roadmap D-5 (imagenes)**. Cada frente
> con su S-0X en servidor y bump. Detalle cronologico en §3 y §8.

Elegido por el operador (arranque): hacer **A (PC-1 cleanup)** y luego
**B (PC-2 — split de `accounts/views.py`)** en la misma sesion.

**A. PC-1 cleanup** — Extraer los 4 dominios residuales de
`services/__init__.py` para dejarlo como puro re-export:
- retention sweep (`run_retention_sweep`, `_prune_audit_with_anchor`)
- audit reporting (`summarize_*`, `serialize_audit_event`,
  `paginate_audit_for_admin`, `filtered_audit_queryset`,
  `list_recent_audit_entries`, `_audit_queryset_for_filters`,
  `_display_tone_for_action`)
- auth-failure alerts (`_auth_failures_alert_cooldown`,
  `_send_auth_failures_alert`, `_maybe_alert_for_auth_failures_burst`)
- email-change double-opt-in flow (`_hash_email_change_token`,
  `_build_email_change_urls`, `_build_public_base_url`,
  `_send_email_change_confirmation`, `_send_email_change_alert`,
  `request_email_change`, `_find_email_change_request`,
  `confirm_email_change`, `cancel_email_change`, `pending_email_change_for`)

**B. PC-2** — Split `accounts/views.py` (1267 lineas). Estrategia
incremental como PC-1: identificar dominios cohesivos y extraerlos uno
por uno. Se define el plan al terminar A.

## §3. Trabajo realizado

### 3.1. PC-1 cleanup (commit `0268300`)

Extraidos los 4 dominios residuales de `services/__init__.py`:

| Modulo nuevo | Lineas | Contenido |
|---|---|---|
| `services/retention.py` | 194 | `run_retention_sweep`, `_prune_audit_with_anchor` |
| `services/reporting.py` | 286 | `summarize_users`, `summarize_email_queue`, `serialize_audit_event`, `list_recent_audit_entries`, `_audit_queryset_for_filters`, `paginate_audit_for_admin`, `filtered_audit_queryset`, `_display_tone_for_action` |
| `services/auth_alerts.py` | 189 | `AUTH_FAILURES_ALERT_COOLDOWN_HOURS_DEFAULT`, `_auth_failures_alert_cooldown`, `_send_auth_failures_alert`, `_maybe_alert_for_auth_failures_burst` |
| `services/email_change.py` | 302 | `EMAIL_CHANGE_TTL_HOURS_DEFAULT`, `EMAIL_CHANGE_TOKEN_BYTES`, `_hash_email_change_token`, `_build_email_change_urls`, `_build_public_base_url`, `_send_email_change_confirmation`, `_send_email_change_alert`, `request_email_change`, `_find_email_change_request`, `confirm_email_change`, `cancel_email_change`, `pending_email_change_for` |

`services/__init__.py` paso de 1104 a ~200 lineas — ahora **puro re-export**.
`EmailChangeRequest` (modelo) tambien se re-exporta desde `services/__init__.py`
porque `views.py:email_change_cancel_self_view` lo importa por la fachada
plana (`from .services import EmailChangeRequest`). Preserva back-compat.

Fix colateral: `tests/test_code_review_fixes_20260615.py` parcheaba
`ameli_web.accounts.services.timezone.now`. Como `timezone` ya no es
import top-level en `__init__.py`, el patch se re-apunto a
`ameli_web.accounts.services.throttle.timezone.now` (el modulo donde
`_read_throttle_counter_sliding` realmente lee el reloj).

### 3.2. PC-2 (commit `94ce941`)

Split de `accounts/views.py` (1267 lineas) a `accounts/views/` package
con 8 modulos por dominio + `__init__.py` re-export:

| Modulo | Lineas aprox | Contenido |
|---|---|---|
| `views/_common.py` | 42 | PENDING_MFA session keys, User, `_expects_json`, `_json_body`, `_json_error`, logger |
| `views/auth.py` | ~410 | `TemplateLoginView`, `logout_view`, `_clear_pending_mfa`, `_pending_mfa_user`, `verify_mfa_view`, `verify_mfa_resend_view` |
| `views/profile.py` | ~350 | `_pending_email_change`, `_security_alerts_for`, `profile_view`, `update_preferences`, `send_profile_test_email_view`, `update_avatar`, `delete_avatar_view` |
| `views/password.py` | ~285 | `change_password_view`, `_build_public_base_url`, `forgot_password_view`, `reset_password_view` |
| `views/account.py` | ~120 | `delete_my_account_view` |
| `views/sessions.py` | ~120 | `revoke_other_sessions_view`, `revoke_session_view`, `admin_session_json` |
| `views/mfa.py` | ~225 | 8 MFA endpoints |
| `views/email_change.py` | ~210 | 4 email-change endpoints |
| `views/__init__.py` | 55 | Puro re-export para preservar `views.X` en urls.py |

Ajustes derivados:
- Ruff `--fix --unsafe-fixes` limpio 349 F401 (los submodulos heredaron
  un header permisivo comun que luego se poda).
- Los `from .services` / `.models` / `.permissions` / `.forms` /
  `. import mfa` (lazy dentro de funciones) se re-escribieron a `from ..`
  porque el nivel de anidamiento cambio.
- `pyproject.toml` `[[tool.mypy.overrides]]` extendido con el patron
  `ameli_web.accounts.views.*` para que los submodulos hereden la
  supresion de `union-attr` que el views.py monolito tenia.
- `_build_public_base_url` re-exportado desde `views/__init__.py` porque
  `tests/test_password_reset_host_injection.py` lo importa por la
  fachada plana.

## §4. Decisiones tomadas

1. **PC-1 cleanup + PC-2 en 2 commits separados**, no bundle. Cada uno
   toca un area distinta del codigo y facilita `git blame`.
2. **`views/` package con `__init__.py` re-export** (no `views.py` +
   `views/` dual, no `__all__`). Misma estrategia que PC-1 —
   consistencia total.
3. **NO extraer PC-3 (`admin_views.py`)** en esta sesion. El operador
   pidio solo A+B; PC-3 queda para proxima sesion.
4. **Versionado**: NO bumpear a `v0.4.2-django`. PC-2 cierra un roadmap
   grande pero el codigo de `views/` NO se ha probado en servidor todavia
   (S-05 pendiente). El bump espera hasta que S-05 confirme runtime OK.

## §5. Metricas al cierre

| Indicador | Antes | Despues |
|---|---|---|
| Unit tests | 1013 pass / 11 fail | 1012 pass / 12 fail (1 race Windows en `test_breaker_transitions_to_half_open_after_cooldown`, NO regresion) |
| Ruff | 0 errores | 0 errores |
| Mypy | 0 errores en paquete (`av.py` Windows) | 0 errores en paquete (idem) |
| `services/__init__.py` lineas | 1104 | ~200 (**puro re-export**) |
| `accounts/views.py` lineas | 1267 | 0 (**convertido a paquete `views/`**) |
| Modulos `services/` | 10 | **14** |
| Modulos `views/` | 0 (era single file) | **9** |
| Commits del dia | — | 2 (PC-1 cleanup, PC-2) |
| HEAD al cierre | `699303a` | `94ce941` |
| Version | `v0.4.1-django` | `v0.4.1-django` (sin bump — pendiente S-05) |

## §6. Hallazgos / findings

### 6.1. Ruff `--fix --unsafe-fixes` es idempotente pero puede reformatear

En PC-1 cleanup, `ruff --fix` expandio los imports de `services/__init__.py`
a un `from X import (Y as Y,)` por cada simbolo, destrozando la
legibilidad. Solucion: agregar `# ruff: noqa: I001` al archivo y
re-escribirlo consolidado.

En PC-2 el mismo patron aparecio en `views/__init__.py`; misma
solucion.

### 6.2. mypy overrides son sensibles a package vs module

`[[tool.mypy.overrides]] module = ["ameli_web.accounts.views"]` cubre
`views.py` pero NO `views/*.py`. Cuando un file monolitico se convierte
en package, el operador debe extender el patron a `views.*`.

### 6.3. Lazy imports relativos cambian de nivel al mover a subpackage

`from .services import X` en `views.py` (nivel 1) se rompe cuando el
archivo se mueve a `views/password.py` (nivel 2 relativo al package
padre). Cada lazy import necesita `..services`. Ruff `--fix` NO
detecta esto — corrio manualmente con un script Python.

## §7. Roadmap actualizado

**PC-1/2/3/4 CERRADOS** — los 4 splits estructurales grandes (services,
views, admin_views, settings) son paquetes por dominio. No queda ningun
monolito de backend. Version actual: `v0.4.4-django`.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| **D-5** | **Pipeline de transformacion de avatar** (resize + WebP + strip EXIF) | 1-1.5h | Ver §7.1 — Pillow ya esta instalado; sin deps nuevas |
| D-2 | UX MFA prompts | 45 min | Polish |
| D-4 | JS test framework | 2h | |
| Templates | Split inline JS de `admin/panel.html` (~650) + `profile.html` (~470) | 2-3h | Deuda frontend (no backend) |
| D-1 | Identidad visual | 6-8h | Solo si operador decide |
| Promote | `dev → main` v0.5.0 | — | Requiere instruccion explicita del operador |

### §7.1. D-5 — Pipeline de transformacion de avatar (diseno)

**Problema**: hoy `replace_avatar` ([`services/user.py:95`](../src/ameli_web/accounts/services/user.py))
guarda el archivo tal cual llega. La validacion (`forms.py`) solo pone
techos (3 MB, 4096 px/lado, anti-bomb) pero NO transforma. Un avatar se
muestra chico pero se sirve verbatim: un PNG de 3 MB / 4000px queda en
disco y se descarga entero en cada request sin cache. Ademas el EXIF
(GPS del celular) queda embebido = fuga de PII.

**Propuesta**: nuevo `services/images.py` (mismo patron de dominios de
PC-1..PC-4), llamado desde `replace_avatar` **despues del AV scan,
antes del `.save()`**:

1. `ImageOps.exif_transpose(img)` — corrige orientacion de fotos de celular.
2. `img.thumbnail((MAX, MAX))` — resize preservando aspect ratio.
3. Re-encode a WebP (quality configurable) — el re-encode **borra el
   EXIF/GPS** naturalmente (privacidad + tamano).
4. Guardar los bytes transformados con extension `.webp`.

Resultado esperado: 3 MB PNG 4000px → ~50-150 KB WebP 512px (~95% menos
storage + bandwidth). Transparente para templates (el `<img>` ya apunta
a `avatar_url`).

**Settings (patron template, env con defaults sanos)**:
- `AMELI_APP_AVATAR_MAX_DIMENSION` (default 512) → iria en `settings/i18n_static.py` o un nuevo `settings/media.py`.
- `AMELI_APP_AVATAR_FORMAT` (default `webp`, o `keep` para no re-encodear).
- `AMELI_APP_AVATAR_WEBP_QUALITY` (default 82).

**Tests a cubrir**: PNG grande → WebP chico y ≤ MAX px; EXIF-con-GPS →
sin EXIF tras transform; orientacion EXIF aplicada; `keep` no re-encodea;
imagen ya chica no se agranda; la extension del archivo guardado cambia
a `.webp` y `avatar_url` sigue resolviendo.

**Decisiones abiertas para cuando se implemente**:
- Always-on vs opt-in: recomendacion always-on para avatares (son
  display-only, lossy es apropiado), exponiendo los knobs de arriba.
- WebP vs preservar formato original: WebP gana en tamano, soporte
  universal en navegadores 2026. `keep` como escape hatch.

**Complementario (ya documentado, NO es codigo de la app)**:
`docs/TLS_WITH_CADDY.md` § "Compresion + cache de estaticos y media"
cubre servir `/media` + `/static` directo desde Caddy con brotli +
`Cache-Control`. Reduce el costo de *servir*; D-5 reduce el costo de
*almacenar/generar*. Las dos son complementarias.

## §8. Continuidad — para el proximo agente

### 8.0. Estado snapshot al cierre (FINAL — actualizado 2026-07-01)

- Rama: **`dev @ a7592e1`** (local == `origin/dev`, pusheado).
- `main @ 4b36607`, **66 commits atras** de `dev` (sin tocar).
- Version: **`v0.4.4-django`** (confirmada en runtime en `ha-report2`).
- Unit suite: **1060 pass / 0 fail / 18 skip** (14 skipif Windows + 4 e2e opt-in).
- ruff: **0 errores**. mypy: **0 errores** (salvo `av.py` AF_UNIX, Windows-only).
- Coverage total: **88%**; paquete `views/` en **96%**.
- **4 splits estructurales cerrados** — no queda monolito de backend:
  - `services/` — 14 modulos (PC-1)
  - `views/` — 9 modulos (PC-2)
  - `admin_views/` — 10 modulos (PC-3)
  - `settings/` — 10 modulos (PC-4)
- Servidor `ha-report2 @ /opt/ameli-app-template-dev`: corriendo
  `v0.4.4-django`, S-05/S-06/S-07 aprobados.

### 8.05. S-05 — ejecutado y aprobado (2026-07-01)

Ejecutado en `ha-report2 @ /opt/ameli-app-template-dev` tras pull a `1fe655d`:

- **Boot**: servicio `active (running)` en <1s tras restart; sin
  traceback, sin `ImportError` a pesar del split masivo (~600 lineas
  de views movidas + lazy imports re-anclados).
- **Imports por shell**: 29 view symbols accesibles via
  `from ameli_web.accounts import views` — todas las funciones que
  `accounts/urls.py` usa via `views.<name>`.
- **Rutas publicas** (GET sin cookie): `/`, `/login/`, `/login/forgot/`,
  `/docs` → 200 todas.
- **Rutas privadas** (GET sin cookie): `/profile/`, `/profile/password/`,
  `/profile/delete-account/` → 302 (redirect a login) todas.
- **Browser (manual)**: login normal, `/profile/` tabs, cambio de
  preferencias, `/login/forgot/` → confirmado OK por el operador.
- **`ameli-app verify-audit`**: `{"checked": 225, "ok": true}` (+19
  filas vs baseline pre-S-05).

**Veredicto**: PC-1 cleanup + PC-2 preservan comportamiento identico
al monolito. Runtime aprobado para bump.

### 8.1. Primer paso (siguiente agente)

Los 4 splits estructurales estan cerrados y validados en servidor. El
proximo agente elige del roadmap (§7). Opciones, en orden sugerido:

1. **D-5 — pipeline de transformacion de avatar** (resize + WebP + strip
   EXIF). Diseno completo en §7.1; Pillow ya esta instalado. ~1-1.5h.
   Mismo patron de dominios que PC-1..PC-4 (nuevo `services/images.py`).
2. **Promote `dev → main` v0.5.0** — con los 4 PCs cerrados, `dev` esta
   66 commits adelante de `main`. Buen momento para milestone con tag
   limpio. **Requiere instruccion explicita del operador** (regla vigente).
3. **D-2 / D-4 / templates inline JS** — polish frontend + testing.

Nota: si se retoma servidor, la version corriendo es `v0.4.4-django`
(pull ya hecho). No hay pasos pendientes de deploy.

### 8.06. S-05 pasado, bump aplicado (commit `11deef0`)

S-05 se aprobo (ver §8.05). Se aplico el bump a `v0.4.2-django`
(`VERSION`, `pyproject.toml`, entrada en `CHANGELOG.md`). Confirmado
en runtime en `ha-report2` — `/health` devuelve `version: v0.4.2-django`.

### 8.07. Cierre de cobertura en views/ (commit `bc55df8`)

El operador reviso los logs de CI (`Lint + Test` Python 3.11/3.12) y
detecto que el reporte de coverage por-archivo (visible por primera
vez tras el split PC-2, antes enterrado en un unico numero para
`accounts/views.py`) mostraba 5 modulos bajos: `sessions.py` 48%,
`account.py` 55%, `mfa.py` 70%, `email_change.py` 74%, `profile.py` 78%.

No era una regresion de PC-2 — las ramas nunca estuvieron testeadas,
solo quedaban invisibles al estar todas juntas en un solo archivo.

Se agregaron/extendieron 5 archivos de test:

| Archivo | Cambio | Cobertura resultante |
|---|---|---|
| `tests/test_profile_session_revoke_views.py` (nuevo) | HTTP tests para `revoke_other_sessions_view` / `revoke_session_view` — antes solo se probaban indirectamente via interceptacion de middleware | `sessions.py`: 48% → **100%** |
| `tests/test_hardening_20260615.py` (extendido) | JSON malformado, password vacio/incorrecto, form-POST no-JSON para `delete_my_account_view` | `account.py`: 55% → **100%** |
| `tests/test_mfa_view_error_paths.py` (nuevo) | JSON malformado parametrizado en los 8 endpoints MFA, `mfa_confirm_view` (TOTP confirm, CERO cobertura previa), success de `mfa_start_view`, wrong-password en disable generico + email-disable | `mfa.py`: 70% → **98%** |
| `tests/test_email_change_double_opt_in.py` (extendido) | `email_change_cancel_view` (link publico de alerta, CERO cobertura previa), token invalido en confirm, "sin pending" 404 en cancel-self, JSON malformado | `email_change.py`: 74% → **95%** |
| `tests/test_profile_view_gaps.py` (nuevo) | `?partial=sessions`, GET-405/JSON malformado/form invalido en `update_preferences`, form invalido + JSON-success en `update_avatar`, `delete_avatar_view` (CERO cobertura previa) | `profile.py`: 78% → **93%** |

**Suite**: 1013 → **1058 pass** (+45 tests), mismos 11 fail
pre-existentes de Windows. Coverage total: 86% → **88%**.

**Sin bump de version** — es cierre de deuda de tests surgida de
PC-2, no una fase de roadmap.

**Lo que queda sin cerrar (bajo valor, requiere mocking pesado)**:
- `mfa_email_start_view` / `email_change_request_view` / `send_profile_test_email_view`:
  rama `except Exception` generica de fallo SMTP (necesita mockear
  `send_with_retry`/`.send()` para forzar una excepcion no-ValueError).
- `profile.py`: rama de "password con mas de N dias" en
  `_security_alerts_for` (requiere fijar `password_changed_at` en el
  pasado) y dos `try/except` de `file.seek()` no-seekable (edge case
  de streams no reposicionables).

Pendiente opcional para una sesion futura si se quiere cerrar el 100%
en los 5 modulos.

### 8.08. Cierre de gaps residuales + Windows-only skipif

Dos frentes cerrados en la misma ronda:

**a) 11 fails pre-existentes de Windows → 0.**

Cada uno depende de comportamiento Linux/POSIX sin equivalente en
Windows. Marcados con `pytest.mark.skipif(sys.platform == "win32", ...)`
para que sigan corriendo sin cambios en el CI Linux (donde vive el
deploy). Archivos tocados:

| Test | Motivo del skip |
|---|---|
| `test_clamd_unix_clean_verdict` | `AF_UNIX` no existe en el `socket` de Windows |
| `test_clamd_unix_infected_extracts_signature` | idem |
| `test_scan_bytes_treats_missing_unix_socket_as_unreachable` | idem |
| `test_backup_sh_pg_url_strip.py` (**7 tests**, module-level `pytestmark`) | Todos usan `_strip_driver()` que invoca `sed` real via subprocess |
| `test_backup_fail_helper_honours_explicit_exit_code` | Requiere bash script |
| `test_apply_audit_key_to_env_file_refuses_symlink` | `symlink_to` requiere privilegio elevado en Windows |
| `test_apply_audit_key_to_env_file_rejects_symlink_at_syscall_level` | idem |
| `test_apply_audit_key_to_env_file_fsyncs_parent_dir` | Identidad `st_dev/st_ino` de POSIX no aplica en Windows |

Un test resulto ser un bug de portabilidad, no incompatibilidad:
`test_autodetect_prefers_config_yaml_over_example` chequeaba
`"/config/app.yaml"` en lugar de `os.sep.join(...)`. Corregido — pasa
en ambas plataformas.

**Nota sobre el conteo**: el `pytestmark` a nivel de módulo del
`test_backup_sh_pg_url_strip.py` alcanza los 7 tests del archivo, no
solo los 3 que aparecían como FAILED en el log anterior (los otros 4
también fallaban silenciosamente porque `_strip_driver()` era su
dependencia común — el log truncó a los primeros 3). El total real
de tests que ahora skippean en Windows es 14 (no 11), lo que explica
`1060 pass / 18 skip` en la corrida final (14 nuevos + 4 e2e).

**b) Gaps residuales de bajo valor cerrados.**

Nuevos tests que ejercen las ramas "generic Exception" (SMTP) y los
edge cases pendientes:

| Test agregado | Cierra |
|---|---|
| `test_send_profile_test_email_view_maps_smtp_exception_to_502` | `profile.py` líneas 219-223 |
| `test_email_change_request_endpoint_maps_smtp_exception_to_502` | `email_change.py` líneas 43-45 |
| `test_mfa_email_start_view_maps_smtp_exception_to_502` | `mfa.py` líneas 150-152 |
| `test_update_avatar_swallows_seek_exception_on_non_seekable_stream` | `profile.py` líneas 258-259, 263-264 (proxy no-seekable) |
| `test_security_alerts_flags_password_age_over_max` | `profile.py` rama `age_days > max_age` en `_security_alerts_for` (setear `date_joined` en el pasado — no existe `password_changed_at` como field) |

**Suite**: 1058 → **1060 pass, 0 fail, 18 skip** (14 nuevos skipif Windows + 4 e2e opt-in). El commit `604ffe2` reporta "1063 pass" por un typo — el numero correcto es 1060; ver "Nota sobre el conteo" arriba. Los 11 anteriores ahora
skip explícito en Windows). Coverage sigue en 88% total, pero las
ramas SMTP y el edge de seek quedaron cubiertos.

### 8.09. PC-3 — split `admin_views.py` (commit `a5e37fc`)

Mismo patron que PC-2: `ameli_web/admin_views.py` (745 lineas) →
paquete `ameli_web/admin_views/` con 10 modulos + `__init__.py`
re-export. `ameli_web/urls.py` no cambia (usa `admin_views.<name>`).

| Modulo | Contenido |
|---|---|
| `_common.py` | Decoradores (`superadmin_required`, `sudo_required`), constantes `*_PER_PAGE_COOKIE`, helpers (`_expects_json`, `_json_body`, `_json_error`, `_is_fetch_request`) |
| `panel.py` | `admin_panel` (HTML dashboard) |
| `users.py` | `admin_users`, `admin_update_user`, `admin_disable_user_mfa`, `admin_reset_user_password`, `admin_change_password`, `admin_unlock_user` |
| `audit.py` | `admin_audit` |
| `maintenance.py` | `admin_maintenance_toggle`, `admin_maintenance_status` |
| `metrics.py` | `admin_email_queue_metrics` |
| `sessions.py` | `admin_sessions`, `admin_revoke_session` |
| `exports.py` | `_AUDIT_EXPORT_COLUMNS`, `_USERS_EXPORT_COLUMNS`, `_csv_safe`, iterators + `admin_audit_export`, `admin_users_export` |
| `sudo.py` | `admin_sudo`, `admin_sudo_email_code`, `admin_sudo_status`, `admin_django_admin_enter` |

**Ajustes derivados**:
- Ruff `--fix --unsafe-fixes` limpio 318 F401 (headers permisivos comunes).
- `pyproject.toml` `[[tool.mypy.overrides]]` extendido con
  `ameli_web.admin_views.*` para que los submodulos hereden la
  supresion (`union-attr`, `call-arg`, etc.) que el monolito tenia.
- `_csv_safe` re-exportado desde `admin_views/__init__.py` porque
  `tests/test_security_hardening_block1.py` lo importa por la
  fachada plana.

**Fix de regresion durante la verificacion** (bug del script de
extraccion, no de PC-3 per se): mi primera version del decorador
`sudo_required` en `_common.py` retornaba `_json_error("sudo required",
status=403)`. El original retornaba `JsonResponse({"ok": False,
"error": "sudo required", "need_sudo": True, "sudo_url": "/admin/sudo/"},
status=401)` — ese payload especifico permite a la UI prompt-and-retry
transparente. Dos tests de seguridad
(`test_admin_write_without_sudo_returns_need_sudo`,
`test_enter_django_admin_endpoint_requires_sudo`) pinnearon la
forma exacta y fallaron; se restauro el codigo original antes del push.

**Suite tras el fix**: 1060 pass / 0 fail / 18 skip. Ruff / mypy clean.

### 8.10. S-06 aprobado + bump a `v0.4.3-django`

**S-06** ejecutado en `ha-report2 @ /opt/ameli-app-template-dev` tras
pull a `ca74d3e`:

- **Boot**: `active (running)` en <1s tras restart; sin traceback a
  pesar del split de 745 lineas + los 10 modulos nuevos.
- **Imports por shell**: 25 admin_views symbols accesibles via
  `from ameli_web import admin_views` — todas las funciones + los 2
  decoradores + las 3 constantes `*_PER_PAGE_COOKIE` que
  `ameli_web/urls.py` no necesita pero externos podrian.
- **Rutas privadas (GET sin cookie)**: `/admin/`, `/admin/users`,
  `/admin/audit`, `/admin/sessions`, `/admin/maintenance/status/`,
  `/admin/metrics/email-queue`, `/admin/sudo/status/` → 302 todas
  (redirect a login, comportamiento intacto).
- **Browser (manual, confirmado por operador)**: reset password
  desde `/admin/`, requerir 2FA para un user, forzar cambio de
  contrasena — todas las acciones pasan por
  `superadmin_required` + `sudo_required` y funcionan.

**Bump a `v0.4.3-django`** aplicado (`VERSION`, `pyproject.toml`,
`CHANGELOG.md` con entrada consolidada PC-3 + CI cleanup).

**Nota sobre el smoke test 3 (sudo_required)**: el status devolvio
`302` en lugar de `401`. Es un falso negativo del test, no un bug de
PC-3: `bootstrap_superadmin` crea el user con
`must_change_password=True` por default, y `MustChangePasswordMiddleware`
intercepta antes de que `sudo_required` ejerza. El fix real del
decorador esta cubierto por
`test_admin_write_without_sudo_returns_need_sudo` y
`test_enter_django_admin_endpoint_requires_sudo` (ambos verdes en
suite local + CI Linux).

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` solo avanza por instruccion
  explicita "milestone".
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self` (cierra cookie-thief).
- No revertir `MustChangePasswordMiddleware` (`/profile/` NO en
  `_ALLOWED_EXACT`).
- No relajar `OperationalError → fail-CLOSED` en
  `MaintenanceModeMiddleware`.
- No romper la API publica de `services/` ni de `views/`: todo debe
  seguir importable como `from ameli_web.accounts.services import X` /
  `from ameli_web.accounts.views import X`.
- Correr ruff + mypy + pytest antes de cada push.
- No instalar Playwright/chromium en el servidor.
- No promover `dev → main` sin instruccion explicita del operador.
- Convencion de versionado: bump solo por cierre de fase/roadmap
  completo, no por commit individual. Ultimo bump: `v0.4.1-django` con
  el cierre de PC-1 (commit `8be7be0`).
- Al mover archivos a un subpaquete, ajustar SIEMPRE los lazy imports
  relativos (`.` → `..`) y los patrones de `[[tool.mypy.overrides]]`.
  El fix suele ser un `--fix` de ruff + un pase manual con sed/python
  sobre los lazy imports.
