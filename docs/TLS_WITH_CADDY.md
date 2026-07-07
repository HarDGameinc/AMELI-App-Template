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

Reemplaza el contenido de `/etc/caddy/Caddyfile` con esto (un sitio por
deploy):

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

Despues de habilitar TLS, marca las cookies como secure via env:

```bash
# /etc/<slug>-<env>/app.env
AMELI_APP_SESSION_COOKIE_SECURE=true
```

Eso fuerza que el browser solo envie la session cookie sobre HTTPS, y
proteccion CSRF tambien valida origen seguro.

Si la app esta detras de Caddy, el `client_ip()` de servicios.py ya
lee `X-Forwarded-For`, asi que el rate limiting y account lockout
cuentan correctamente la IP del cliente real (no la del proxy).

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
