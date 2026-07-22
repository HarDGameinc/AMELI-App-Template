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

#### Bloqueantes destapados al corregir los anteriores

Arreglar B3 hizo que `app.yaml` dijera `environment: "prod"` de verdad.
Hasta ese momento **los guards estaban desactivados y tapaban todo lo que
sigue**. Cada fix destapo el siguiente error real.

| # | Bloqueante | Evidencia |
|---|---|---|
| **B6** | `.env.example` siembra `AMELI_APP_DJANGO_DEBUG=true` en prod | Se copia verbatim a `/etc/<instancia>/app.env`. `settings/base.py:36` se niega a bootear. Ruidoso. |
| **B7** | `.env.example` siembra `AMELI_APP_SESSION_COOKIE_NAME` | `settings/cookies.py:37` lee *cualquier* nombre explicito como override deliberado del operador y **se saltea la politica `__Host-`** (ASVS V3.4.4). **Silencioso.** Nadie eligio ese override: lo sembro el installer. |
| **B8** | `.env.example` siembra `SESSION_COOKIE_SECURE=false` | Cookie de sesion sin flag `Secure` detras de TLS. **Silencioso.** |
| **B9** | `app.yaml.example` trae `email.backend: "console"` | `settings/email.py:36` se niega a bootear fuera de dev: el backend console deja el mail en memoria y password reset / MFA por email fallan en silencio. |
| **B10** | **El puerto explicito del operador se descarta en silencio** | `.env.example` trae `AMELI_APP_API_PORT=18080` (el de dev); `default_env` por diseno solo escribe una clave que FALTA, asi que el valor del ejemplo le gana al default por entorno **y a `AMELI_APP_API_PORT=18190 bash scripts/install.sh`**. Las units systemd se renderizan desde el valor del shell mientras el proceso lee el env file: dos fuentes de verdad divergentes. En `ha-report2` el servicio quedo intentando bindear **18080, puerto de otra app en produccion**. Solo no paso a mayores porque estaba ocupado y el bind fallo. |
| **B11** | `validate_installation.sh` da un veredicto que depende del timing | Reportaba `OK=25 WARN=0 FAIL=0` sobre una API que no respondia nada. Con `Type=simple` systemd marca la unit `active` apenas hace exec, antes del bind, asi que un crash-loop samplea como sano ~la mitad de las veces. La misma instalacion dio `[WARN] ACTIVE` en una corrida y `[OK] ACTIVE` en la siguiente sin cambiar nada. |
| **B12** | `install.sh` ensucia su propio checkout y **rompe el `git pull`** | El Quickstart clona directo en `/opt/<instancia>`, asi que `APP_DIR` *es* el checkout y `repair_permissions` le pasa el chmod encima. El esquema aplicado no coincidia con los modos de git en las dos direcciones (6 scripts 644→755, `deploy/git-hooks/pre-push` 755→644). 7 archivos quedaban permanentemente `modified` y el update documentado abortaba. **Visto en vivo**: un `git pull` fallo, la corrida siguiente uso codigo viejo, y se diagnosticaron sintomas de un fix que nunca habia llegado. |

#### Las dos causas raiz

No es una lista de bugs sueltos:

1. **Los archivos de ejemplo son configuracion de DESARROLLO, y el
   installer los usaba como configuracion de PRODUCCION** — B3, B6, B7,
   B8, B9, B10. Los graves no son los que revientan: son B7/B8
   (degradacion de seguridad sin un solo mensaje) y B10 (la intencion
   explicita del operador descartada en silencio).
2. **El installer asume un arbol de deploy, pero el Quickstart lo hace
   correr sobre un checkout de git** — B12.

#### Confirmado funcionando

- **Auto-generacion de claves cripto** ✅ — 3 × `generated ...`.
- **Idempotencia** ✅ — `Preservado: app.env` / `app.yaml`, sin regenerar.
- **`ameli-app configure`** ✅ — crea el superadmin (`"status": "created"`)
  y en la segunda corrida es idempotente y explicito
  (`"status": "skipped", "reason": "superadmin-already-exists"`).
- **Instalacion completa a produccion con Caddy** ✅ — ver §3.2.

### 3.2. Instalacion completa a produccion con TLS (Caddy)

Ground truth del host, leido antes de tocar nada (`AGENTS.md` → nunca
adivinar): `Caddyfile` **monolitico, sin `import`**, 4 site blocks vivos
(`dev01`–`dev04`), **certificado wildcard ya emitido** en
`/etc/ssl/ameli/wildcard-*` — sin ACME, sin rate limits, sin necesidad de
80/443. Copiar `Caddyfile.example` encima —lo que la guia decia hasta hoy—
**habria tirado las 4 apps**.

Se agrego un site block siguiendo la convencion de `dev04`, validado con
`caddy adapt` **antes** del reload y con backup previo:

```
dev05.ameli.cl:18495 -> reverse_proxy 127.0.0.1:18190
```

`dev05.ameli.cl` no resuelve en DNS; se verifico con `curl --resolve`
para no mutar `/etc/hosts`.

**Resultado end-to-end:**

- `GET /health` sobre TLS → `"ok": true`, `"status": "OPERATIVO"`
- `GET /login/` → `200`, cookie **`__Host-ameli_csrf`** con
  `Secure; HttpOnly; SameSite=Lax` → B7/B8 validados **en comportamiento
  real**, no solo como valor en un archivo
- `validate_installation.sh` → `OK=26 WARN=0 FAIL=0`
- checkout **limpio antes y despues** de instalar → B12 validado
- las 4 apps vivas del host, intactas en todo momento

**Los 21 tests de `test_install_env_seeding.py` corren y pasan en el
servidor.** En Windows estan skipped por diseno (`win32`), y con CI
apagado hasta el 01-08 el servidor es el unico lugar donde se ejecutan.

#### Falso hallazgo, aclarado

`audit_chain: ok:false` / `DEGRADADO` en una corrida **no era un bug del
template**: se borro `/etc/tmpl-smoke-prod` tres veces —regenerando
`AMELI_APP_AUDIT_HMAC_KEY`— conservando la misma base. La fila de
auditoria quedo firmada con una clave que ya no existia. Con base nueva:
`"no signed rows yet"`, `ok: true`, `OPERATIVO`. Deja igual un item de
doc (§5.1).

#### Diagnostico

`3145c65` arreglo **solo las 3 claves cripto**. El resto de la cascada de
crashes seguia intacta, y el flujo prometido de 3 comandos
(`install.sh` → `configure` → Caddy) **era circular**: ambos booteaban
Django antes de que existiera una config valida. El template llevaba desde
el 21/07 con ese flujo documentado como funcional.

## §4. Decisiones tomadas

- **DECISIONS #11** — Windows-native + testing extensivo en servidor
  (supersede #9). WSL2/Docker quedan documentados, no usados.
- Regla `no-sudo` promovida a convencion de primer nivel en `AGENTS.md`.
- **CI apagado hasta el 2026-08-01** por decision del operador. Mientras
  tanto **el servidor es el unico gate** para la superficie shell/systemd:
  los tests marcados `win32`-skip no se ejecutan en ningun otro lado.
- Los archivos `.example` se tratan de ahora en mas como **artefactos de
  desarrollo**: el installer los renderiza, nunca los copia tal cual.

## §5. Fix set entregado

Seis commits, todos con test de regresion. **11 de 12 bloqueantes
corregidos y verificados en servidor real**; B5 es doc-only y ya esta
escrito.

| Commit | Cierra |
|---|---|
| `489c8ab` | B1, B2, B3, B4, B5 — siembra de guards, `render_config_file`, `configure` sin traceback crudo, doc con tag promovido |
| `36f82a0` | Aviso de no sobrescribir un `Caddyfile` compartido |
| `eb92eef` | B6, B7, B8 — `render_env_file` + `warn_insecure_prod_env` |
| `8876480` | B9 — backend de email entregable fuera de dev |
| `818e678` | B10 — `.env.example` deja de pisar host/puertos resueltos |
| `65b81d9` | B12 — `repair_permissions` no ensucia el checkout |
| `8582749` | B11 — `/health` como chequeo autoritativo de liveness |

Superficie tocada: `scripts/_common.sh`, `scripts/install.sh`,
`scripts/validate_installation.sh`, `src/ameli_app/cli.py`,
`deploy/caddy/Caddyfile.example`, `docs/FIRST_INSTALL_DJANGO.md`, y los
modos de git de 6 scripts.

Criterio de diseno aplicado en todos: **renderizar solo al crear el
archivo**, nunca reescribir uno que el operador toco. Para las instancias
ya provisionadas con la degradacion, `warn_insecure_prod_env` y
`warn_port_drift` corren en cada install y la reportan **sin tocar nada**.

### 5.1. Items de documentacion — cerrados (`f29a475`)

1. **Recuperacion de la cadena de auditoria** → `OPERATIONS.md`, seccion
   nueva "Disaster recovery: the key is GONE". La receta de rotacion que
   ya existia **necesita `OLD_KEY`** para re-estampar; si se fue `/etc`,
   esa clave se fue con el y las filas existentes **no vuelven a ser
   verificables por ningun procedimiento**. Se documenta como se llega
   ahi, la prevencion (`backup.sh` dumpea la base pero **no** `app.env`:
   las 3 claves generadas van al secret manager; perder la de MFA vuelve
   indescifrable cada secreto TOTP) y las dos salidas posibles.
2. **HSTS duplicado** → `TLS_WITH_CADDY.md`, seccion nueva. El dueño es
   **Django**. Lo importante no es el header repetido sino que
   `AMELI_APP_HSTS_SECONDS=0` **deja de tener efecto** si Caddy tambien
   lo emite: la perilla que existe para salir de un HSTS mal puesto queda
   inutilizada.
3. **Procedimiento provisorio "servidor como gate"** → `CONTRIBUTING.md`
   + `DECISIONS.md` #11. Mientras el CI este apagado, el **control 1 de
   #11 no existe**: el servidor no es una segunda opinion, es el unico
   gate. El bloque de CONTRIBUTING dice explicitamente que se borra
   cuando el CI vuelva.

**Bonus:** `TLS_WITH_CADDY.md` tambien decia *"reemplaza el contenido de
`/etc/caddy/Caddyfile`"* — el tercer lugar con el mismo consejo que tira
las apps de un host compartido (los otros dos: `Caddyfile.example` en
`36f82a0` y el mensaje post-install en `8582749`). Corregido.

## §6. Notas de operacion

- `ha-report2` hospeda **varias apps AMELI vivas**. Antes de instalar nada:
  `ss -tlnp`, y forzar `APP_SLUG` unico. Los defaults del template
  (`ameli-app`, 8080/8081) **colisionan** con lo que ya corre ahi.
- **`Caddyfile` monolitico sin `import`**, con `dev01`–`dev04` vivos y
  cert wildcard en `/etc/ssl/ameli/`. **Nunca sobrescribirlo**: agregar
  bloque, `caddy adapt` para validar, backup, y recien ahi reload.
- Instancia de prueba a limpiar: `tmpl-smoke-prod`
  (`/opt/tmpl-smoke-prod`, `/etc/tmpl-smoke-prod`, units
  `tmpl-smoke-prod-*`, rol y DB `tmpl_smoke`, y el site block
  `dev05.ameli.cl:18495` del `Caddyfile`).

## §7. Continuidad

1. ~~Los tres items de doc~~ ✅ **hecho** (§5.1, `f29a475`).
2. ~~Reinstalar `tmpl-smoke-prod` desde cero sin parches manuales~~ ✅
   **hecho** — criterio de aceptacion cumplido (§3.2).
3. Limpiar la instancia de prueba (§6), site block de Caddy incluido.
4. Cortar **v0.5.10** y entregar a la hija Starlink (prompt ya redactado en
   el handoff 2026-07-21 §8c). **No es un bump de rutina**: es la primera
   version en la que el flujo de instalacion a produccion existe de verdad.
   `main` sigue en `v0.5.9-django` y nada de esto esta promovido.
5. Revisar **PR #13**.

> **Nota para el proximo agente.** Con el CI apagado hasta el 2026-08-01,
> antes de tocar `scripts/*.sh`, `deploy/systemd/*` o el camino de
> instalacion: la suite Windows **no cubre nada de eso** (21 tests solo de
> `test_install_env_seeding.py` estan `win32`-skip). Correrlos en el
> servidor es obligatorio, no opcional. El procedimiento esta en §3.2.
