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
- ~~Instancia de prueba a limpiar: `tmpl-smoke-prod`~~ ✅ **limpiada**
  (units, `/opt`, `/etc`, `/var/lib`, `/var/log`, `/var/backups`, rol y DB
  `tmpl_smoke`, usuario de sistema, y el site block
  `dev05.ameli.cl:18495`). `caddy adapt` OK, los 4 sites originales
  intactos, `dev01` respondiendo.

### 6.0. Estado de red tras la consolidacion (2026-07-22)

**`dev03` y `dev04` migrados a 443 y verificados end to end.**

| Site | URL | Backend | Bind |
|---|---|---|---|
| `dev01` | `https://dev01.ameli.cl:8443` | `18098` | `0.0.0.0` ⚠️ |
| `dev02` | `https://dev02.ameli.cl` | `18050` | `127.0.0.1` ✅ |
| `dev03` | `https://dev03.ameli.cl` | `18080` | `127.0.0.1` ✅ |
| `dev04` | `https://dev04.ameli.cl` | `18090` | `127.0.0.1` ✅ |

**`dev02` — migrado y cerrado.** No es una app del template: es
`ameli-metro-status-dev` (`python -m ameli_metro.api`), prefijo `METRO_*`
y **sin** `CSRF_TRUSTED_ORIGINS` ni `ALLOWED_HOSTS`, asi que el modo de
falla de Starlink no aplicaba. Lo aplicado:

- `METRO_PUBLIC_URL` → `https://dev02.ameli.cl`. Importa mas que en las
  otras: la app manda **web push VAPID y FCM**, y la URL de destino va
  embebida en la notificacion, asi que un valor viejo manda al usuario a
  una URL muerta cuando toca la notificacion.
- **DNS**: la zona publica ya era A → `.36`, pero **faltaba el override
  interno**. `192.168.140.18` no es una zona propia sino un resolutor que
  reenvia a `cpanelhost.cl`; el CNAME ya no existia en el origen y lo que
  devolvia era **cache** (TTL 14400). `dev03`/`dev04` si tenian override
  interno cargado a mano — por eso resolvian a `10.100.100.16` y `dev02`
  no. Se agrego `dev02 A 10.100.100.16`.
- `METRO_API_HOST=0.0.0.0` → `127.0.0.1`, **tras 30 min de muestreo de
  sockets sin un solo peer que no fuera loopback**. El muestreo era
  necesario porque ufw abria `18050` a cuatro subredes LAN y la VPN con
  comentario explicito, o sea que parecia intencional; y los logs de la
  app no servian para decidir porque loguea el `X-Forwarded-For`, asi que
  directo y proxeado se ven identicos.
- Bloque `:18450` y **las 7 reglas ufw** (`18450` + seis de `18050`)
  eliminadas.

Verificado al cierre: `dev02`/`dev03`/`dev04` responden 200 por nombre
desde dentro y desde fuera, `dev01` sigue en 401 con su `basic_auth`
intacto.

> **Hallazgo:** `METRO_EXPOSE_PUBLIC=0` y aun asi el proceso bindea
> `0.0.0.0`. El flag **no controla el bind**. Un operador que lo lea cree
> que el servicio no esta expuesto y no es cierto — misma clase de
> problema que el `validate_installation.sh` que daba OK sobre un
> servicio caido: una señal que miente es peor que no tenerla.

- **IP publica nueva `181.190.21.36`** con VIP Static NAT 443→443 hacia
  `10.100.100.16` en el FortiGate. `dev03`/`dev04`/`dev05` en DNS apuntan
  ahi (TTL 14400). `dev01`/`dev02` siguen en `181.190.21.34`.
- **Split-horizon DNS**: el resolutor interno devuelve `10.100.100.16`,
  el publico `181.190.21.36`. Ambos caminos verificados con `curl 200` y
  certificado valido.
- Caddy bindea `10.100.100.16:443` (directiva `bind` — **debe ser una IP
  local**, no la publica). Regla ufw acotada a esa IP.
- Bloques `:18480`/`:18490` y sus reglas ufw **eliminados**.
- `AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS` y `AMELI_APP_URL_BASE`
  actualizados sin puerto en ambas apps.
- **`dev05.ameli.cl` resuelve a `.36` pero no tiene site block** (se borro
  con la instancia de prueba). Registro DNS colgado.

> **Leccion operativa.** Se saco el puerto viejo del Caddyfile **antes**
> de confirmar que el CSRF apuntara al origen nuevo: el paso quedo
> huerfano entre dos temas y nadie verifico su `grep`. Resultado: la app
> Starlink de produccion quedo unos minutos aceptando `GET` pero
> rechazando todo `POST` con 403 — el login caido sin ningun error
> visible en logs de Caddy. **Ningun paso destructivo va antes de la
> evidencia de que el preparatorio se aplico.**

### 6.1. Pendiente: consolidar `dev01` y `dev02`

El operador abre **una regla de firewall por app**, con un subdominio y un
puerto alto cada una. No hace falta: Caddy multiplexa por SNI/`Host` en un
unico listener, asi que **un subdominio por app sobre el 443 estandar deja
el firewall con una sola regla**. El procedimiento generico quedo escrito
en `TLS_WITH_CADDY.md` → "Varias apps en un host".

**Terreno ya verificado en `ha-report2` (2026-07-22):**

- Caddy **ya es dueño del `:80`**; el **`:443` esta LIBRE**. La
  consolidacion no compite con nada.
- Admin API de Caddy en `127.0.0.1:2019` (loopback, correcto).
- Sites actuales: `dev01:8443`, `dev02:18450`, `dev03:18480`,
  `dev04:18490`. **`dev01` tiene logica propia de iframes**
  (`@iframeMunicipio`, `@iframeSalud`, cookies `Partitioned`) que **no
  entra en el snippet** — hay que escribir ese bloque completo.
- Cert **wildcard ya emitido** en `/etc/ssl/ameli/` — sin ACME por sitio.

> #### 🟡 Bypass del `basic_auth` de `dev01` — exposicion lateral
>
> **Confirmado**: `curl http://127.0.0.1:18098/` → **200**, mientras
> `https://dev01.ameli.cl:8443/` → **401**. El backend
> (`ameli-bandwidth-dashboard-dev`) escucha en `0.0.0.0` y ufw lo permite
> desde `Anywhere`, asi que se saltea el `basic_auth` **y** la CSP,
> `Referrer-Policy`, `X-Content-Type-Options` y `Permissions-Policy` que
> viven en ese `handle` del Caddyfile.
>
> **Alcance real, medido**: NO es internet. Desde una maquina de otro
> segmento, `181.190.21.34:18098` y `10.100.100.16:18098` dan **timeout**
> mientras `10.100.100.16:443` da 200 — el FortiGate no publica ese
> puerto. La exposicion es a **cualquier host que rutee al servidor**
> (LAN y las varias subredes VPN habilitadas). Es defensa en profundidad,
> no incendio. Verificacion definitiva: revisar VIP/policy en el
> FortiGate, no `curl` desde un solo punto.
>
> Mismo caso, menor: `18050` (backend de `dev02`) en `0.0.0.0`, ufw
> restringido a LAN/VPN.
>
> **Dos correcciones de afirmaciones previas de esta sesion**, ambas por
> deducir desde una capa sin comprobar las de arriba:
> 1. Dije que un backend expuesto permitia **falsificar la IP de
>    origen**. **Falso** — `client_ip()`
>    (`accounts/services/session.py`) solo honra `X-Forwarded-For` cuando
>    `REMOTE_ADDR` esta en `TRUSTED_PROXIES`; en acceso directo
>    `REMOTE_ADDR` es la IP real del atacante.
> 2. Dije que `18098` estaba **abierto a internet**, leyendo la regla de
>    ufw sin verificar el perimetro. **Falso** — el FortiGate lo contiene.
>
> **Bindear a loopback es prerequisito de la consolidacion, no un
> follow-up.** Falta mapear que puerto corresponde a que app y cual esta
> realmente expuesta al exterior (el listado salio de un `ss` filtrado,
> no exhaustivo, y no se reviso el ruleset del firewall).

**Orden obligatorio** (cerrar el firewall antes de mover Caddy deja al
operador sin acceso): backends a loopback → subdominios en 443 **con los
puertos viejos vivos** → verificar cada app por el nombre nuevo → recien
ahi cerrar. Y revisar `CSRF_TRUSTED_ORIGINS` / `URL_BASE` en cada app,
porque al irse el puerto **cambia el origen** y los POST empiezan a
fallar por CSRF.

## §7. Continuidad

1. ~~Los tres items de doc~~ ✅ **hecho** (§5.1, `f29a475`).
2. ~~Reinstalar `tmpl-smoke-prod` desde cero sin parches manuales~~ ✅
   **hecho** — criterio de aceptacion cumplido (§3.2).
3. ~~Limpiar la instancia de prueba~~ ✅ **hecho** (§6).
4. ~~Cortar **v0.5.10**~~ ✅ **hecho** — `c7ffbc8`, tag `v0.5.10-django`
   **sobre `dev`**. `main` sigue en `v0.5.9-django` por decision explicita
   del operador: el CI esta apagado hasta el 2026-08-01 y la regla es que
   `main` solo avanza por PR con CI verde, asi que se corta el tag para no
   bloquear la entrega sin romper la regla. **No es un bump de rutina**:
   es la primera version en la que el flujo de instalacion a produccion
   existe de verdad.
5. **Entregar a la hija Starlink** (prompt en el handoff 2026-07-21 §8c).
   Tres cosas que le cambian el deploy: (a) los defaults de puerto en prod
   pasan a 8080/8081 —antes heredaba 18080/18081 del `.env.example`—;
   (b) su instancia **no se re-renderiza sola** por diseno, asi que al
   reinstalar tiene que atender los `WARN:` nuevos: si sale el de
   `SESSION_COOKIE_NAME` su deploy corre **hoy** sin prefijo `__Host-`;
   (c) si su Caddyfile setea HSTS, ver la seccion nueva de
   `TLS_WITH_CADDY.md`.
6. **Consolidacion de Caddy + firewall** — §6.1, con el hallazgo de los
   backends en `0.0.0.0` como prerequisito.
7. Revisar **PR #13**.
8. **Al volver el CI (2026-08-01):** PR `dev`→`main` con verde, promover
   `v0.5.10-django`, y **borrar el bloque marcado** en `CONTRIBUTING.md`
   (lleva un `delete this block once CI is back on` para que no se
   fosilice) mas el aviso en `DECISIONS.md` #11.

> **Nota para el proximo agente.** Con el CI apagado hasta el 2026-08-01,
> antes de tocar `scripts/*.sh`, `deploy/systemd/*` o el camino de
> instalacion: la suite Windows **no cubre nada de eso** (21 tests solo de
> `test_install_env_seeding.py` estan `win32`-skip). Correrlos en el
> servidor es obligatorio, no opcional. El procedimiento esta en §3.2.
