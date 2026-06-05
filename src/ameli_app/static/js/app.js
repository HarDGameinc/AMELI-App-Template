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
function setupPaginationSwap() {
  document.addEventListener("click", async (event) => {
    const link = event.target.closest(".pagination-footer a");
    if (!link) return;
    const panel = link.closest("[data-pagination-panel]");
    if (!panel) return;

    const panelKey = panel.dataset.paginationPanel;
    const url = new URL(link.href, window.location.origin);
    const fetchUrl = new URL(url);
    fetchUrl.searchParams.set("partial", panelKey);

    event.preventDefault();
    panel.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(fetchUrl, {
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      panel.innerHTML = html;
      const newUrl = url.pathname + url.search + url.hash;
      window.history.pushState({ panel: panelKey }, "", newUrl);
    } catch (error) {
      // Fall back to a real navigation if the swap fails.
      window.location.href = link.href;
    } finally {
      panel.removeAttribute("aria-busy");
    }
  });
}

setupPaginationSwap();
