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
