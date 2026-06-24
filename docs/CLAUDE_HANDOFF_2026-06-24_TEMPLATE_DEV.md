## AMELI App Template handoff (sesion Claude, 2026-06-24)

Fecha: `2026-06-24`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `502f123` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 7 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-23_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-23_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ 502f123` (sync local == origin).
  - `main @ 4b36607` (sync local == origin), 7 commits atras de
    `dev` post-milestone del 23-jun.
  - Convencion ratificada el 21-jun: server pullea SIEMPRE `dev`;
    `main` solo avanza por instruccion explicita "milestone".
- Tests: **1004 unit pass** + 4 e2e collected (skip por default).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src.
- ruff: clean local.
- bandit: clean local (Medium: 0 con el `# nosec` shipped ayer).
- Version: `v0.4.0-django`.
- Server `ha-report2`: corriendo `36c4329` (codigo del 22-jun),
  MFA email funcional, IPv6 disabled, dev deps NO instaladas.
- ASVS L2: 151 PASS + V12.4.1 strict + V10.3.x SRI + V14 TT.
- Mini-roadmap: **12/12 closed** (Fase 6 #12 Playwright cerrado
  el 23-jun shippeando suite + CI job).
- CI status: Lint+Test ✓, supply-chain ✓, **e2e job rojo** con
  2 bugs identificados de test-code (no de workflow), documentados
  en §8 del 23-jun.

### Commits pendientes en `dev` desde el ultimo match con `main`

| Bloque | Commits | Tema |
|---|---|---|
| Cierre 23-jun | `502f123`, `e08ec7c`, `bf711a2`, `fbfe3af`, `e235ebc` | docs y handoffs |
| Fase 6 #12 + CI fixes | `8cbebbe`, `5695c64`, `568ced1`, `3ae3d50` | e2e suite + 3 layers de CI |

Total: 7 commits ahead, sin code change runtime (e2e + workflow +
docs).

## §2. Objetivo de la sesion

Continuar pendientes del cierre del 23-jun:

1. **Bug A — Cross-thread DB invisibility en e2e_admin fixture**
   (afecta 3 tests con `TimeoutError`):
   - Fixture usa `db` (savepoint mode, no committed). `live_server`
     corre en otro thread y NO ve el user creado.
   - Fix: `tests/e2e/conftest.py:e2e_admin(db, ...)` →
     `e2e_admin(transactional_db, ...)`.
2. **Bug B — Assert message mismatch en
   `test_login_with_wrong_password_*`**:
   - Django renderiza "por favor, introduzca un nombre de usuario
     y clave correctos." — mis asserts buscan "credenciales/
     incorrect/invalid/no pudimos".
   - Fix: cambiar assert a `"introduzca un nombre" in body`.
3. **Verificar CI verde post-fix** — el job e2e debe pasar los
   4 tests. Si pasa, mini-roadmap wire-validated end-to-end.

Cosmetico opcional al cierre:
- Log line format del breaker (`%.0f` → `%.1f`).

## §3. Trabajo realizado

| # | Commit | Descripcion |
|---|---|---|
| 1 | `413fd81` | docs: abrir handoff 2026-06-24 con §1 snapshot + §2 pendings |
| 2 | `5930ee8` | fix e2e CI (4/N): cross-thread DB (`transactional_db`) + assert "introduzca un nombre" |
| 3 | `f4bb119` | fix e2e CI (5/N): post-login waits for `/profile/` (LOGIN_REDIRECT_URL), not `/` |
| 4 | (este) | cosmetico breaker `%.0f` → `%.1f` + cierre handoff §3-§8 |

### 3.1. Bug A — `transactional_db` switch (`5930ee8`)

`tests/e2e/conftest.py:e2e_admin` paso de `db` → `transactional_db`.
La fixture `db` envuelve cada test en una transaccion con savepoint
que jamas commitea — el thread del `live_server` (que es OTRO
thread, otra conexion) por lo tanto no ve la fila creada. La
`transactional_db` trunca al final en lugar de hacer rollback, asi
los commits si son visibles cross-thread.

El cambio es correcto y se queda — pero como se demostro en §3.3,
NO era la causa del symptom timeout de 3/4 tests. La fixture seguia
fallando por un motivo distinto (Bug C). El cambio es defensivo:
sin el, cualquier test e2e nuevo que use `e2e_admin` heredaria la
trampa cross-thread.

### 3.2. Bug B — assert "introduzca un nombre" (`5930ee8`)

`tests/e2e/test_login_flow.py:test_login_with_wrong_password_*`:
los asserts originales buscaban copy especulativa ("credenciales/
incorrect/invalid/no pudimos"). Django renderiza el string stock
en espanol: "Por favor, introduzca un nombre de usuario y clave
correctos. Observe que ambos campos pueden ser sensibles a
mayusculas." Cambio el assert a `"introduzca un nombre" in body`
con fallback `"introduzca un usuario"` por si el snapshot de
traduccion cambia.

Resultado en CI run `28099349394`: el test PASO. Bug B resuelto.

### 3.3. Bug C — wrong post-login URL (`f4bb119`)

Diagnostico real del symptom timeout. Los 3 tests que fallaban
con `wait_for_url(f"{live_url}/")` no era cross-thread — era que
Django redirige todo login exitoso a `/profile/`, no a `/`:

- `src/ameli_web/settings.py:534`: `LOGIN_REDIRECT_URL = "/profile/"`
- `src/ameli_web/accounts/views.py:103-112`:
  `LoginView.get_success_url()` regresa `/profile/` por default.

El test esperaba `/` (dashboard-home), pero login nunca aterriza
ahi salvo que se pase explicitamente `?next=/`. Fix: cambiar los
3 `wait_for_url(f"{live_url}/")` a `wait_for_url(re.compile(rf"{re.escape(live_url)}/profile/.*"))`
en los helpers `_login_no_mfa` de `test_avatar_upload.py` y
`test_password_change.py`, y en el step 6 de
`test_login_with_email_mfa_reaches_dashboard`.

**Por que el diagnostico anterior fue erroneo**: la senal en la
que se baso §2 punto 1 fue "3 tests fallan al esperar `/` y el
test de wrong-password pasa". La heuristica fue: "si el user no
existiera tampoco fallaria el wrong-password" — pero esa heuristica
es FALSA. El wrong-password test pasa igual exista o no el user
porque Django regresa el mismo mensaje "introduzca un nombre"
en ambos casos (auth fail = user-not-found O wrong-pass, indistinto
por diseno anti-enumeration). Asi que la prueba que se uso para
inferir "user existe → cross-thread no es la causa" no probaba
nada. La causa real solo se vio leyendo `views.py:103-112` +
`settings.py:534`.

Resultado en CI run `28099841141` post-`f4bb119`: **2/4 tests
pasan** (avatar + wrong-password), 2/4 siguen rojos por
**Bug D + Bug E**, detallados en §6.

### 3.4. Cosmetico — breaker `%.0f` → `%.1f`

`src/ameli_web/accounts/circuit_breaker.py:102`. Sin tests que
dependan del formato literal del log (`grep` confirmado).

## §4. Decisiones tomadas

1. **Parar de iterar en el job e2e despues de 5/N**. Per
   instruccion explicita del operador ("el error no se soluciona,
   dejalo documentado y continuemos con otros pendientes"). Los
   Bugs D y E quedan diagnosticados en §6 con la linea exacta del
   codigo a tocar, listos para el proximo agente. Costaria ~10
   min cada uno pero el operador prefiere priorizar otras tareas
   en su ventana de tiempo.

2. **Mantener el `transactional_db` aunque no era la causa**.
   El cambio es defensivo: previene una trampa real que aparece
   cuando alguien anada un test e2e que escriba a la DB desde
   el thread del test. Reverter seria invitar la trampa de vuelta.

3. **Asserts contra copy literal de Django**. Bug B confirma:
   evitar asserts contra strings que adivinamos para el UX. Usar
   el substring exacto que Django (o el template propio) renderiza,
   con un fallback breve para tolerar snapshots de traduccion.

4. **No promover a main**. Mini-roadmap sigue 12/12 closed
   funcionalmente; el job e2e wire es validacion adicional pero
   no bloquea ningun release del template. `main @ 4b36607` se
   mantiene intacto.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests | 1004 pass |
| E2E tests | 4 collected, 2 pass + 2 fail en CI (Bugs D + E) |
| Coverage | 85% (floor pinned) |
| Ruff | clean local |
| Mypy | 0 errores en 51 archivos src |
| Bandit | Medium: 0 |
| Commits del dia | 4 (incluido este) |
| Lineas tocadas | tests/e2e/ + src/.../circuit_breaker.py + docs |
| Runtime touched | Solo log format `%.0f`→`%.1f` (cosmetico) |
| ASVS L2 | 151 PASS + V12.4.1 + V10.3.x + V14 |
| Mini-roadmap | 12/12 closed |
| CI Lint+Test | ✓ (3.11 + 3.12) |
| CI Supply-chain | ✓ |
| CI E2E | ⚠️ 2/4 pass — Bug D + E pendientes |
| Server `ha-report2` | sin cambio runtime relevante hoy |

## §6. Hallazgos / findings

### 6.1. Bug D — MFA email no se activa por solo setear `mfa_email_enabled`

**Archivo**: `tests/e2e/test_login_flow.py:28-34` (helper
`_enrol_email_mfa`).

**Codigo del test (incorrecto)**:
```python
def _enrol_email_mfa(user):
    user.mfa_email_enabled = True
    user.save(update_fields=["mfa_email_enabled"])
```

**Codigo del runtime que decide si activar el flow MFA**
(`src/ameli_web/accounts/views.py:159`):
```python
if getattr(user, "mfa_enabled", False):
    ...
    return redirect("accounts:verify-mfa")
```

**Causa**: el flag que mira el `LoginView.form_valid` es
`mfa_enabled` (boolean derivado o stored), NO `mfa_email_enabled`.
Setear solo el segundo no enciende el primero, asi que el login
exitoso aterriza directo en `/profile/` (Bug C ya corregido) y
nunca pasa por `/login/verify-mfa/`. El test
`test_login_with_email_mfa_reaches_dashboard` falla con
`TimeoutError` esperando esa URL.

**Fix sugerido** (a confirmar leyendo `accounts/models.py:User`):
```python
def _enrol_email_mfa(user):
    user.mfa_email_enabled = True
    user.mfa_enabled = True  # <-- el flag maestro
    user.save(update_fields=["mfa_email_enabled", "mfa_enabled"])
```

Alternativa mas limpia: invocar el helper real
`enable_email_mfa(user)` de `accounts/services.py` si existe,
que enciende ambos flags de forma consistente con el flow
`/profile/mfa-email-start`. Hay que leer el modelo + servicios
para confirmar la API correcta.

**Costo estimado del fix**: 5-10 min.

### 6.2. Bug E — `/logout/` solo acepta POST, el test hace GET

**Archivo**: `tests/e2e/test_password_change.py:55`.

**Codigo del test (incorrecto)**:
```python
page.goto(f"{live_url}/logout/")
```

**Codigo del runtime** (`src/ameli_web/accounts/views.py:175`):
```python
@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    ...
```

**Causa**: `page.goto()` hace `GET /logout/`. El decorator
`@require_POST` regresa 405 (Method Not Allowed), el log de Django
captura `"Method Not Allowed (GET): /logout/"`. El usuario NUNCA
queda deslogueado, asi que la siguiente navegacion a `/login/` ya
viene autenticado y redirige a `/profile/`, donde no existe el
input `username` — entonces el `page.fill('input[name="username"]')`
de la linea 64 falla con `TimeoutError: waiting for locator`.

**Fix sugerido**:
```python
# Submit the logout form (POST) instead of GET-navigating to /logout/
page.locator('form[action*="logout"] button[type="submit"]').first.click()
page.wait_for_load_state("networkidle")
```

O alternativa equivalente:
```python
page.evaluate("""
    () => {
        const f = document.createElement('form');
        f.method = 'POST';
        f.action = '/logout/';
        // CSRF token from the existing form on the page
        const t = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (t) f.appendChild(t.cloneNode());
        document.body.appendChild(f);
        f.submit();
    }
""")
page.wait_for_load_state("networkidle")
```

La opcion 1 es la mas robusta — el template ya tiene un form
logout en el menu del usuario (`base.html`).

**Costo estimado del fix**: 5-10 min.

### 6.3. Reflexion sobre el diagnostico erroneo de Bug A

La leccion mas clara del dia: la heuristica "si el wrong-password
test pasa entonces el user esta visible" es invalida en este
sistema. Django regresa el MISMO mensaje stock para user-not-found
y wrong-password (anti-enumeration por diseno). Cualquier futuro
diagnostico de e2e tests debe leer el view + settings PRIMERO,
antes de asumir causas indirectas como "cross-thread".

Para validar visibilidad cross-thread en un test futuro, lo
correcto seria hacer un check directo dentro del thread del
live_server (e.g. un endpoint debug que cuente filas, o un
`live_server.thread.run` que lea la DB), no inferir desde el
comportamiento del login.

### 6.4. CI runs relevantes del dia

| Run ID | Commit | Resultado | Job rojo |
|---|---|---|---|
| `28099185292` | `413fd815` | cancelled | (en flight cuando llego 5930ee8) |
| `28099349394` | `5930ee83` | failure | e2e 3/4 fail — Bug A no era la causa, solo Bug B fix tomo |
| `28099841141` | `f4bb1196` | failure | e2e 2/4 fail — Bug C fix tomo, restan Bug D + Bug E |
| (pendiente) | (este commit) | — | cosmetico breaker, no toca e2e |

## §7. Roadmap actualizado

- Mini-roadmap: **12/12 closed**, sin cambios funcionales hoy.
  El job e2e en CI es validacion wire adicional, NO un item del
  roadmap. Los 2 bugs D+E son test-code, no rompen funcionalidad
  ni shipping.
- Roadmap general: nada nuevo abierto hoy. Lo unico que tendria
  sentido anadir como item explicito si se quiere cerrar es:
  - **Hardening e2e suite** (1 dia): fix Bug D + Bug E + escribir
    el helper canonico `enrol_email_mfa(user)` reusable + dejar
    el job e2e verde + agregar 1 test de MFA TOTP para no quedar
    solo con email path + revisar selector strategy (tag-name vs
    name=) para reducir frangibilidad.

## §8. Continuidad — para el proximo agente

### 8.1. Estado snapshot al cierre

- Rama: `dev @ <commit-cierre>` (este push). `main @ 4b36607`
  intacto.
- Unit suite: **1004 pass local**. Coverage 85%.
- E2E suite: 2/4 pass en CI runner (avatar + wrong-password).
  Bug D + Bug E pendientes en §6.
- Server `ha-report2`: NO se ha hecho deploy hoy. Sigue en
  `36c4329` del 22-jun. Los cambios de hoy son tests + cosmetico,
  no requieren deploy.
- ruff/mypy/bandit: clean local.

### 8.2. Pendientes ordenados por prioridad

1. **(opcional)** Bug D — `_enrol_email_mfa` debe encender
   `mfa_enabled`, no solo `mfa_email_enabled`. §6.1. ~10 min.
2. **(opcional)** Bug E — el helper de logout debe POSTear, no
   GET. §6.2. ~10 min.
3. **(cuando los 2 anteriores cierren)** Verificar CI verde
   y, si el operador lo pide explicitamente, considerar promover
   `dev → main` con la convencion "milestone". HOY NO se prometio.

### 8.3. Que NO hacer

- No promover `dev → main` sin instruccion explicita del operador.
- No revertir el `transactional_db` switch. Es defensivo aunque
  no haya sido la causa original.
- No revertir el `wait_for_url("/profile/")` switch. Es la URL
  correcta a la que Django redirige por design.
- No tocar el server `ha-report2` por el job e2e — el e2e corre
  solo en CI runner, el deploy de produccion NO lo necesita.
- No instalar Playwright / chromium en `ha-report2`. El job e2e
  vive 100% en CI por diseno.

### 8.4. Lectura sugerida antes de tocar e2e de nuevo

- `src/ameli_web/accounts/views.py` lineas 100-180 (LoginView +
  form_valid + logout_view).
- `src/ameli_web/accounts/models.py` (definicion de
  `mfa_enabled` vs `mfa_email_enabled`).
- `src/ameli_web/accounts/services.py` (buscar `enable_email_mfa`
  o helper equivalente para no reinventar la enrolment logic).
- `src/ameli_web/settings.py:534` (LOGIN_REDIRECT_URL).
- §6.3 de este handoff (la leccion sobre la heuristica falsa).
