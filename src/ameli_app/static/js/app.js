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
