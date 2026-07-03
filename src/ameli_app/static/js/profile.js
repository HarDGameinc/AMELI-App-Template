// AMELI profile page behaviour — tab navigation, password change, MFA
// enrollment/disable (TOTP + email), recovery-code tools and email
// change. Extracted from the inline <script> in accounts/profile.html
// (frontend-debt split). Server-rendered URLs arrive via data-* on the
// #profile-js-config element; the CSRF token is read from the page form
// hidden input, exactly as the inline version did.
document.addEventListener("DOMContentLoaded", () => {
  const cfg = (document.getElementById("profile-js-config") || {}).dataset || {};
  const passwordForm = document.getElementById("profile-password-form");
  const passwordCurrentInput = document.getElementById("profile-cp-current");
  const passwordFeedback = document.getElementById("profile-password-feedback");
  const passwordExperience = passwordForm && window.AmeliPassword
    ? window.AmeliPassword.setupForm(passwordForm)
    : null;

  function activateTabById(tabId, options = {}) {
    const updateHash = options.updateHash !== false;
    let activated = false;
    document.querySelectorAll(".tab-nav").forEach((nav) => {
      const btn = nav.querySelector(`button[data-tab="${tabId}"]`);
      if (!btn) return;
      nav.querySelectorAll("button[data-tab]").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      const target = document.getElementById(tabId);
      if (target) target.classList.add("active");
      activated = true;
    });
    if (activated && updateHash) {
      history.replaceState(null, "", `#${tabId}`);
    }
    return activated;
  }

  document.querySelectorAll(".tab-nav").forEach((nav) => {
    nav.querySelectorAll("button[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activateTabById(btn.dataset.tab);
      });
    });
  });

  // Restore the active tab from the URL hash so Prev/Next links in
  // paginated panels stay on the same tab they were navigated from.
  const initialHash = (window.location.hash || "").replace(/^#/, "");
  if (initialHash) {
    activateTabById(initialHash, { updateHash: false });
  }
  window.addEventListener("hashchange", () => {
    const hash = (window.location.hash || "").replace(/^#/, "");
    if (hash) activateTabById(hash, { updateHash: false });
  });

  document.querySelectorAll("[data-tab-trigger]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.tabTrigger;
      const trigger = document.querySelector(`.tab-nav button[data-tab="${targetId}"]`);
      trigger?.click();
    });
  });

  passwordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!passwordExperience) return;
    const state = passwordExperience.sync();
    if (!state.matches) {
      if (passwordFeedback) passwordFeedback.textContent = "Confirma la nueva contrasena antes de guardar.";
      return;
    }
    if (state.strength.level === "weak") {
      if (passwordFeedback) passwordFeedback.textContent = "La nueva contrasena aun es debil. Refuerzala antes de guardar.";
      return;
    }
    if (passwordFeedback) passwordFeedback.textContent = "Guardando...";
    try {
      const payload = {
        current_password: String(passwordCurrentInput?.value || ""),
        new_password: passwordExperience.getValue(),
      };
      const response = await fetch(cfg.urlPassword, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "",
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "No se pudo actualizar la contrasena.");
      }
      if (passwordFeedback) {
        passwordFeedback.textContent = data.status
          ? `OK: ${data.status}. Otras sesiones revocadas: ${Number(data.revoked_sessions || 0)}. Recargando perfil...`
          : "Contrasena actualizada. Recargando perfil...";
      }
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      if (passwordFeedback) {
        passwordFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
      }
    }
  });

  // ``profile-email-test`` button used to live in the General tab; it
  // moved out when the email field migrated to the double-opt-in card.
  // The handler stays no-op-safe via ``?.`` in case a future iteration
  // brings the button back.

  // ---- MFA enrollment / disable ----
  const csrfTokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  const mfaPanel = document.getElementById("profile-mfa-panel");
  const mfaSections = {
    stacked: document.getElementById("profile-mfa-stacked"),
    pending: document.getElementById("profile-mfa-pending"),
    emailPending: document.getElementById("profile-mfa-email-pending"),
    recovery: document.getElementById("profile-mfa-recovery"),
  };

  function showMfaSection(name) {
    Object.entries(mfaSections).forEach(([key, node]) => {
      if (node) node.hidden = key !== name;
    });
  }

  async function postJson(url, payload = null) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-csrf-token": csrfTokenInput,
      },
      body: payload === null ? "" : JSON.stringify(payload),
    });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Operacion no completada.");
    }
    return data;
  }

  const activateBtn = document.getElementById("profile-mfa-activate");
  const activatePassword = document.getElementById("profile-mfa-totp-activate-password");
  const activateFeedback = document.getElementById("profile-mfa-activate-feedback");
  const verifyBtn = document.getElementById("profile-mfa-verify");
  const cancelBtn = document.getElementById("profile-mfa-cancel");
  const verifyFeedback = document.getElementById("profile-mfa-verify-feedback");
  const codeInput = document.getElementById("profile-mfa-code");
  const qrSlot = document.getElementById("profile-mfa-qr");
  const secretText = document.getElementById("profile-mfa-secret-text");
  const recoveryAck = document.getElementById("profile-mfa-recovery-ack");
  const recoveryList = document.getElementById("profile-mfa-recovery-list");
  const totpDisableBtn = document.getElementById("profile-mfa-totp-disable");
  const totpDisablePassword = document.getElementById("profile-mfa-totp-disable-password");
  const totpDisableFeedback = document.getElementById("profile-mfa-totp-disable-feedback");
  const emailDisableBtn = document.getElementById("profile-mfa-email-disable");
  const emailDisablePassword = document.getElementById("profile-mfa-email-disable-password");
  const emailDisableFeedback = document.getElementById("profile-mfa-email-disable-feedback");
  const regenerateBtn = document.getElementById("profile-mfa-regenerate");
  const regeneratePassword = document.getElementById("profile-mfa-regenerate-password");
  const regenerateFeedback = document.getElementById("profile-mfa-regenerate-feedback");
  const emailActivateBtn = document.getElementById("profile-mfa-email-activate");
  const emailActivatePassword = document.getElementById("profile-mfa-email-activate-password");
  const emailVerifyBtn = document.getElementById("profile-mfa-email-verify");
  const emailCancelBtn = document.getElementById("profile-mfa-email-cancel");
  const emailCodeInput = document.getElementById("profile-mfa-email-code");
  const emailVerifyFeedback = document.getElementById("profile-mfa-email-verify-feedback");

  activateBtn?.addEventListener("click", async () => {
    // Cookie-thief hardening (PHASE_B Bloque A1): the backend now
    // requires the current password to provision a fresh TOTP secret
    // so a stolen session alone cannot enroll the attacker's
    // authenticator on the victim's account. D-2: the re-auth uses an
    // inline password field (matching the disable flow) instead of a
    // native browser prompt dialog.
    const currentPassword = String(activatePassword?.value || "").trim();
    if (!currentPassword) {
      if (activateFeedback) activateFeedback.textContent = "Confirma tu contrasena para activar.";
      activatePassword?.focus();
      return;
    }
    activateBtn.disabled = true;
    if (activateFeedback) activateFeedback.textContent = "Generando codigo QR...";
    try {
      const data = await postJson(
        cfg.urlMfaStart,
        { current_password: currentPassword },
      );
      if (activatePassword) activatePassword.value = "";
      if (qrSlot) qrSlot.innerHTML = window.ameliTrusted.createHTML(data.qr_svg || "");
      if (secretText) secretText.textContent = data.secret || "-";
      if (codeInput) codeInput.value = "";
      if (verifyFeedback) verifyFeedback.textContent = "";
      if (activateFeedback) activateFeedback.textContent = "";
      showMfaSection("pending");
      codeInput?.focus();
    } catch (error) {
      if (activateFeedback) activateFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    } finally {
      activateBtn.disabled = false;
    }
  });

  cancelBtn?.addEventListener("click", async () => {
    try {
      await postJson(cfg.urlMfaDisable, { current_password: "" });
    } catch {
      // Even if the server rejects (no password), we just close the pending UI.
    }
    window.location.reload();
  });

  function showRecoveryOrReload(codes) {
    if (!Array.isArray(codes) || codes.length === 0) {
      window.location.reload();
      return;
    }
    if (recoveryList) {
      recoveryList.replaceChildren();
      codes.forEach((codeValue) => {
        const li = document.createElement("li");
        li.textContent = codeValue;
        recoveryList.appendChild(li);
      });
    }
    showMfaSection("recovery");
    setupRecoveryTools(codes);
  }

  function setupRecoveryTools(codes) {
    const feedback = document.getElementById("profile-mfa-recovery-feedback");
    const flash = (message) => {
      if (!feedback) return;
      feedback.textContent = message;
      setTimeout(() => { if (feedback.textContent === message) feedback.textContent = ""; }, 3000);
    };
    const text = codes.join("\n") + "\n";

    // Legacy fallback for non-secure (HTTP) contexts — e.g. an internal
    // operational network without TLS. A temp textarea + execCommand is
    // the only path that copies without the async Clipboard API. It runs
    // ONLY when isSecureContext is false, so an HTTPS/Caddy deploy uses
    // the modern API below and never touches execCommand.
    const legacyCopy = (value) => {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (err) {
        ok = false;
      }
      document.body.removeChild(ta);
      return ok;
    };

    const copyBtn = document.getElementById("profile-mfa-recovery-copy");
    if (copyBtn) {
      copyBtn.onclick = async () => {
        // Prefer the async Clipboard API — it requires a secure context
        // (HTTPS or localhost). In HTTPS/prod this is the only branch taken.
        if (window.isSecureContext && navigator.clipboard) {
          try {
            await navigator.clipboard.writeText(text);
            flash("Copiados al portapapeles");
            return;
          } catch (err) {
            // fall through to the legacy path
          }
        }
        if (legacyCopy(text)) {
          flash("Copiados al portapapeles");
        } else {
          flash("No se pudo copiar — selecciona y copia manualmente");
        }
      };
    }

    const dlBtn = document.getElementById("profile-mfa-recovery-download");
    if (dlBtn) {
      dlBtn.onclick = () => {
        const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        const stamp = new Date().toISOString().slice(0, 10);
        a.download = `ameli-recovery-codes-${stamp}.txt`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
        flash("Archivo descargado");
      };
    }

    const printBtn = document.getElementById("profile-mfa-recovery-print");
    if (printBtn) {
      printBtn.onclick = () => {
        const w = window.open("", "_blank");
        if (!w) { flash("Habilita popups para imprimir"); return; }
        const doc = w.document;
        doc.title = "Codigos de recuperacion AMELI";
        const style = doc.createElement("style");
        style.textContent = "body{font-family:monospace;font-size:14pt;padding:24pt;}li{margin:6pt 0;}";
        doc.head.appendChild(style);
        const h2 = doc.createElement("h2");
        h2.textContent = "Codigos de recuperacion";
        const intro = doc.createElement("p");
        const em = doc.createElement("em");
        em.textContent = "Guarda esta hoja en un lugar seguro.";
        intro.appendChild(em);
        const ul = doc.createElement("ul");
        codes.forEach((c) => {
          const li = doc.createElement("li");
          li.textContent = c;
          ul.appendChild(li);
        });
        doc.body.append(h2, intro, ul);
        w.focus();
        w.print();
      };
    }
  }

  verifyBtn?.addEventListener("click", async () => {
    const code = String(codeInput?.value || "").trim();
    if (!code) {
      if (verifyFeedback) verifyFeedback.textContent = "Tipeá el código de la app.";
      return;
    }
    verifyBtn.disabled = true;
    if (verifyFeedback) verifyFeedback.textContent = "Verificando...";
    try {
      const data = await postJson(cfg.urlMfaConfirm, { code });
      showRecoveryOrReload(data.recovery_codes);
    } catch (error) {
      if (verifyFeedback) verifyFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    } finally {
      verifyBtn.disabled = false;
    }
  });

  recoveryAck?.addEventListener("click", () => {
    window.location.reload();
  });

  function wireDisableButton(btn, passwordInput, feedback, url, label) {
    btn?.addEventListener("click", async () => {
      const password = String(passwordInput?.value || "").trim();
      if (!password) {
        if (feedback) feedback.textContent = "Confirma tu contrasena para desactivar.";
        return;
      }
      btn.disabled = true;
      if (feedback) feedback.textContent = "Desactivando...";
      try {
        await postJson(url, { current_password: password });
        if (feedback) feedback.textContent = label + " desactivado. Recargando...";
        window.setTimeout(() => window.location.reload(), 400);
      } catch (error) {
        if (feedback) feedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
        btn.disabled = false;
      }
    });
  }

  wireDisableButton(totpDisableBtn, totpDisablePassword, totpDisableFeedback,
    cfg.urlMfaTotpDisable, "App de autenticacion");
  wireDisableButton(emailDisableBtn, emailDisablePassword, emailDisableFeedback,
    cfg.urlMfaEmailDisable, "Email");

  emailActivateBtn?.addEventListener("click", async () => {
    // Cookie-thief hardening (PHASE_B Bloque A2): re-auth required.
    // D-2: inline password field instead of a native browser prompt dialog.
    const currentPassword = String(emailActivatePassword?.value || "").trim();
    if (!currentPassword) {
      if (activateFeedback) activateFeedback.textContent = "Confirma tu contrasena para activar.";
      emailActivatePassword?.focus();
      return;
    }
    emailActivateBtn.disabled = true;
    if (activateFeedback) activateFeedback.textContent = "Enviando codigo...";
    try {
      await postJson(
        cfg.urlMfaEmailStart,
        { current_password: currentPassword },
      );
      if (emailActivatePassword) emailActivatePassword.value = "";
      if (emailCodeInput) emailCodeInput.value = "";
      if (emailVerifyFeedback) emailVerifyFeedback.textContent = "";
      if (activateFeedback) activateFeedback.textContent = "";
      showMfaSection("emailPending");
      emailCodeInput?.focus();
    } catch (error) {
      if (activateFeedback) activateFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    } finally {
      emailActivateBtn.disabled = false;
    }
  });

  emailCancelBtn?.addEventListener("click", () => {
    window.location.reload();
  });

  emailVerifyBtn?.addEventListener("click", async () => {
    const code = String(emailCodeInput?.value || "").trim();
    if (!code) {
      if (emailVerifyFeedback) emailVerifyFeedback.textContent = "Tipea el codigo recibido por email.";
      return;
    }
    emailVerifyBtn.disabled = true;
    if (emailVerifyFeedback) emailVerifyFeedback.textContent = "Verificando...";
    try {
      const data = await postJson(cfg.urlMfaEmailConfirm, { code });
      showRecoveryOrReload(data.recovery_codes);
    } catch (error) {
      if (emailVerifyFeedback) emailVerifyFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    } finally {
      emailVerifyBtn.disabled = false;
    }
  });

  regenerateBtn?.addEventListener("click", async () => {
    // Cookie-thief hardening (PHASE_B Bloque A1): re-auth required so
    // a stolen session alone cannot mint a fresh set of recovery
    // codes — which would be a permanent MFA backdoor since the codes
    // don't expire. D-2: the confirmation prompt + password prompt +
    // error alert are now an inline password field + warning caption +
    // feedback line (no native prompt/confirm/alert dialogs).
    const currentPassword = String(regeneratePassword?.value || "").trim();
    if (!currentPassword) {
      if (regenerateFeedback) regenerateFeedback.textContent = "Confirma tu contrasena para regenerar.";
      regeneratePassword?.focus();
      return;
    }
    regenerateBtn.disabled = true;
    if (regenerateFeedback) regenerateFeedback.textContent = "Regenerando...";
    try {
      const data = await postJson(
        cfg.urlMfaRegenerate,
        { current_password: currentPassword },
      );
      if (regeneratePassword) regeneratePassword.value = "";
      if (regenerateFeedback) regenerateFeedback.textContent = "";
      // Reuse the enrollment path so the copy / download / print tools
      // get wired via setupRecoveryTools(). The old inline list-build
      // rendered the codes but never wired the buttons, leaving them
      // dead after a regenerate (pre-existing bug surfaced during D-2).
      showRecoveryOrReload(data.recovery_codes);
    } catch (error) {
      if (regenerateFeedback) regenerateFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
      regenerateBtn.disabled = false;
    }
  });

  // ---- Email change (double-opt-in) ----
  const emailForm = document.getElementById("profile-email-change-form");
  if (emailForm) {
    const newEmailInput = document.getElementById("profile-email-new");
    const passwordInput = document.getElementById("profile-email-password");
    const feedback = document.getElementById("profile-email-change-feedback");
    emailForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (feedback) feedback.textContent = "";
      try {
        const response = await fetch("/profile/email-change/", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfTokenInput,
          },
          credentials: "same-origin",
          body: JSON.stringify({
            new_email: (newEmailInput?.value || "").trim(),
            current_password: passwordInput?.value || "",
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          if (feedback) feedback.textContent = data.error || "No se pudo iniciar el cambio.";
          return;
        }
        if (feedback) {
          feedback.textContent = "Te mandamos un mail a " + data.new_email + ". Confirma desde el link.";
        }
        // Refresh so the form switches to the pending-state panel.
        setTimeout(() => window.location.reload(), 1500);
      } catch (err) {
        if (feedback) feedback.textContent = "Error de red al iniciar el cambio.";
      }
    });
  }

  // ``emailCancelBtn`` is already taken further up by the MFA-email
  // disable handler; use a different name here so both can coexist.
  const emailChangeCancelBtn = document.getElementById("profile-email-cancel");
  if (emailChangeCancelBtn) {
    const feedback = document.getElementById("profile-email-cancel-feedback");
    emailChangeCancelBtn.addEventListener("click", async () => {
      if (!confirm("Cancelar el cambio pendiente?")) return;
      emailChangeCancelBtn.disabled = true;
      try {
        const response = await fetch("/profile/email-change/cancel-pending/", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfTokenInput },
          credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          if (feedback) feedback.textContent = data.error || "No se pudo cancelar.";
          emailChangeCancelBtn.disabled = false;
          return;
        }
        if (feedback) feedback.textContent = "Cancelado. Refrescando...";
        setTimeout(() => window.location.reload(), 800);
      } catch (err) {
        if (feedback) feedback.textContent = "Error de red al cancelar.";
        emailChangeCancelBtn.disabled = false;
      }
    });
  }

});
