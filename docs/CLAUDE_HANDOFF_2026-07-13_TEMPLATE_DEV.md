## AMELI App Template handoff (sesion Claude, 2026-07-13)

Fecha: `2026-07-13`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.4-django`)
Rama estable: `main` (promoviendo `v0.5.4` en esta sesion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-11_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-11_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Local `dev` estaba **33 commits detras** de `origin/dev` (ahead=0, arbol
  limpio) → **fast-forward** seguro. origin/dev traia el trabajo de las
  sesiones 10-jul y 11-jul (v0.5.2 Django 5.2.16 CVEs, v0.5.3 M3 throttle
  atomico + template-check, TLS/SSH cerrados en el host, SBOM, rotacion de
  secretos, CSP style-src).
- `dev` y `main` en `v0.5.3`, con **7 commits en `dev` sin promover** — el
  relevante: `96f6bec feat(security): drop 'unsafe-inline' from CSP
  style-src`. CI verde en el HEAD de dev; sin PRs abiertos.

## §2. Objetivo de la sesion

**Promover `dev → main` como `v0.5.4-django`** para cerrar el loop del feat
de CSP `style-src` (mejora de seguridad sin versionar ni promover) + los
docs SBOM/ops "ground-truth".

## §3. Trabajo realizado

### 3.1. Fix de test flaky (`test(sri)`, commit `4977edc`)

`test_sri_for_caches_until_mtime_changes` fallaba **solo en Windows** (pasaba
aislado y en CI Linux). Causa: `os.utime()` seguido de `write_bytes()`
reseteaba el mtime a "ahora", que en un filesystem de resolucion gruesa podia
igualar el `cached_mtime` y no invalidar la cache. Fix determinista: escribir
primero, forzar mtime distinto despues. 5/5 ×3 estable. Verificado como flake
ambiental, no regresion (solo hice fast-forward).

### 3.2. Bump `v0.5.4` + validacion en server

Contenido del release (los 7 commits sin promover + el fix del test):
- **CSP `style-src` sin `'unsafe-inline'`** (`96f6bec`): 46 `style=""` de 11
  templates → clases utilitarias en `app.css` (cero cambio visual), ultimo
  token inseguro fuera del CSP principal.
- Docs: OPERATIONS "Deployed instance — ground truth", SBOM CycloneDX,
  prompts S-09/S-10.

**Validado en `ha-report2`** (deploy a `4977edc`): `/health` →
`v0.5.3-django` OPERATIVO; `check` 0 issues; **CSP header responde
`style-src 'self' https://fonts.googleapis.com`** (sin `'unsafe-inline'`);
render 2FA/login intacto. El unico error en consola era de una **extension
del navegador** (autofill overlay) — el CSP bloqueando inyeccion de estilos
de terceros, comportamiento correcto, no de la app.

### 3.3. Promocion `dev → main`

(A completar tras el merge: PR, CI verde, merge commit, tag/release
`v0.5.4-django`, sync del server.)

## §4. Continuidad / backlog (opcional)

- Host: limpiar reglas ufw vestigiales del 18080 (loopback-only, inofensivas).
- Repo: **Model C** del update-channel (`ameli-core` + Dependabot, grande;
  `DECISIONS.md` #7). Nada obligatorio pendiente.

## §5. Restricciones criticas (vigentes)

- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde +
  merge commit + tag (flujo en `RELEASE.md`).
- Deploy/ground-truth del server en `OPERATIONS.md` → "Deployed instance —
  ground truth" (servicio `ameli-app-template-dev-api.service`, loopback
  `127.0.0.1:18080` detras de Caddy TLS en `dev03.ameli.cl:18480`). No hay
  `sudo` (root).
- Tests requieren `APP_ENV=dev`. Suite completa + ruff antes de push. Bump
  solo tras validar en server.
