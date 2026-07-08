# Frontend Design Review

**Project:** AMELI App Template  
**Review date:** 2026-06-25  
**Version:** v0.4.0-django  
**Lens:** frontend-design skill — distinctive visual identity, deliberate typography, structure as information, restraint

> **STATUS: RESOLVED (2026-07-07).** This review is the source that spawned
> the **D-1 visual-identity** work. All of its recommendations were
> implemented in `v0.4.13`→`v0.4.16` and shipped in `v0.5.0-django`:
> signature element (header "telemetry pulse"), brand palette + **4
> selectable color palettes**, DM Sans / IBM Plex Sans typography, visual
> hierarchy (palette-aware hero + aligned layout), `max-width` shell, and
> a staggered-reveal + hover motion pass. This doc is kept as historical
> rationale; the recommendations below are **done**, not open work.

---

## 1. Subject & Audience

The template is a **Django-first backend shell** for internal AMELI applications. Its frontend is an admin/operations UI — dashboards, user profile, admin panel, login/auth flows. The audience is **operators, admins, and developers**, not end consumers. The page's single job: **let authenticated users manage accounts, monitor system health, and navigate to documentation**. The subject's world is **operational tooling**: metrics, logs, statuses, access control.

---

## 2. Strengths — what works well

### 2.1 Accessibility baseline is solid
- Skip-link, `:focus-visible` rings, `prefers-reduced-motion`, `aria-*` attributes throughout, semantic roles on tab panels and modals.
- Color contrast ratios in both themes are adequate (blue-on-white, light-on-dark).
- `aria-live="polite"` on flash messages and feedback containers is correctly applied.

### 2.2 Theming is well-executed
- Three-mode theme system (light / dark / auto via `prefers-color-scheme`) with CSS custom properties.
- `color-scheme` meta tag correctly matches the active theme to style native controls.
- Dark theme is not an afterthought — every color variable has a dark equivalent.

### 2.3 Responsive behavior is pragmatic
- Breakpoints at 480px, 600px, 680px, 880px, 900px, 980px cover the main mobile/tablet scenarios.
- Tables collapse to stacked card layout with `data-label` pseudo-headers.
- Login grid collapses to single column, modals resize gracefully.

### 2.4 Security-Frontend integration is exemplary
- CSP nonces on all inline scripts.
- Trusted Types policy (`ameli-template`) enforced via CSP.
- SRI hashes on static assets via custom `{% sri_for %}` tag.
- Honeypot field in login form, CSRF on every state-changing action.
- Sudo prompt modal for sensitive admin actions with MFA support.

### 2.5 JS architecture is clean and progressive
- Single `app.js` with delegated event listeners (works after AJAX swaps).
- Password strength meter with real-time policy checks.
- AJAX pagination with `pushState`, debounced filters, partial panel swaps.
- Back-to-top button injected via JS with reduced-motion respect.
- `window.AmeliPassword` public API is well-abstracted.

### 2.6 Copywriting is consistent and intentional
- Spanish UI throughout (matching the audience).
- Active voice: "Crear usuario", "Guardar perfil", "Actualizar contraseña".
- Error messages explain what happened and how to fix it.
- Empty states give direction ("Confirma la contraseña antes de guardar.").

---

## 3. Critique: visual identity

### 3.1 The design has no signature element
The skill says: *"Spend your boldness in one place. Let the signature element be the one memorable thing."* This template does not have one. Every section is a grey panel on a grey background. No hero visual, no characterful header, no typographic moment, no illustration or pattern. The result is **functional but forgettable** — it looks like every other admin panel.

**Recommendation:** Introduce one signature element. For an operational tool, this could be:
- A large, live status indicator or availability bar in the header.
- An animated timeline or health pulse that gives the dashboard a beating heart.
- A distinctive data visualization (even a simple sparkline grid) that immediately communicates "system health at a glance."

### 3.2 Palette is the "warm cream" default
The light theme (`#f6f7fb` bg, `#155eef` accent) falls squarely into the AI-generated default bucket described in the skill: *near-white background, primary blue accent.* No terracotta, no deep indigo, no chartreuse — nothing that ties the template to AMELI's identity. The dark theme is slightly more distinctive (`#0f1420` bg, `#5b8cff` accent) but still generic.

**Recommendation:** Define a palette that comes from the AMELI brand or from the operational tool's subject. Examples:
- A deep navy (`#0a1628`) as primary surface, orange-amber (`#e67e22`) as accent for alerts/warnings.
- A dark slate (`#1a1d23`) with cyan (`#00bcd4`) for a more technical, monitoring-tool feel.
- Keep the blue accent but pair it with a warm grey and a distinct secondary (e.g., teal or coral).

### 3.3 Typography is system-default
`font-family: "Segoe UI", system-ui, -apple-system, sans-serif` — no personality whatsoever. No display face, no body face pairing, no type scale beyond `font-size` values. The skill says: *"Typography carries the personality of the page. Pair the display and body faces deliberately."*

**Recommendation:** Pick one characterful typeface pair:
- **Display:** A geometric sans like DM Sans or Inter for headers (tight tracking, distinctive `R` and `a`).
- **Body:** A humanist sans like Source Sans 3 or IBM Plex Sans for readability at small sizes.
- Load from Google Fonts (already loading Material Symbols) and set a proper type scale (e.g., 12 / 14 / 16 / 20 / 28 / 36 px).

### 3.4 No visual hierarchy beyond panels
All content lives in `.panel` (grey border, 8px radius, white background). There is no visual distinction between primary content, secondary content, and tertiary/ambient information. The layout is a uniform stack of equally-weighted card rectangles.

**Recommendation:** Introduce a visual hierarchy:
- **Hero area** with a colored background or subtle gradient to anchor the page.
- **Primary cards** with a left accent border or a subtle elevation shadow.
- **Secondary sections** demoted with a transparent bg or tighter spacing.
- Use `z-index` sparingly and create real depth with shadows and color.

### 3.5 Icons carry all personality — and it's not enough
Material Symbols Rounded is a good choice (friendly, modern), and the icon usage is correct. But icons alone cannot carry a design. They need typography, color, and layout to land.

---

## 4. Critique: layout and structure

### 4.1 Maximum width feels constraining
`main { max-width: 1280px }` with padding `22px 24px 32px`. For a dashboard/monitoring tool, this is narrow. Many admin panels benefit from 1440px or even full-width on large screens. The sidebar grid (`.grid { 1fr 360px }`) pushes secondary content to the right but the canvas is too small to breathe.

**Recommendation:** Consider `max-width: 1440px` for the main container, or allow the `.admin-layout` and dashboard to go full-width with comfortable inner padding.

### 4.2 Timeline visualization is the most visually interesting element
The `.timeline` component (lines of colored segments showing OPERATIVO/DEGRADADO/FALLA/SIN_DATOS) is the only element that departs from the card-stack pattern. It's good — color-coded, hoverable, with a legend and axis. **This should be the seed of the visual identity.** Build the palette and layout language around this kind of data-forward thinking.

### 4.3 Login page layout is better than the dashboard
The login page uses a `login-shell` grid (`minmax(320px, 520px) minmax(260px, 1fr)`) with a form panel and an info sidebar. This asymmetry is more interesting than the dashboard's uniform grid. It suggests the team knows how to do layout but chose not to apply it to the main pages.

---

## 5. Critique: interaction and motion

### 5.1 Animations are minimal — but inconsistent
- Transitions on metric cards (`.2s`), table rows (`.12s`), password strength bar (`.18s`).
- Back-to-top scroll is smooth.
- But modals appear instantly (no fade/scale). The login shell has no transitions.
- The `prefers-reduced-motion` override is correctly implemented.

**Recommendation:** Consider a **single orchestrated moment** — for example, a staggered fade-in of metric cards on dashboard load. One 400ms staggered reveal would give the page a sense of polish without over-animating.

### 5.2 Hover states are too subtle
`.lines-table tr:hover td { background: rgba(127, 140, 170, 0.04); }` — 4% opacity is almost invisible. `0.10` would still be restrained but actually noticeable.

---

## 6. Critique: copy and content

### 6.1 The subtitle is the closest thing to a "thesis"
`"Base Django-first para apps AMELI con cuentas, perfil, administración y documentación API"` is descriptive but not memorable. The skill says: *"The hero is a thesis. Open with the most characteristic thing."*

**Recommendation:** Lead with **why** the template matters, not **what** it contains. Example: *"El template que hace que la próxima app AMELI arranque con autenticación, auditoría y despliegue — sin reescribir nada."*

### 6.2 The capabilities section is text-heavy
The events list under "Capacidades listas para heredar" is four `<article>` blocks with status badges and tag lists. It's correct but visually dense. Consider a more scannable format — a 2x2 grid of illustrated cards, or a checklist-style layout.

---

## 7. Frontend code quality

### 7.1 CSS is monolithic with good organization
820 lines in one file, organized by component (header, footer, toolbar, metrics, tables, timeline, modals, forms, tabs, responsive). Custom properties at the top, media queries at the bottom. No CSS preprocessor. **This is maintainable for a template** but will need splitting as projects grow.

### 7.2 Inline styles in templates are a code smell
Several templates use `style="..."` attributes: `style="margin-bottom:16px;"`, `style="border-left:4px solid var(--warn-fg)"`, `style="display:flex;gap:12px;..."`. These should be utility classes (e.g., `.mb-16`, `.border-left-warn`, `.flex-row`).

### 7.3 Inline JavaScript in templates is extensive
`admin/panel.html` has ~650 lines of inline JS. `profile.html` has ~470 lines. While CSP nonces make this safe, it's hard to test and maintain. Consider extracting to a page-specific JS file for each major view that uses a data-attribute initialization pattern.

### 7.4 No loading states for AJAX operations
The `aria-busy` attribute is set on panels during swaps, but there is no visual loading indicator (spinner, skeleton). Users see a blank panel briefly. For the email queue widget, polling updates text content without any loading feedback.

### 7.5 CSS selector specificity could cause issues
The skill warns: *"It's easy to generate CSS classes that cancel each other out."* This project has:
- `button` element selector (line 71) setting border, bg, color, border-radius, min-height, padding, cursor, font-weight.
- `.modal-close-dash` needs `background:none; border:none; min-height:auto;` to override.
- `.menu-logout-btn` needs `width:100%; border:1px solid...` to re-override.
- This cascading reset pattern works but is brittle. Consider removing the `button` base styles and using class-based selectors everywhere.

---

## 8. Summary: what to prioritize

| Priority | Issue | Impact |
|----------|-------|--------|
| **P0** | No signature element — template looks like every other admin panel | Brand identity, memorability |
| **P0** | System-default typography, no type personality | Visual polish, design maturity |
| **P1** | Palette is the generic AI-default blue-on-white | Distinctiveness |
| **P1** | No visual hierarchy beyond identical `.panel` cards | Scannability, information design |
| **P1** | Inline styles in templates instead of utility classes | Maintainability |
| **P2** | Max-width 1280px is tight for monitoring dashboards | Layout, usability on wide screens |
| **P2** | No loading spinners/skeletons during AJAX | Perceived performance |
| **P2** | Button element selector causes cascading override patterns | CSS robustness |
| **P3** | Inline JS in templates should be extracted | Testability |
| **P3** | Hover states are too subtle (4% opacity) | Interaction feedback |

---

## 9. Visual identity proposal (if redesigning today)

- **Palette:** `#0b1420` (deep navy bg), `#1a2332` (surface), `#e8edf5` (ink), `#00c9a7` (accent — teal-green, feels operational/healthy), `#f59e0b` (warn — amber), `#ef4444` (bad — red).
- **Type:** DM Sans (display, weights 500/700) + IBM Plex Sans (body, weight 400/600).
- **Signature:** An animated multi-line health sparkline in the header — three colored traces (uptime, latency, error rate) that pulse gently, giving the dashboard a living heartbeat.
- **Layout:** 1440px max-width, hero area with subtle gradient background, primary panels with a 3px left accent border keyed to status color.
- **Motion:** Single staggered reveal on page load (cards fade in 100ms apart), zero animation on subsequent AJAX swaps.
