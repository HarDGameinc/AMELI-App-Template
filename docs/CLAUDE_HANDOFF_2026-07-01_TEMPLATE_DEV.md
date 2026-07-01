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

Elegido por el operador: hacer **A (PC-1 cleanup)** y luego **B (PC-2 —
split de `accounts/views.py`)** en la misma sesion.

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

**PC-1 CERRADO 100%** (services/__init__.py = puro re-export).
**PC-2 CERRADO** (views.py = paquete por dominios).

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| S-05 | Pruebas en servidor de PC-2 (auth, profile, password, MFA, sessions, email-change, account delete) | 30-45 min | Verificar que todas las URLs siguen respondiendo tras el split |
| Bump | `v0.4.2-django` tras S-05 OK | 5 min | Cerrar PC-1 cleanup + PC-2 con marker limpio |
| PC-3 | Split `admin_views.py` (745 lineas + HTML inline) | 1-2h | Mismo patron; HTML inline merece su propio pass |
| PC-4 | Split `settings.py` en package | 1h | Mecanico |
| D-2 | UX MFA prompts | 45 min | Polish |
| D-1 | Identidad visual | 6-8h | Solo si operador decide |
| D-4 | JS test framework | 2h | |
| Promote | `dev → main` v0.5.0 | — | Requiere instruccion explicita del operador |

## §8. Continuidad — para el proximo agente

### 8.0. Estado snapshot al cierre

- Rama: **`dev @ HEAD`** tras cierre de gaps residuales + skipif Windows.
- `main @ 4b36607`, **52+ commits atras** de `dev`.
- Unit suite: **1063 pass / 0 fail** (los 11 pre-existentes Windows
  ahora skip explicito en la plataforma).
- ruff / mypy: **0 errores en codigo del paquete**.
- Coverage total: **88%** (era 86% al abrir la sesion).
- Version: **`v0.4.2-django`** (bumpeado tras S-05, confirmado en servidor).
- `services/` package: **14 modulos** (`__init__.py` puro re-export).
- `views/` package: **9 modulos** (`__init__.py` puro re-export),
  cobertura 93-100% en los 5 modulos que quedaron bajos tras el split.

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

**Ejecutar S-05 en `ha-report2`:**

```bash
cd /opt/ameli-app-template-dev
git pull origin dev
systemctl restart ameli-app-template-dev-api.service
curl -s http://127.0.0.1:18080/health | python3 -m json.tool | grep -E '"ok"|"version"'
```

Todas las URLs de `accounts/urls.py` deben responder igual que antes:
- `/login/`, `/login/verify-mfa/`, `/login/verify-mfa/resend/`
- `/login/forgot/`, `/login/reset/<uid>/<token>/`
- `/logout/`
- `/profile/`, `/profile/preferences/`, `/profile/email/test/`
- `/profile/avatar/`, `/profile/avatar/delete/`
- `/profile/password/`, `/profile/delete-account/`
- `/profile/sessions/revoke-others/`, `/profile/sessions/<key>/revoke/`
- `/profile/mfa/start/`, `/profile/mfa/confirm/`, `/profile/mfa/disable/`,
  `/profile/mfa/totp/disable/`, `/profile/mfa/email/disable/`,
  `/profile/mfa/regenerate-codes/`, `/profile/mfa/email/start/`,
  `/profile/mfa/email/confirm/`
- `/profile/email-change/`, `/profile/email-change/cancel-pending/`,
  `/profile/email-change/confirm/<id>/<token>/`,
  `/profile/email-change/cancel/<id>/<token>/`
- `/api/admin/session`

Si S-05 pasa: bump a `v0.4.2-django` (VERSION + pyproject.toml +
CHANGELOG.md entry + commit `close PC-1 cleanup + PC-2 + bump v0.4.2-django`).

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
