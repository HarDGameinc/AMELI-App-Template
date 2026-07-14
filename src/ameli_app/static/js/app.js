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

const AMELI_PASSWORD_SYMBOLS = "!@#$%^&*()-_=+?";

function ameliRandomIndex(max) {
  // Cryptographic randomness is REQUIRED. ``Math.random`` is a PRNG
  // (seeded once per browsing context, no entropy injection) so the
  // output is predictable to anyone who can observe the sequence.
  // Falling back silently would let a TLS-stripping intermediary or
  // a forensic adversary regenerate the password offline. Refuse
  // instead of producing a weak credential.
  // (SKILLS_REVIEW §4 Security MEDIUM, 2026-06-25.)
  // ``globalThis.crypto`` is the Web Crypto API in browsers AND in
  // Node (global since Node 20) — using it instead of ``window.crypto``
  // lets the pure helpers run under node:test without a DOM.
  const cryptoObj = globalThis.crypto;
  if (!cryptoObj || typeof cryptoObj.getRandomValues !== "function") {
    throw new Error(
      "crypto.getRandomValues is unavailable; refusing to generate a password with non-cryptographic randomness."
    );
  }
  const values = new Uint32Array(1);
  cryptoObj.getRandomValues(values);
  return values[0] % max;
}

function ameliGeneratePassword(length = 18) {
  const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lower = "abcdefghijkmnopqrstuvwxyz";
  const digits = "23456789";
  const all = upper + lower + digits + AMELI_PASSWORD_SYMBOLS;
  try {
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
  } catch (error) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("Password generator unavailable:", error);
    }
    return "";
  }
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
    if (!value) {
      // ``ameliGeneratePassword`` returns "" when crypto.getRandomValues
      // is unavailable. Surface the error and DO NOT touch the inputs
      // so the user is not silently handed a weak / blank credential.
      if (feedback instanceof HTMLElement) {
        feedback.textContent = "No pudimos generar la clave: tu navegador no expone una fuente segura de aleatoriedad.";
      }
      return;
    }
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

if (typeof window !== "undefined") {
  window.AmeliPassword = {
    SYMBOLS: AMELI_PASSWORD_SYMBOLS,
    generate: ameliGeneratePassword,
    evaluate: ameliEvaluatePasswordStrength,
    setupForm: setupPasswordForm,
  };
}


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

// ---- Screen-reader announcements ----
//
// A single visually-hidden polite live region (``#a11y-live`` in base.html).
// Client-side DOM swaps (pagination / filter) announce a concise summary here
// so screen-reader users are told the content changed — ``aria-busy`` alone
// does NOT announce the new content. Clearing then re-setting textContent
// after a short timeout forces assistive tech to re-announce even an
// identical consecutive message (e.g. paging back and forth to the same
// result count). ``setTimeout`` — not ``requestAnimationFrame`` — because rAF
// is paused/throttled in background or non-painting tabs, which would drop
// the announcement.
function announce(message) {
  const region = document.getElementById("a11y-live");
  if (!region || !message) return;
  region.textContent = "";
  window.setTimeout(() => {
    region.textContent = message;
  }, 50);
}

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
    // Announce the new result summary (e.g. "Mostrando 26–50 de 120") so
    // screen-reader users know the swap completed. Falls back to a generic
    // message if the swapped partial has no pagination counter.
    const counter = panel.querySelector(".pagination-counter");
    announce(counter ? counter.textContent.trim() : "Contenido actualizado.");
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
  // Bare ``setTimeout`` / ``clearTimeout`` (not ``window.``-prefixed) so
  // the helper works both in the browser and under node:test.
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
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

// ---- Avatar cropper (progressive enhancement) ----
//
// When the user picks an image in the avatar form we reveal a square
// canvas viewport they can pan (drag / arrow keys) and zoom (slider) to
// choose the framing. On submit we render the visible square to an
// offscreen canvas, export it to a Blob, and swap it into the file input
// via ``DataTransfer`` so the NATIVE form submit carries the cropped
// image — the D-5 server pipeline (resize + WebP + strip EXIF) then does
// the rest. No fetch, no CSRF handling: the existing hidden token rides
// along.
//
// The source image is read with ``FileReader.readAsDataURL`` (a ``data:``
// URL) NOT ``URL.createObjectURL`` (a ``blob:`` URL) so it loads under the
// app CSP ``img-src 'self' data:`` without relaxing the policy.
//
// Everything is feature-gated: a browser missing canvas 2D, FileReader or
// DataTransfer keeps the plain file input, which submits the raw file and
// lets the server pipeline handle it. No JS, no cropper, still works.
function setupAvatarCropper() {
  const form = document.querySelector("[data-avatar-crop-form]");
  const input = document.querySelector("[data-avatar-crop-input]");
  const cropper = document.querySelector("[data-avatar-cropper]");
  const canvas = document.querySelector("[data-avatar-crop-canvas]");
  const zoom = document.querySelector("[data-avatar-crop-zoom]");
  if (!form || !input || !cropper || !(canvas instanceof HTMLCanvasElement) || !zoom) return;

  const ctx = canvas.getContext("2d");
  const supported =
    ctx &&
    typeof window.FileReader === "function" &&
    typeof window.DataTransfer === "function" &&
    typeof canvas.toBlob === "function";
  if (!supported) return;

  const EXPORT_SIZE = 512;       // matches the server AVATAR_MAX_DIMENSION default
  const KEY_PAN_STEP = 12;       // px per arrow-key press
  const view = canvas.width;     // drawing-buffer is square (240)

  const state = { image: null, baseScale: 1, scale: 1, offsetX: 0, offsetY: 0 };

  function clampOffsets(drawW, drawH) {
    // Keep the image covering the viewport — never expose empty gaps.
    state.offsetX = Math.min(0, Math.max(view - drawW, state.offsetX));
    state.offsetY = Math.min(0, Math.max(view - drawH, state.offsetY));
  }

  function effScale() {
    return state.baseScale * state.scale;
  }

  function draw() {
    if (!state.image) return;
    const s = effScale();
    const drawW = state.image.naturalWidth * s;
    const drawH = state.image.naturalHeight * s;
    clampOffsets(drawW, drawH);
    ctx.clearRect(0, 0, view, view);
    ctx.drawImage(state.image, state.offsetX, state.offsetY, drawW, drawH);
  }

  function loadImage(file) {
    const reader = new FileReader();
    reader.onload = () => {
      const image = new Image();
      image.onload = () => {
        const iw = image.naturalWidth;
        const ih = image.naturalHeight;
        if (!iw || !ih) {
          cropper.hidden = true;
          return;
        }
        state.image = image;
        // "cover" fit: smallest scale that fills the square viewport.
        state.baseScale = Math.max(view / iw, view / ih);
        state.scale = 1;
        zoom.value = "1";
        const drawW = iw * state.baseScale;
        const drawH = ih * state.baseScale;
        state.offsetX = (view - drawW) / 2;
        state.offsetY = (view - drawH) / 2;
        cropper.hidden = false;
        draw();
      };
      image.onerror = () => {
        // Not a decodable image — let the native submit + server form
        // validation reject it with a proper message.
        state.image = null;
        cropper.hidden = true;
      };
      image.src = String(reader.result || "");
    };
    reader.onerror = () => {
      state.image = null;
      cropper.hidden = true;
    };
    reader.readAsDataURL(file);
  }

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file || !String(file.type || "").startsWith("image/")) {
      state.image = null;
      cropper.hidden = true;
      return;
    }
    loadImage(file);
  });

  zoom.addEventListener("input", () => {
    if (!state.image) return;
    const prev = effScale();
    state.scale = Number(zoom.value) || 1;
    const next = effScale();
    // Zoom around the viewport centre so the framing stays put.
    const centre = view / 2;
    const ratio = next / prev;
    state.offsetX = centre - (centre - state.offsetX) * ratio;
    state.offsetY = centre - (centre - state.offsetY) * ratio;
    draw();
  });

  // Pointer drag to pan.
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let startOffsetX = 0;
  let startOffsetY = 0;
  canvas.addEventListener("pointerdown", (event) => {
    if (!state.image) return;
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    startOffsetX = state.offsetX;
    startOffsetY = state.offsetY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging || !state.image) return;
    // Canvas CSS size may differ from its drawing buffer; scale the
    // pointer delta into buffer coordinates.
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width ? view / rect.width : 1;
    const scaleY = rect.height ? view / rect.height : 1;
    state.offsetX = startOffsetX + (event.clientX - startX) * scaleX;
    state.offsetY = startOffsetY + (event.clientY - startY) * scaleY;
    draw();
  });
  function endDrag(event) {
    if (!dragging) return;
    dragging = false;
    if (canvas.hasPointerCapture && canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  }
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  // Keyboard pan for accessibility.
  canvas.addEventListener("keydown", (event) => {
    if (!state.image) return;
    const moves = {
      ArrowLeft: [KEY_PAN_STEP, 0],
      ArrowRight: [-KEY_PAN_STEP, 0],
      ArrowUp: [0, KEY_PAN_STEP],
      ArrowDown: [0, -KEY_PAN_STEP],
    };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    state.offsetX += move[0];
    state.offsetY += move[1];
    draw();
  });

  function dataUrlToBlob(dataUrl) {
    const comma = dataUrl.indexOf(",");
    const header = dataUrl.slice(0, comma);
    const mime = (header.match(/data:([^;]+)/) || [])[1] || "image/png";
    const binary = atob(dataUrl.slice(comma + 1));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }

  function buildCroppedFile() {
    const out = document.createElement("canvas");
    out.width = EXPORT_SIZE;
    out.height = EXPORT_SIZE;
    const outCtx = out.getContext("2d");
    if (!outCtx) return null;
    const s = effScale();
    // Source rectangle under the viewport, mapped back to image pixels.
    const sx = -state.offsetX / s;
    const sy = -state.offsetY / s;
    const sSize = view / s;
    outCtx.drawImage(state.image, sx, sy, sSize, sSize, 0, 0, EXPORT_SIZE, EXPORT_SIZE);
    // ``toDataURL`` is SYNCHRONOUS (unlike ``toBlob``), so the file swap
    // in the submit handler happens inside the submit event's own tick —
    // the native submission then serialises the cropped file with no
    // preventDefault and no deferred re-submit. Keeping the
    // click -> navigation chain synchronous is what the browser AND
    // Playwright's auto-wait expect (the async path broke the e2e).
    // Prefer WebP; fall back to PNG if the encoder declined.
    let ext = "webp";
    let dataUrl = out.toDataURL("image/webp", 0.9);
    if (dataUrl.indexOf("data:image/webp") !== 0) {
      dataUrl = out.toDataURL("image/png");
      ext = "png";
    }
    return new File([dataUrlToBlob(dataUrl)], `avatar.${ext}`, { type: `image/${ext}` });
  }

  form.addEventListener("submit", () => {
    // No image staged (a non-image was picked, or it hasn't decoded yet)
    // -> let the native submit carry whatever the input holds.
    if (!state.image || cropper.hidden) return;
    const file = buildCroppedFile();
    if (!file) return; // ctx unavailable -> native submit with the raw file
    const transfer = new DataTransfer();
    transfer.items.add(file);
    // Swap the cropped image into the file input synchronously. We do NOT
    // preventDefault: the browser serialises the form (with the updated
    // files) after this handler returns, so the submission stays native
    // and the click -> redirect chain is synchronous.
    input.files = transfer.files;
  });
}

// ---- Bootstrap (browser only) ----
//
// Guard on ``document`` so this file can be ``require``d in Node for unit
// tests (node:test, see tests/js/) WITHOUT a DOM. The DOM wiring only
// runs in a browser; the pure helpers are exported for Node below. In
// the browser this runs at load (the <script> sits at the end of <body>),
// identical to the previous scattered invocations.
if (typeof document !== "undefined") {
  refreshHealthBadge();
  setupUserMenu();
  setupGlobalPasswordVisibilityToggle();
  setupPaginationSwap();
  setupAuditDatePresets();
  setupBackToTop();
  setupAvatarCropper();
}

// CommonJS export surface for node:test. ``module`` is undefined in the
// browser, so this is a no-op there.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    PASSWORD_SYMBOLS: AMELI_PASSWORD_SYMBOLS,
    generatePassword: ameliGeneratePassword,
    evaluatePasswordStrength: ameliEvaluatePasswordStrength,
    debounce,
  };
}
