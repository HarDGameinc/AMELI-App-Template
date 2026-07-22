# TLS interno con Caddy

Esta guia describe como poner Caddy delante de un deploy del AMELI App
Template para resolver el warning "Inseguro" que Firefox muestra cuando
el navegador detecta un formulario enviado por HTTP. Es opcional: la app
funciona sin TLS, pero los browsers modernos cada vez son mas estrictos.

Pensado para deploys internos (`/opt/<slug>-<env>/`, puerto `18080` o
similar) donde el dominio es interno (`metro.lan`, `10.100.100.16`, etc.)
y no podemos pedir un cert publico de Let's Encrypt.

## Por que Caddy

- Genera certificados internos automaticamente (CA local)
- Renueva sin intervencion manual
- Una sola linea de config por sitio
- No requiere apertura a internet
- Reverse proxy con WebSocket y SSE soportados (utiles a futuro)

Alternativas validas: nginx con `mkcert`, traefik, hyperscale propio. La
recomendacion para AMELI es Caddy por simplicidad operativa.

## Instalacion

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install caddy
```

## Caddyfile minimo

> ### ⚠️ Si el host ya sirve otras apps, NO reemplaces el archivo
>
> Un `/etc/caddy/Caddyfile` monolitico con varios site blocks es lo
> normal en un host compartido, y sobrescribirlo **tira todas las apps
> que viven ahi**. Agregá tu bloque al final (o un fragment aparte si el
> archivo tiene `import`), y validá **antes** de recargar:
>
> ```bash
> cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d-%H%M%S)
> # ...agregar el bloque...
> caddy adapt --config /etc/caddy/Caddyfile >/dev/null && systemctl reload caddy
> ```
>
> `caddy adapt` parsea sin aplicar: si falla, no recargues.

En un host dedicado, el contenido de `/etc/caddy/Caddyfile` es
directamente esto (un sitio por deploy):

```caddy
# AMELI App Template dev
metro-dev.lan {
    tls internal
    encode gzip

    # Backend gunicorn/uwsgi escuchando en localhost:18080
    reverse_proxy 127.0.0.1:18080

    # Forward del IP real al backend para que client_ip() funcione,
    # rate limiting por IP cuente bien y el audit log lo registre.
    header_up X-Forwarded-For {remote_host}
    header_up X-Forwarded-Proto {scheme}
}

# Si hay mas environments, agregalos como bloques nuevos.
# metro-staging.lan {
#     tls internal
#     reverse_proxy 127.0.0.1:18081
# }
```

## Quien es el dueño del header HSTS: Django

**No pongas `Strict-Transport-Security` en el site block de Caddy.** El
template ya lo emite desde Django (`settings/security_headers.py`), con
un default de **un año fuera de dev** y control fino por env var:

| Variable | Efecto |
|---|---|
| `AMELI_APP_HSTS_SECONDS` | `max-age`. `0` desactiva — util mientras estas cableando TLS |
| `AMELI_APP_HSTS_INCLUDE_SUBDOMAINS` | agrega `includeSubDomains` (opt-in) |

Si ademas lo declaras en Caddy, la respuesta sale con **el header dos
veces**. No es explotable —los navegadores toman el primero— pero:

- las dos fuentes divergen apenas alguien cambia una sola, y la que gana
  no es la que el operador cree;
- `AMELI_APP_HSTS_SECONDS=0` deja de tener efecto, porque el header de
  Caddy sigue ahi. Justo la perilla que existe para poder salir de un
  HSTS mal puesto queda inutilizada.

Verificalo con:

```bash
curl -sSI https://TU_HOSTNAME/ | grep -ci "^strict-transport-security"
```

Tiene que devolver **1**. Si devuelve 2, sacá la linea del `Caddyfile`.

> Django solo emite HSTS cuando ve la request como segura, o sea con
> `AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https` seteado y
> `AMELI_APP_TRUSTED_PROXIES` incluyendo al proxy. Si sacaste el header
> de Caddy y ahora no aparece ninguno, eso es lo que falta — revisá la
> seccion de `SECURE_PROXY_SSL_HEADER` mas abajo antes de volver a
> ponerlo en Caddy.

## Varias apps en un host: un subdominio por app, un solo puerto

El patron que se adopta solo suele ser **un puerto por app** (`app1` en
8443, `app2` en 18450, …), y termina con una regla de firewall por app.
No hace falta: Caddy multiplexa por SNI/`Host` en **un unico listener**.
Un subdominio por app sobre el 443 estandar deja el firewall con **una
sola regla**, y las URLs sin puertos que recordar.

### Por que NO consolidar en un solo subdominio

La tentacion opuesta —un solo nombre para todo, separando por path o por
puerto— rompe el aislamiento entre apps:

- **El puerto no separa cookies.** `apps.example.com:8443` y
  `apps.example.com:18450` comparten el mismo tarro (RFC 6265: el puerto
  no es parte de la identidad de la cookie). Consolidar el nombre y dejar
  los puertos distintos **no aisla nada**.
- **`__Host-` exige `Path=/`.** El template emite
  `__Host-ameli_app_session`, el mismo nombre en cada instancia. Con un
  hostname compartido, la app B pisa la sesion de A **y recibe la cookie
  de sesion de A en cada request**.
- **El template no corre bajo un subpath.** `LOGIN_URL`, `STATIC_URL` y
  `MEDIA_URL` estan fijos en la raiz y no hay `FORCE_SCRIPT_NAME`, asi que
  `handle_path /app1/*` se rompe en el primer redirect.

Se puede forzar dandole a cada app un `AMELI_APP_SESSION_COOKIE_NAME`
distinto, pero eso **desactiva la politica `__Host-`** y deja el
aislamiento apoyado en que los nombres no colisionen, no en el navegador.
Solo para apps que ya confian entre si. **Un subdominio por app es la
respuesta correcta.**

### Requisito previo: los backends van en loopback

Antes de tocar el firewall, verifica que ninguna app servida por Caddy
bindee `0.0.0.0`:

```bash
ss -tlnp | grep -v 127.0.0.1 | grep -vE "caddy|:22\s"
```

Un backend en `0.0.0.0` con su puerto abierto en el firewall es
**alcanzable sin pasar por Caddy**. Lo que eso rompe, en concreto:

- **Todo control que viva en el proxy se saltea**: `basicauth`, matchers
  de IP, rate limiting, headers de seguridad, cualquier restriccion del
  site block. Si tu autenticacion esta en Caddy, el backend queda
  **abierto**.
- **Trafico en claro.** No hay `SECURE_SSL_REDIRECT` en el template, asi
  que la app responde por HTTP sin redirigir. Las cookies marcadas
  `Secure` no viajan (el navegador las retiene), pero **un POST de login
  a `http://` manda las credenciales en texto plano**.
- **HSTS no cubre este camino**: la politica es por hostname, y aca se
  entra por `IP:puerto`.

**Lo que NO pasa**, para no sobreestimar el riesgo: no se puede
falsificar la IP de origen. `client_ip()`
(`accounts/services/session.py`) solo mira `X-Forwarded-For` cuando
`REMOTE_ADDR` esta en `TRUSTED_PROXIES`; en un acceso directo
`REMOTE_ADDR` es la IP real del atacante, que no esta en la lista, asi
que el header se ignora. `ALLOWED_HOSTS` tampoco se saltea — pero se
satisface mandando el `Host` correcto, asi que no es una defensa.

En el template esto ya viene bien (`AMELI_APP_HOST=127.0.0.1` por
defecto); revisa el `--host` de las apps que no lo usen.

### El Caddyfile, con snippet reutilizable

```caddy
(ameli_app) {
    header Strict-Transport-Security "max-age=31536000"
    encode gzip zstd
    tls /etc/ssl/example/wildcard-fullchain.crt /etc/ssl/example/wildcard.key
    reverse_proxy 127.0.0.1:{args[0]} {
        header_up X-Forwarded-Proto https
        header_up X-Real-IP {remote_host}
    }
}

app1.example.com { import ameli_app 18080 }
app2.example.com { import ameli_app 18090 }
app3.example.com { import ameli_app 18105 }
```

Un cert wildcard cubre todos los subdominios sin ACME por sitio. Los
bloques con logica propia (matchers de iframe, rutas especiales) no
entran en el snippet: se escriben completos.

### Migracion en dos etapas, sin ventana de caida

**El orden importa**: cerrar el firewall antes de mover Caddy te deja sin
acceso. Hacelo con la sesion SSH abierta y backup del `Caddyfile`.

1. **Levantar los subdominios en 443 dejando los puertos viejos vivos.**
   Ambos caminos responden. Verificar cada app por el nombre nuevo:
   ```bash
   caddy adapt --config /etc/caddy/Caddyfile >/dev/null && systemctl reload caddy
   for h in app1 app2 app3; do
     curl -sSI "https://${h}.example.com/" -o /dev/null -w "${h}: %{http_code}\n"
   done
   ```
2. **Actualizar `CSRF_TRUSTED_ORIGINS` con AMBOS origenes** (viejo y
   nuevo) y reiniciar. Ver el aviso de abajo: este paso va **antes** de
   tocar nada destructivo.
3. **Recien entonces** eliminar los bloques de puerto alto y cerrar las
   reglas de firewall, dejando 443 (+80 si queres redirect HTTP→HTTPS).

> ### ⚠️ El `GET` te miente
>
> Si sacas el puerto viejo sin haber actualizado `CSRF_TRUSTED_ORIGINS`,
> la app sigue respondiendo **200 a todo `GET`** — las paginas cargan, el
> health check pasa, Caddy no loguea nada raro. Lo unico que se rompe es
> el `POST`: **403 CSRF, o sea nadie puede loguearse**. Es un modo de
> falla silencioso para toda la verificacion habitual.
>
> Regla: **ningun paso destructivo va antes de la evidencia de que el
> preparatorio se aplico.** Verificalo explicitamente:
>
> ```bash
> grep -H "^AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS" /etc/<instancia>/app.env
> ```

### Probar el camino publico SIN tocar el DNS

Antes de mover ningun registro, forza la resolucion solo para el test:

```bash
curl -sS --resolve app1.example.com:443:<IP_PUBLICA> \
     https://app1.example.com/ -o /dev/null -w "%{http_code}\n"
```

Si da 200, el NAT y la policy del perimetro estan bien y lo unico que
falta es DNS. Si da timeout, el problema esta aguas arriba y no moviste
nada. **Un VIP sin su policy asociada es el olvido mas comun** — el
mapeo queda perfecto y no pasa trafico.

### Bajar el TTL antes de mover el DNS

Mientras convivan los dos caminos, el rollback es "usar el puerto viejo".
**Eso deja de valer en cuanto el DNS apunta a la IP nueva**: si la IP
vieja no publica el puerto alto, la URL vieja queda inalcanzable por
nombre. El rollback pasa a ser revertir el registro, y tarda lo que diga
el TTL.

```bash
dig +noall +answer app1.example.com
```

Con TTL de 4 horas, un rollback tarda 4 horas. Bajalo a **300** y espera
a que expire el viejo **antes** de cambiar la IP.

### El detalle que muerde: cambia el origen

Al desaparecer el `:8443` de la URL publica **cambia el origen**. En cada
app hay que revisar:

- `AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS` — si tiene el puerto viejo
  hardcodeado, **todos los POST empiezan a fallar por CSRF**.
- `AMELI_APP_URL_BASE` — los links de reset de password y de
  verificacion por email seguirian apuntando al puerto viejo.

`AMELI_APP_DJANGO_ALLOWED_HOSTS` no cambia: se compara contra el
hostname, sin puerto.

## Compresion + cache de estaticos y media (optimizacion)

Por defecto la app sirve `/static/` y `/media/` ella misma (via
`django.views.static.serve` en `urls.py`). Funciona, pero cada avatar,
CSS y JS pega en el proceso Python — desperdicia un worker en algo que
un file server hace mucho mas rapido, sin cache headers ni compresion
mas alla del `encode gzip` global.

Cuando el deploy empieza a tener trafico real, conviene que **Caddy
sirva estos assets directamente desde disco**, con brotli + gzip y
`Cache-Control` de larga vida. Django deja de verlos.

```caddy
# AMELI App Template dev — variante optimizada
metro-dev.lan {
    tls internal

    # brotli para navegadores modernos, gzip de fallback. Caddy elige
    # el mejor que el cliente acepte via Accept-Encoding.
    encode zstd br gzip

    # --- /static/ : assets versionados de la app (CSS/JS/imgs) ---
    # Servidos directo desde el dir de STATICFILES. Ajusta la ruta a
    # donde corre `collectstatic` en tu deploy (o al checkout en dev).
    handle_path /static/* {
        root * /opt/ameli-app-template-dev/src/ameli_app/static
        file_server
        # Los estaticos propios no cambian entre deploys sin cambiar de
        # nombre — cache agresiva es segura. Si versionas por hash en el
        # nombre podes subir a `immutable`.
        header Cache-Control "public, max-age=86400"
    }

    # --- /media/ : avatares subidos por usuarios ---
    # Servidos directo desde MEDIA_ROOT (profile_uploads_dir del app.yaml,
    # p.ej. /var/lib/ameli-app-template-dev/uploads).
    handle_path /media/* {
        root * /var/lib/ameli-app-template-dev/uploads
        file_server
        # Cache mas corta: un avatar se reemplaza sin cambiar de URL, asi
        # que 1h evita que un cambio tarde un dia en propagarse. Si el
        # pipeline de imagenes (roadmap D-5) renombra por hash al
        # transformar, esto tambien puede subir a `immutable`.
        header Cache-Control "public, max-age=3600"
    }

    # --- todo lo demas va a Django ---
    reverse_proxy 127.0.0.1:18080
    header_up X-Forwarded-For {remote_host}
    header_up X-Forwarded-Proto {scheme}
}
```

Notas:

- **Permisos**: el usuario de Caddy tiene que poder leer `MEDIA_ROOT`.
  En install.sh el dir de uploads es del app user (modo 0750); agrega
  al usuario `caddy` al grupo del app user o afloja a 0755 el dir de
  uploads (no los archivos con PII de otros lados).
- **`collectstatic`**: si servis `/static/` desde Caddy fuera de dev,
  corre `manage.py collectstatic` en cada deploy para juntar los assets
  de Django admin + los propios en un solo dir, y apunta el `root` ahi.
  En dev el finder de Django (que camina cada app) es mas comodo.
- **`immutable`**: solo es seguro si el nombre del archivo cambia cuando
  el contenido cambia (versionado por hash). Hoy los avatares mantienen
  la URL al reemplazarse, por eso `max-age=3600` en lugar de `immutable`.
- Esto NO reemplaza el transform server-side de imagenes (roadmap D-5):
  cache/compresion reduce el costo de *servir* la imagen, pero un avatar
  de 3 MB sigue siendo 3 MB en disco y en la primera descarga. Las dos
  optimizaciones son complementarias.

## DNS interno

Caddy resuelve el cert al startup. El nombre del sitio
(`metro-dev.lan`) tiene que resolver a la IP del servidor desde las
maquinas cliente. Opciones:

- **/etc/hosts** en cada cliente (mas simple para pocos clientes)
- **DNS interno** (Pi-hole, dnsmasq, AD DNS) — recomendado
- **Tu router** si soporta entradas locales

## Confiar en la CA interna

Caddy genera una CA local autofirmada. Cada cliente que vaya a usar la
app necesita importarla para que el browser no muestre warnings.

```bash
# En el servidor con Caddy:
caddy trust  # importa la CA del propio Caddy en el trust store local
# Para distribuir a otros clientes:
cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
# Copia ese archivo a cada cliente e instalalo en:
#   - Linux: /usr/local/share/ca-certificates/, luego ``update-ca-certificates``
#   - Windows: Certificados confiables -> Entidades de certificacion raiz
#   - macOS: Keychain Access -> System -> Always Trust
#   - Firefox: tiene su propio store, importar manualmente en about:preferences#privacy
```

## Cambios en el AMELI App Template

Detras de un proxy TLS hay que ajustar **cuatro** cosas en
`/etc/<slug>-<env>/app.env`. Cambialas **juntas** y reinicia: arreglar el
header sin agregar el trusted-origin rompe el login (ver mas abajo).

```bash
# /etc/<slug>-<env>/app.env

# 1. Que request.is_secure() sea honesto detras del proxy. Caddy manda
#    "X-Forwarded-Proto: https"; Django lo lee como META HTTP_X_FORWARDED_PROTO.
#    Aceptamos ambas formas (la app normaliza), pero es el header CLAVE:
#    si queda mal, is_secure() es False y secure-cookies/HSTS/CSRF-seguro
#    no se activan aunque el sitio sea HTTPS (falla en silencio).
AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https

# 2. Origenes confiables para CSRF (scheme://host[:puerto]). REQUERIDO en
#    cuanto is_secure() es True: sin esto, todo POST (login) falla el
#    chequeo estricto de origen. Lista separada por comas.
AMELI_APP_DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com:8443

# 3. Cookies solo por HTTPS (+ prefijo __Host- en la de CSRF).
AMELI_APP_SESSION_COOKIE_SECURE=true

# 4. Hosts que responde la app. En dev el default es "*"; fuera de dev
#    (o si lo restringis) tiene que incluir el hostname del sitio Caddy.
# AMELI_APP_DJANGO_ALLOWED_HOSTS=app.example.com,127.0.0.1
```

> **Footgun del #1**: Django compara contra `request.META[name]`, cuyas
> claves de header estan WSGI-mangled (`HTTP_` + mayusculas +
> guiones->underscores). Poner `X-Forwarded-Proto=https` "a secas" no
> matcheaba y dejaba `is_secure()` en False **sin ningun error**. Desde
> 2026-07-10 la app **normaliza** el nombre, asi que tanto
> `X-Forwarded-Proto=https` como `HTTP_X_FORWARDED_PROTO=https` funcionan.

> **Seguridad del header**: confiar en `X-Forwarded-Proto` solo es seguro
> si la app **no** es alcanzable salvo por el proxy. Con
> `AMELI_APP_HOST=127.0.0.1` (bind a loopback) se cumple; si la app
> escuchara en `0.0.0.0`, un cliente podria mandar el header y falsear
> "secure". Verifica el bind con `ss -tlnp | grep <puerto>`.

Si la app esta detras de Caddy, el `client_ip()` de `services/` ya lee
`X-Forwarded-For`, asi que el rate limiting y account lockout cuentan
correctamente la IP del cliente real (no la del proxy).

Verifica el login **por HTTPS** despues del cambio (un POST real, no solo
un GET) — es lo que ejercita el CSRF trusted-origin.

## Verificacion

```bash
# Sin TLS (esperar warning):
curl http://metro-dev.lan/health

# Con TLS (cert interno):
curl --cacert /etc/caddy/.local/share/caddy/pki/authorities/local/root.crt \
     https://metro-dev.lan/health
```

Browser: navegar a `https://metro-dev.lan/`. Con la CA importada el
candado aparece verde. Firefox deja de quejarse por formularios en HTTP.

## Backout

```bash
systemctl stop caddy
systemctl disable caddy
# Apuntar /etc/hosts (o DNS) directo al puerto del backend
```

La app sigue funcionando como antes en `http://10.100.100.16:18080/`.
