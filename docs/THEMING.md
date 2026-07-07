# Theming (light / dark / auto)

The template ships a three-mode theme system driven by CSS custom
properties. This note exists because the **Auto** mode's dependence on the
browser (not just the OS) surprised an operator on 2026-07-06 — the app
looked correct, the confusion was entirely browser-side.

## The three modes

Set per user in **Profile → General → "Tema preferido"**:

- **Claro** — forces the light palette.
- **Oscuro** — forces the dark palette.
- **Auto** (default) — follows the browser's `prefers-color-scheme`.

## How it works (no JS theme switcher)

`accounts/context_processors.py` computes `active_theme`:

```python
active_theme = theme_preference  if theme_preference in {"light", "dark"}  else ""
```

`base.html` then renders:

```html
<html {% if active_theme %}data-theme="{{ active_theme }}"{% endif %} ...>
```

- **Claro / Oscuro** → `data-theme="light"|"dark"` on `<html>` → the CSS
  `:root[data-theme="…"]` block wins. Deterministic, independent of the
  browser.
- **Auto** → **no** `data-theme` attribute → the CSS falls through to
  `@media (prefers-color-scheme: dark) :root:not([data-theme="light"]):not([data-theme="dark"])`.
  So Auto = whatever the browser reports for `prefers-color-scheme`.

There is no JavaScript theme toggle; it is pure CSS + one server-rendered
attribute. `app.css` defines both palettes plus the `--*-fill` tokens (the
colour to use behind white text on filled buttons/pills — see the
`## State of the project` notes and `docs/DECISIONS.md`).

## The gotcha: Auto follows the BROWSER, not "what the OS looks like"

`prefers-color-scheme` is reported by the **browser**, which normally
derives it from the OS *app colour mode* — but it can be overridden:

- **Windows**: Settings → Personalization → Colors → "Choose your mode".
  A light *Windows* mode with a dark *app* mode makes browsers report
  **dark** even though the wallpaper/taskbar look light.
- **Firefox**: `about:preferences` → General → **"Website appearance"**
  (Auto / Light / Dark) is an independent control. "Auto"/"System" tracks
  the Firefox theme and `ui.systemUsesDarkTheme`, which an **enterprise
  policy** (managed browser) can pin to dark.
- Chromium browsers (Chrome / Edge / Brave) follow the OS app mode
  directly and generally match.

**Diagnostic** — in the page console:

```js
matchMedia('(prefers-color-scheme: dark)').matches
```

`true` → the browser is reporting dark, so Auto renders dark **correctly**.
To rule out a browser extension, retest in Firefox **Troubleshoot Mode**
(Help → Troubleshoot Mode, extensions off): if it is still `true`, it is a
policy / OS pref, not an extension.

**Fixes (all browser-side; the app needs no change):**

- In the app: pick **Claro** or **Oscuro** explicitly in the profile —
  this always wins regardless of the browser.
- In Firefox: set "Website appearance" to **Claro**, or the Firefox theme
  to **System**, or `about:config` →
  `layout.css.prefers-color-scheme.content-override` = `1` (light).
- In Windows: set Colors → mode → Light.

## Accessibility

Both palettes are contrast-checked in CI: `tests/e2e/test_accessibility.py`
runs axe-core (WCAG 2.1 A/AA) with `page.emulate_media(color_scheme=…)` for
**both** light and dark, so a palette change that breaks contrast in either
theme fails the build deterministically — no reliance on the runner's OS
theme.
