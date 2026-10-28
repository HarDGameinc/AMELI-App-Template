## AMELI App Template — retiro y archivo (2026-10-27)

Fecha: `2026-10-27`
Agente: `claude-opus-5-5`
Rama de trabajo: `dev` (HEAD `ede2402` al abrir)
Rama estable: `main` en **`v0.5.12-django`** (`1ab4305`) — release final
Sesion previa: [`CLAUDE_HANDOFF_2026-08-04_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-08-04_TEMPLATE_DEV.md)

## §1. Decision

El operador decidio **retirar y archivar** el proyecto. No hay mas
desarrollo, releases ni fixes de seguridad. El repositorio queda en solo
lectura en GitHub como referencia.

## §2. Estado al cierre

- **Release final: `v0.5.12-django`** (`main`, PR #15, 2026-08-05).
- `dev` = `main` + commits de docs (handoff 08-04 y este retiro). Sin
  codigo pendiente de promover.
- Local vs remoto verificado: clones Windows y WSL sincronizados con
  `origin/dev`, arbol limpio, sin stashes ni ramas locales extra. No se
  perdio trabajo.
- **PR #13** (Dependabot, `actions/setup-python` 6→7) cerrado sin
  mergear; su rama remota borrada.
- Repositorio GitHub **archivado** (`gh repo archive`). Reversible desde
  Settings → "Unarchive" si alguna vez hiciera falta.

## §3. Impacto en apps hijas

Las apps hijas (p. ej. **AMELI Report Starlink**) que usan este repo como
remote `template` (DECISIONS #7) siguen pudiendo clonarlo y cherry-pickear
desde los tags, pero **no recibiran mas fixes**. Cada hija asume desde ahora
su propio mantenimiento, incluidos parches de seguridad de Django (5.2 LTS
tiene soporte hasta ~2028) y del lockfile (`pip-audit`).

## §4. Limpieza del servidor `ha-report2`

La instancia `ameli-app-template-dev` se desinstala con
`scripts/uninstall.sh --purge --yes`, que primero saca un backup final a
`/var/backups/ameli-app-template-dev-*.tar.gz` y luego elimina units,
directorios y el usuario del sistema. La base de datos y el bloque de
Caddy no los toca el script; se eliminan a mano (comandos en el chat de
la sesion).

La limpieza se ejecuta **despues** de archivar el repo (un repo archivado
no acepta pushes), asi que su resultado no queda registrado aqui: este
documento es el ultimo commit del proyecto. El backup final de la
instancia queda en `/var/backups/` del servidor por si hubiera que
recuperar datos.
