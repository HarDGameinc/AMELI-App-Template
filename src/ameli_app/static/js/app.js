async function refreshHealthBadge() {
  const badge = document.querySelector(".status");
  if (!badge) return;

  try {
    const response = await fetch("/health", { cache: "no-store" });
    const payload = await response.json();
    if (payload.ok && payload.version) {
      badge.textContent = payload.version;
    }
  } catch {
    // Keep the existing label when health cannot be fetched.
  }
}

refreshHealthBadge();

function setupUserMenu() {
  const toggle = document.querySelector("[data-user-menu-toggle]");
  const panel = document.querySelector("[data-user-menu-panel]");
  if (!(toggle instanceof HTMLElement) || !(panel instanceof HTMLElement)) return;

  function closeMenu() {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  function openMenu() {
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
  }

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    if (panel.hidden) {
      openMenu();
      return;
    }
    closeMenu();
  });

  panel.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
}

setupUserMenu();

const AMELI_PASSWORD_SYMBOLS = "!@#$%^&*()-_=+?";

function ameliRandomIndex(max) {
  if (window.crypto?.getRandomValues) {
    const values = new Uint32Array(1);
    window.crypto.getRandomValues(values);
    return values[0] % max;
  }
  return Math.floor(Math.random() * max);
}

function ameliGeneratePassword(length = 18) {
  const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lower = "abcdefghijkmnopqrstuvwxyz";
  const digits = "23456789";
  const all = upper + lower + digits + AMELI_PASSWORD_SYMBOLS;
  const chars = [
    upper[ameliRandomIndex(upper.length)],
    lower[ameliRandomIndex(lower.length)],
    digits[ameliRandomIndex(digits.length)],
    AMELI_PASSWORD_SYMBOLS[ameliRandomIndex(AMELI_PASSWORD_SYMBOLS.length)],
  ];
  while (chars.length < length) {
    chars.push(all[ameliRandomIndex(all.length)]);
  }
  for (let index = chars.length - 1; index > 0; index -= 1) {
    const swapIndex = ameliRandomIndex(index + 1);
    [chars[index], chars[swapIndex]] = [chars[swapIndex], chars[index]];
  }
  return chars.join("");
}

function ameliEvaluatePasswordStrength(value) {
  const text = String(value || "");
  const checks = {
    length: text.length >= 12,
    upper: /[A-Z]/.test(text),
    lower: /[a-z]/.test(text),
    digit: /\d/.test(text),
    symbol: [...text].some((char) => AMELI_PASSWORD_SYMBOLS.includes(char)),
  };
  const score = Object.values(checks).filter(Boolean).length;
  if (score <= 2) {
    return { level: "weak", label: "Debil", hint: "Debe tener al menos 12 caracteres.", percent: 24, checks };
  }
  if (score <= 4) {
    return { level: "medium", label: "Media", hint: "Cumple la base, pero aun puedes reforzarla.", percent: 62, checks };
  }
  return { level: "strong", label: "Fuerte", hint: "Cumple largo, mezcla y simbolos permitidos.", percent: 100, checks };
}

function setupGlobalPasswordVisibilityToggle() {
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-password-toggle]");
    if (!toggle) return;
    const target = document.getElementById(toggle.dataset.passwordToggle || "");
    if (!(target instanceof HTMLInputElement)) return;
    const nextType = target.type === "password" ? "text" : "password";
    target.type = nextType;
    const icon = toggle.querySelector(".material-symbols-rounded");
    if (icon) icon.textContent = nextType === "password" ? "visibility" : "visibility_off";
  });
}

setupGlobalPasswordVisibilityToggle();

function setupPasswordForm(container, options = {}) {
  if (!(container instanceof Element)) return null;

  const newInput = container.querySelector("[data-password-new]");
  if (!(newInput instanceof HTMLInputElement)) return null;

  const confirmInput = container.querySelector("[data-password-confirm]");
  const generateButton = container.querySelector("[data-password-generate]");
  const strengthBar = container.querySelector("[data-password-strength-bar]");
  const strengthLabel = container.querySelector("[data-password-strength-label]");
  const strengthHint = container.querySelector("[data-password-strength-hint]");
  const matchHint = container.querySelector("[data-password-match-hint]");
  const submitButton = container.querySelector("[data-password-submit]");
  const feedback = container.querySelector("[data-password-feedback]");

  const policyItems = new Map(
    Array.from(container.querySelectorAll("[data-policy-check]")).map((node) => [node.dataset.policyCheck, node])
  );

  const generatedMessage =
    options.generatedMessage ||
    "Contrasena generada con el estandar permitido. Guardala en un lugar seguro antes de continuar.";

  function syncStrength() {
    const state = ameliEvaluatePasswordStrength(newInput.value);
    if (strengthBar instanceof HTMLElement) {
      strengthBar.style.width = `${state.percent}%`;
      strengthBar.classList.remove("weak", "medium", "strong");
      strengthBar.classList.add(state.level);
    }
    if (strengthLabel instanceof HTMLElement) strengthLabel.textContent = state.label;
    if (strengthHint instanceof HTMLElement) strengthHint.textContent = state.hint;
    Object.entries(state.checks).forEach(([key, valid]) => {
      const node = policyItems.get(key);
      if (!node) return;
      node.classList.toggle("pass", valid);
      node.classList.toggle("fail", !valid);
    });
    return state;
  }

  function syncMatch() {
    if (!(matchHint instanceof HTMLElement) || !(confirmInput instanceof HTMLInputElement)) {
      return Boolean(confirmInput ? confirmInput.value && confirmInput.value === newInput.value : true);
    }
    const next = String(newInput.value || "");
    const confirmed = String(confirmInput.value || "");
    if (!confirmed) {
      matchHint.textContent = "Confirma la nueva contrasena antes de guardar.";
      matchHint.classList.remove("warn-text", "ok-text");
      return false;
    }
    if (next !== confirmed) {
      matchHint.textContent = "La confirmacion no coincide con la nueva contrasena.";
      matchHint.classList.add("warn-text");
      matchHint.classList.remove("ok-text");
      return false;
    }
    matchHint.textContent = "La confirmacion coincide.";
    matchHint.classList.remove("warn-text");
    matchHint.classList.add("ok-text");
    return true;
  }

  function sync() {
    const strength = syncStrength();
    const matches = confirmInput ? syncMatch() : true;
    const valid = strength.level !== "weak" && matches;
    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = !valid;
    return { strength, matches, valid };
  }

  function reveal(inputElement) {
    if (!(inputElement instanceof HTMLInputElement)) return;
    inputElement.type = "text";
    const toggleSelector = `[data-password-toggle="${inputElement.id}"]`;
    container.querySelectorAll(toggleSelector).forEach((button) => {
      const icon = button.querySelector(".material-symbols-rounded");
      if (icon) icon.textContent = "visibility_off";
    });
  }

  generateButton?.addEventListener("click", () => {
    const value = ameliGeneratePassword();
    newInput.value = value;
    reveal(newInput);
    if (confirmInput instanceof HTMLInputElement) {
      confirmInput.value = value;
      reveal(confirmInput);
    }
    if (feedback instanceof HTMLElement) feedback.textContent = generatedMessage;
    sync();
  });

  newInput.addEventListener("input", sync);
  confirmInput?.addEventListener("input", sync);
  sync();

  return {
    sync,
    isValid: () => sync().valid,
    getValue: () => String(newInput.value || ""),
    elements: { container, newInput, confirmInput, generateButton, submitButton, feedback },
  };
}

window.AmeliPassword = {
  SYMBOLS: AMELI_PASSWORD_SYMBOLS,
  generate: ameliGeneratePassword,
  evaluate: ameliEvaluatePasswordStrength,
  setupForm: setupPasswordForm,
};


// ---- Pagination AJAX swap ----
//
// Any pagination footer link inside a node tagged with
// ``data-pagination-panel="<id>"`` is intercepted: instead of triggering a
// full reload we fetch the same URL with ``?partial=<id>`` appended and
// replace the panel's innerHTML with the response. ``history.pushState``
// keeps the URL bookmarkeable. If the fetch fails (offline, server error,
// no JS) the link falls back to its native navigation.
//
// The same panel can also host a filter ``<form data-filter-form>``: as the
// user types or changes a select, we debounce/snapshot the form and reissue
// the request through the same swap path so filter and pagination stay
// consistent without the page ever reloading.

async function swapPanelTo(panel, targetUrl) {
  const panelKey = panel.dataset.paginationPanel;
  const url = new URL(targetUrl, window.location.origin);
  const fetchUrl = new URL(url);
  fetchUrl.searchParams.set("partial", panelKey);
  // Strip ``partial`` from the URL we push to history — if the user
  // refreshes after an AJAX swap, we want the full page back, not the
  // partial template rendered without layout/css.
  url.searchParams.delete("partial");

  panel.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(fetchUrl, {
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const html = await response.text();
    panel.innerHTML = window.ameliTrusted.createHTML(html);
    const newUrl = url.pathname + url.search + url.hash;
    window.history.pushState({ panel: panelKey }, "", newUrl);
    return true;
  } catch (error) {
    window.location.href = targetUrl;
    return false;
  } finally {
    panel.removeAttribute("aria-busy");
  }
}

function buildFilterFormUrl(form, panel) {
  const params = new URLSearchParams();
  const current = new URLSearchParams(window.location.search);
  const formData = new FormData(form);
  const formKeys = new Set(Array.from(formData.keys()));
  for (const [key, value] of current.entries()) {
    if (!formKeys.has(key) && key !== "partial") params.set(key, value);
  }
  for (const [key, value] of formData.entries()) {
    if (value === "" || value === null || value === undefined) continue;
    params.set(key, value);
  }
  // Reset the panel's own page when filters change.
  const pageParam = `${panel.dataset.paginationPanel}_page`;
  params.delete(pageParam);
  const action = form.getAttribute("action") || window.location.pathname;
  const query = params.toString();
  const anchor = window.location.hash || (panel.id ? `#${panel.id}` : "");
  return query ? `${action}?${query}${anchor}` : `${action}${anchor}`;
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function buildPageSizeUrl(select, panel) {
  const param = select.dataset.perPageParam || "per_page";
  const url = new URL(window.location.href);
  url.searchParams.set(param, select.value);
  // Reset the panel's own page when the size changes; otherwise a deep
  // page can stop existing entirely with the new per_page.
  const pageParam = `${panel.dataset.paginationPanel}_page`;
  url.searchParams.delete(pageParam);
  url.searchParams.delete("partial");
  const anchor = url.hash || (panel.id ? `#${panel.id}` : "");
  return `${url.pathname}?${url.searchParams.toString()}${anchor}`;
}

function setupPaginationSwap() {
  document.addEventListener("click", async (event) => {
    // Intercept any link that should swap a paginated panel in place: the
    // Prev/Next links inside ``.pagination-footer`` and the ``Limpiar
    // filtros`` link (``[data-clear-filters]``) on filter toolbars.
    const link = event.target.closest(".pagination-footer a, [data-clear-filters]");
    if (!link) return;
    const panel = link.closest("[data-pagination-panel]");
    if (!panel) return;
    event.preventDefault();
    swapPanelTo(panel, link.href);
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (!target.matches("[data-page-size]")) return;
    const panel = target.closest("[data-pagination-panel]");
    if (!panel) return;
    swapPanelTo(panel, buildPageSizeUrl(target, panel));
  });

  const debouncedSwap = debounce((panel, url) => swapPanelTo(panel, url), 250);

  function maybeSwapFromForm(form, { immediate }) {
    const panel = form.closest("[data-pagination-panel]");
    if (!panel) return;
    const url = buildFilterFormUrl(form, panel);
    if (immediate) {
      swapPanelTo(panel, url);
    } else {
      debouncedSwap(panel, url);
    }
  }

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    const form = input.closest("form[data-filter-form]");
    if (!form) return;
    maybeSwapFromForm(form, { immediate: false });
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    const form = target.closest("form[data-filter-form]");
    if (!form) return;
    maybeSwapFromForm(form, { immediate: true });
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.matches("form[data-filter-form]")) return;
    event.preventDefault();
    maybeSwapFromForm(form, { immediate: true });
  });
}

setupPaginationSwap();


// ---- Audit date range presets ----
//
// Buttons inside ``[data-audit-date-presets]`` set the ``audit_date_from``
// and ``audit_date_to`` inputs to a quick preset (Today / Yesterday /
// 7 days / 30 days) and dispatch ``input`` events so the existing AJAX
// swap helper picks the change up and reloads the panel without a full
// page reload. ISO ``YYYY-MM-DD`` keeps the server-side parser happy.
function isoDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function setupAuditDatePresets() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-audit-preset]");
    if (!button) return;
    event.preventDefault();
    const form = button.closest("form[data-filter-form]");
    if (!form) return;
    const fromInput = form.querySelector("[data-audit-date-from]");
    const toInput = form.querySelector("[data-audit-date-to]");
    if (!fromInput || !toInput) return;

    const preset = button.dataset.auditPreset;
    const today = new Date();
    let from = today;
    let to = today;
    if (preset === "yesterday") {
      const y = new Date(today);
      y.setDate(today.getDate() - 1);
      from = y;
      to = y;
    } else if (preset === "7d") {
      from = new Date(today);
      from.setDate(today.getDate() - 6);
      to = today;
    } else if (preset === "30d") {
      from = new Date(today);
      from.setDate(today.getDate() - 29);
      to = today;
    }

    fromInput.value = isoDate(from);
    toInput.value = isoDate(to);
    // ``input`` events trigger the debounced filter-form swap registered
    // in ``setupPaginationSwap``; fire on both so the second input cannot
    // race ahead with stale state.
    fromInput.dispatchEvent(new Event("input", { bubbles: true }));
    toInput.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

setupAuditDatePresets();


// ---- Back to top button ----
//
// Injects a single floating button bottom-right that appears once the
// viewport scrolls past ``SCROLL_TRIGGER_PX``. Clicking it smoothly
// returns the user to the top. Honors ``prefers-reduced-motion`` for the
// scroll animation. Inserted via JS so individual templates don't have to
// opt in — every page that loads ``app.js`` gets the helper.
function setupBackToTop() {
  const SCROLL_TRIGGER_PX = 400;
  if (document.querySelector("[data-back-to-top]")) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "back-to-top";
  button.setAttribute("data-back-to-top", "");
  button.setAttribute("aria-label", "Volver al inicio de la pagina");
  button.hidden = true;
  const glyph = document.createElement("span");
  glyph.className = "material-symbols-rounded icon-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = "keyboard_arrow_up";
  const label = document.createElement("span");
  label.className = "back-to-top-label";
  label.textContent = "Arriba";
  button.append(glyph, label);
  document.body.appendChild(button);

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function updateVisibility() {
    const shouldShow = window.scrollY > SCROLL_TRIGGER_PX;
    if (shouldShow === !button.hidden) return;
    button.hidden = !shouldShow;
  }

  window.addEventListener("scroll", updateVisibility, { passive: true });
  window.addEventListener("resize", updateVisibility, { passive: true });
  updateVisibility();

  button.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  });
}

setupBackToTop();
