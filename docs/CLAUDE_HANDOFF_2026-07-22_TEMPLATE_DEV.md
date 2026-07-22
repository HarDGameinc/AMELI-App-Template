## AMELI App Template handoff (sesion Claude, 2026-07-22)

Fecha: `2026-07-22`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.9-django`, HEAD `562d4f4` al abrir)
Rama estable: `main` (en `v0.5.9-django`, `98f32a5`)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-21_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-21_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante el dia.

## §1. Snapshot al inicio

- `dev` == `origin/dev`, arbol limpio. `main` en `v0.5.9-django` (`98f32a5`),
  `dev` **9 commits adelante** — incluyendo `3145c65` (installer DX overhaul),
  que **no esta promovido**. Ver §3.1 B5.
- **PR #13** (Dependabot `setup-python` 6→7) sigue abierto, sin review.
- Server `ha-report2`: apps de produccion en marcha; el template en
  `v0.5.6-django`.

## §2. Objetivo de la sesion

1. Cerrar la estrategia de entorno de desarrollo (WSL2 quedaba fuera).
2. Ejecutar el **plan de prueba en servidor §8b** del handoff anterior:
   validar `install.sh` + `ameli-app configure` de `3145c65` en un
   servidor real, desde cero.
3. Consolidar hallazgos y decidir el fix set antes de cortar **v0.5.10**.

## §3. Trabajo realizado

### 3.0. DECISIONS #11 — entorno de desarrollo (commits `891f7b5`, `8d85525`)

Por instruccion del operador, **WSL2 y Docker salen del loop de trabajo**:
el coste de mantenimiento del puente WSL2 (sync editor↔fs Linux, quoting
de `wsl.exe`, CRLF y expansion de `$` en env files, Postgres sin systemd)
supero el beneficio. Estrategia nueva:

- **Windows-native** para el loop diario (venv desde los *rangos*, no desde
  `requirements.lock`: el lock pinea `uvloop`, POSIX-only).
- **Servidor Linux real** para pruebas extensas.

Documentado como **DECISIONS #11** (supersede #9, que quedo con banner) y
reflejado en `CONTRIBUTING.md`.

**Trade-off asumido y escrito explicitamente:** ~30 tests (shell / systemd /
backup) **no corren en Windows**. La suite Windows da **1135 passed / 58
skipped**; el delta **58 vs 28 skips** es la señal estable. Regla dura: un
cambio en `scripts/*.sh` o `deploy/systemd/*` **nunca queda validado por un
run verde local** — necesita CI verde o prueba en servidor.

También se promovió a convencion de primer nivel en `AGENTS.md` una regla
que estaba enterrada al final de `CONTRIBUTING.md`:

> **El shell del servidor es `root` y NO tiene binario `sudo`.** Un comando
> con `sudo` falla con `sudo: orden no encontrada`. No es estilo: es
> correccion.

### 3.1. Prueba en servidor — instalacion prod desde cero

**Setup aislado** (el box hospeda ~8 apps AMELI vivas; ver §6):

```bash
git clone -b dev https://github.com/HarDGameinc/AMELI-App-Template.git /opt/tmpl-smoke-prod
APP_SLUG=tmpl-smoke APP_ENV=prod \
AMELI_APP_API_PORT=18190 AMELI_APP_WEB_PORT=18191 \
bash scripts/install.sh
```

`APP_SLUG` forzado y puertos 18190/18191 elegidos tras leer `ss -tlnp`
(los defaults prod 8080/8081 colisionaban con la hija Starlink, y el slug
por defecto `ameli-app` habria pisado `/opt/ameli-app-prod`).

**Resultado final: la instalacion completa y valida** —
`RESUMEN: OK=25 WARN=0 FAIL=0`, `/health -> 200 (attempt 1)`, 34 migraciones
aplicadas, 6 units enabled+active.

**Pero solo despues de parchear a mano lo que el installer deberia sembrar.**
El camino a ese verde requirio 5 iteraciones, cada una destapando un
bloqueante real. Ninguno lo detecta CI ni la suite local porque ese camino
**nunca se habia ejecutado end-to-end**.

#### Bloqueantes confirmados

| # | Bloqueante | Evidencia |
|---|---|---|
| **B1** | `install.sh` **no siembra** `AMELI_APP_DJANGO_ALLOWED_HOSTS` | `initialize_runtime_env` (`scripts/_common.sh:276-304`) siembra 12 claves + 3 cripto, ninguna es ALLOWED_HOSTS. El guard de `settings/base.py:48` aborta. |
| **B2** | `install.sh` **no siembra** `AMELI_APP_TRUSTED_PROXIES` | Idem; guard en `settings/base.py:78`. |
| **B3** | `app.yaml` se copia **verbatim**, sin sustitucion | `copy_if_missing` (`_common.sh:189-199`) es un `cp` pelado. `app.yaml.example:30` trae `profile_uploads_dir: "data/uploads/dev"` — relativo y con `dev` hardcodeado. MEDIA_ROOT deriva de esa clave (**no** de `data_dir`, ver `src/ameli_app/config.py:253`), asi que cae dentro del checkout y `_refuse_path_inside_checkout` (`settings/i18n_static.py:64`) lo rechaza. `environment: "dev"` tambien queda mal en una instalacion prod. |
| **B4** | `ameli-app configure` **bootea Django** para crear el superadmin | `cli.py:813` llama `_bootstrap_django(args)`. Circular: el wizard que debe *escribir* la config necesita que la config ya sea valida. Con B1–B3 sin resolver, el wizard recoge todo el input y **crashea con traceback crudo**. Mitigante: `_write_env_updates` corre **antes** (`cli.py:810`), asi que el input no se pierde. |
| **B5** | La doc / Quickstart clonan `main`, donde la feature no existe | `gen_env_if_missing`: **0 ocurrencias en `origin/main`, 4 en `origin/dev`**. `3145c65` esta sin promover. Mi primer intento de prueba fallo justamente por esto. |

#### Confirmado funcionando

- **Auto-generacion de claves cripto** ✅ — 3 × `generated ...` en el primer
  run. Esta era la feature central de `3145c65`.
- **Idempotencia** ✅ — segundo run: `Preservado: app.env` / `Preservado:
  app.yaml`, sin regenerar claves, deps ya satisfechas.
- **`validate_installation.sh`** ✅ — 25 checks, 0 fail, en una instancia
  recien creada con slug y puertos no-default.

#### Diagnostico

`3145c65` arreglo **solo las 3 claves cripto**. El resto de la cascada de
crashes sigue intacta, y el flujo prometido de 3 comandos
(`install.sh` → `configure` → Caddy) **es circular**: ambos bootean Django
antes de que exista una config valida.

## §4. Decisiones tomadas

- **DECISIONS #11** — Windows-native + testing extensivo en servidor
  (supersede #9). WSL2/Docker quedan documentados, no usados.
- Regla `no-sudo` promovida a convencion de primer nivel en `AGENTS.md`.
- **Parar el testing manual** tras el verde y consolidar: seguir tirando del
  hilo a mano ya no aportaba hallazgos nuevos.

## §5. Fix set propuesto (pendiente de aprobacion)

1. **`_common.sh` / `initialize_runtime_env`** — sembrar
   `AMELI_APP_DJANGO_ALLOWED_HOSTS` (hostname autodetectado) y
   `AMELI_APP_TRUSTED_PROXIES=127.0.0.1`. Cierra B1+B2.
2. **`install.sh`** — **templatizar `app.yaml`** en vez del `cp` verbatim:
   `environment` → `$APP_ENV`, `data_dir` y `profile_uploads_dir` →
   `/var/lib/<instance>`. Reutilizar el patron `sed` que ya existe en
   `render_systemd_units`. Cierra B3.
3. **`cli.py` / `configure`** — no emitir traceback crudo cuando Django aun
   no puede bootear; reportar "env escrito, superadmin pendiente" y salir
   con codigo distinto de 0 pero legible. Mitiga B4.
4. **Docs** (`FIRST_INSTALL_DJANGO.md`, Quickstart) — clonar un **tag
   promovido**, no `main` pelado. Cierra B5.

Toca: `scripts/_common.sh`, `scripts/install.sh`, `config/app.yaml.example`,
`src/ameli_app/cli.py`, `docs/FIRST_INSTALL_DJANGO.md`.

Estos cambios son **exactamente** la superficie que Windows no puede
validar (§3.0), asi que van con prueba en servidor + CI verde antes de
cortar **v0.5.10**.

## §6. Notas de operacion

- `ha-report2` hospeda **varias apps AMELI vivas**. Antes de instalar nada:
  `ss -tlnp`, y forzar `APP_SLUG` unico. Los defaults del template
  (`ameli-app`, 8080/8081) **colisionan** con lo que ya corre ahi.
- Instancia de prueba a limpiar: `tmpl-smoke-prod`
  (`/opt/tmpl-smoke-prod`, `/etc/tmpl-smoke-prod`, units
  `tmpl-smoke-prod-*`, rol y DB `tmpl_smoke`).

## §7. Continuidad

1. Implementar el fix set §5 (pendiente de OK del operador).
2. Reinstalar `tmpl-smoke-prod` desde cero **sin parches manuales** — ese
   es el criterio de aceptacion.
3. Limpiar la instancia de prueba (§6).
4. Cortar **v0.5.10** y entregar a la hija Starlink (prompt ya redactado en
   el handoff 2026-07-21 §8c).
5. Revisar **PR #13**.
