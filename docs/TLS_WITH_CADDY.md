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
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
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
sudo caddy trust  # importa la CA del propio Caddy en el trust store local
# Para distribuir a otros clientes:
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
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
sudo systemctl stop caddy
sudo systemctl disable caddy
# Apuntar /etc/hosts (o DNS) directo al puerto del backend
```

La app sigue funcionando como antes en `http://10.100.100.16:18080/`.
