// AMELI admin panel behaviour — maintenance toggle, email-queue metrics
// widget, sudo grant/status, user CRUD + role/password/MFA actions.
// Extracted from the inline <script> in admin/panel.html (frontend-debt
// split). The CSRF token arrives via data-csrf-token on the
// #admin-js-config element; all endpoint paths are literal /admin/* URLs.
document.addEventListener("DOMContentLoaded", () => {
  const csrfToken = ((document.getElementById("admin-js-config") || {}).dataset || {}).csrfToken || "";

  // ---- Maintenance mode toggle ----
  const maintCard = document.getElementById("admin-maintenance-card");
  if (maintCard) {
    const stateBadge = maintCard.querySelector("[data-maintenance-state]");
    const messageInput = maintCard.querySelector("[data-maintenance-message]");
    const enableBtn = maintCard.querySelector("[data-maintenance-enable]");
    const disableBtn = maintCard.querySelector("[data-maintenance-disable]");
    const feedback = maintCard.querySelector("[data-maintenance-feedback]");
    const setState = (active) => {
      if (!stateBadge) return;
      stateBadge.textContent = active ? "ACTIVO" : "INACTIVO";
      stateBadge.classList.toggle("primary", !!active);
    };
    const post = async (action) => {
      feedback.textContent = "Procesando…";
      try {
        const res = await fetch("/admin/maintenance/", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "x-csrf-token": csrfToken,
          },
          body: JSON.stringify({
            action,
            message: messageInput ? messageInput.value : "",
            read_only: true,
          }),
        });
        let payload = {};
        try { payload = await res.json(); } catch (_) { /* non-json */ }
        if (res.status === 401 || payload.need_sudo) {
          feedback.textContent = "Requiere sudo. Tocá el boton 'Admin nativo Django' para iniciar sudo y reintenta.";
          return;
        }
        if (res.status === 403) {
          feedback.textContent = "Sin permisos. Cerra y vuelve a iniciar sesion como superadmin.";
          return;
        }
        if (!res.ok) {
          const detail = payload.error || ("HTTP " + res.status);
          throw new Error(detail);
        }
        setState(!!payload.state && payload.state.active);
        feedback.textContent = "Listo.";
      } catch (err) {
        feedback.textContent = "Error: " + err.message;
      }
    };
    enableBtn?.addEventListener("click", () => post("enable"));
    disableBtn?.addEventListener("click", () => post("disable"));
  }

  // ---- Email queue widget refresh ----
  // Polls /admin/metrics/email-queue every 30 s. Best-effort: a
  // failure leaves the previous numbers in place and updates the
  // "actualizando" label so the operator can see staleness.
  const eqCard = document.getElementById("admin-email-queue-card");
  if (eqCard) {
    const eqUrl = eqCard.dataset.refreshUrl;
    const eqUpdated = eqCard.querySelector("[data-email-queue-updated]");
    const setText = (sel, value) => {
      const el = eqCard.querySelector(sel);
      if (el) el.textContent = String(value);
    };
    const refresh = async () => {
      try {
        const response = await fetch(eqUrl, {
          credentials: "same-origin",
          headers: { "Accept": "application/json" },
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();
        const s = data.summary || {};
        setText("[data-eq-pending]", s.pending ?? 0);
        setText("[data-eq-sent]", s.sent_last_24h ?? 0);
        setText("[data-eq-failed]", s.failed_last_24h ?? 0);
        setText("[data-eq-expired]", s.expired_last_24h ?? 0);
        const oldest = s.oldest_pending_age_seconds;
        setText(
          "[data-eq-oldest]",
          oldest != null
            ? "Mas vieja pendiente: " + oldest + "s."
            : "Sin filas pendientes.",
        );
        const errs = Array.isArray(s.top_error_classes) ? s.top_error_classes : [];
        setText(
          "[data-eq-errors]",
          errs.length
            ? "Errores top: " + errs.map((e) => e.error_class + " (" + e.count + ")").join(", ") + "."
            : "",
        );
        if (eqUpdated) {
          const ts = new Date();
          eqUpdated.textContent = "Actualizado " + ts.toLocaleTimeString();
        }
      } catch (err) {
        if (eqUpdated) eqUpdated.textContent = "Sin conexion (reintenta en 30s)";
      }
    };
    refresh();
    setInterval(refresh, 30000);
  }

  // ---- Sudo prompt ----
  // ``requestJson`` retries once after a successful sudo grant. We keep
  // a single in-flight promise so concurrent calls share one prompt.
  let sudoInFlight = null;

  async function fetchSudoStatus() {
    try {
      const response = await fetch("/admin/sudo/status/", { credentials: "same-origin" });
      if (!response.ok) return null;
      return await response.json();
    } catch (err) {
      return null;
    }
  }

  function promptForSudo() {
    if (sudoInFlight) return sudoInFlight;
    const modal = document.getElementById("sudo-modal");
    const form = document.getElementById("sudo-form");
    const passwordInput = document.getElementById("sudo-password");
    const mfaInput = document.getElementById("sudo-mfa-code");
    const mfaRow = document.getElementById("sudo-mfa-row");
    const mfaHelp = document.getElementById("sudo-mfa-help");
    const emailActions = document.getElementById("sudo-email-actions");
    const emailBtn = document.getElementById("sudo-send-email");
    const emailFeedback = document.getElementById("sudo-email-feedback");
    const errorBox = document.getElementById("sudo-error");
    const submitBtn = document.getElementById("sudo-submit");

    modal.hidden = false;
    passwordInput.value = "";
    mfaInput.value = "";
    errorBox.textContent = "";
    mfaRow.hidden = true;
    emailActions.hidden = true;
    if (emailFeedback) emailFeedback.textContent = "";
    passwordInput.focus();

    // Pre-fetch the operator's enrolled MFA methods so the modal renders
    // the right help text and action buttons before the first submit.
    fetchSudoStatus().then((status) => {
      if (!status || !status.mfa || !status.mfa.enabled) return;
      mfaRow.hidden = false;
      const hints = [];
      if (status.mfa.totp) hints.push("app de autenticacion");
      if (status.mfa.email) hints.push("codigo enviado al email");
      hints.push("codigo de respaldo");
      mfaHelp.textContent = "Aceptamos: " + hints.join(", ") + ".";
      if (status.mfa.email) {
        emailActions.hidden = false;
        if (status.mfa.email_address && emailFeedback) {
          emailFeedback.textContent = "Se enviara a " + status.mfa.email_address;
        }
      }
    });

    sudoInFlight = new Promise((resolve, reject) => {
      const cleanup = () => {
        modal.hidden = true;
        form.removeEventListener("submit", onSubmit);
        modal.querySelectorAll("[data-modal-close]").forEach((b) =>
          b.removeEventListener("click", onCancel)
        );
        if (emailBtn) emailBtn.removeEventListener("click", onSendEmail);
        sudoInFlight = null;
      };
      const onSubmit = async (ev) => {
        ev.preventDefault();
        errorBox.textContent = "";
        submitBtn.disabled = true;
        try {
          const response = await fetch("/admin/sudo/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-csrf-token": csrfToken,
            },
            credentials: "same-origin",
            body: JSON.stringify({
              password: passwordInput.value,
              mfa_code: mfaInput.value,
            }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.ok) {
            const msg = (data.error || "No se pudo confirmar.").toString();
            errorBox.textContent = msg;
            if (msg.toLowerCase().includes("2fa")) {
              mfaRow.hidden = false;
              mfaInput.focus();
            }
            submitBtn.disabled = false;
            return;
          }
          cleanup();
          resolve(true);
        } catch (err) {
          errorBox.textContent = "Error de red al confirmar.";
          submitBtn.disabled = false;
        }
      };
      const onSendEmail = async () => {
        if (!emailBtn) return;
        emailBtn.disabled = true;
        if (emailFeedback) emailFeedback.textContent = "Enviando...";
        try {
          const response = await fetch("/admin/sudo/email-code/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-csrf-token": csrfToken,
            },
            credentials: "same-origin",
            body: "{}",
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.ok) {
            const msg = (data.error || "No se pudo enviar el codigo.").toString();
            if (emailFeedback) emailFeedback.textContent = msg;
            emailBtn.disabled = false;
            return;
          }
          if (emailFeedback) {
            emailFeedback.textContent = "Codigo enviado. Revisa tu email y pegalo arriba.";
          }
          mfaInput.focus();
        } catch (err) {
          if (emailFeedback) emailFeedback.textContent = "Error de red al enviar.";
          emailBtn.disabled = false;
        }
      };
      const onCancel = () => {
        cleanup();
        reject(new Error("sudo cancelado"));
      };
      form.addEventListener("submit", onSubmit);
      if (emailBtn) emailBtn.addEventListener("click", onSendEmail);
      modal.querySelectorAll("[data-modal-close]").forEach((b) =>
        b.addEventListener("click", onCancel)
      );
    });
    return sudoInFlight;
  }

  async function requestJson(url, options = {}, _retriedAfterSudo = false) {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        "x-csrf-token": csrfToken,
      },
    });
    let data = {};
    try { data = await response.json(); } catch {}
    // Sudo gate: if the server says we need sudo, prompt the operator
    // and retry the original request once. Cancelling the prompt
    // surfaces as a regular thrown error so the caller's catch handler
    // shows its usual feedback.
    if (response.status === 401 && data.need_sudo && !_retriedAfterSudo) {
      try {
        await promptForSudo();
      } catch (cancelled) {
        throw new Error("Accion cancelada. Hace falta confirmar tu identidad.");
      }
      return requestJson(url, options, true);
    }
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Operacion no completada.");
    }
    return data;
  }

  function bindPasswordForm(formId, feedbackId, url, buildPayload) {
    const form = document.getElementById(formId);
    const feedback = document.getElementById(feedbackId);
    if (!form || !feedback) return null;
    const experience = window.AmeliPassword?.setupForm(form) || null;

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (experience) {
        const state = experience.sync();
        if (!state.matches) {
          feedback.textContent = "Confirma la contrasena antes de guardar.";
          return;
        }
        if (state.strength.level === "weak") {
          feedback.textContent = "La contrasena aun es debil. Refuerzala antes de guardar.";
          return;
        }
      }
      feedback.textContent = "Guardando...";
      try {
        const payload = buildPayload(form, experience);
        await requestJson(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        });
        feedback.textContent = "Operacion completada. Recargando...";
        window.setTimeout(() => window.location.reload(), 400);
      } catch (error) {
        feedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
      }
    });
    return { form, feedback, experience };
  }

  bindPasswordForm("create-user-form", "create-user-feedback", "/admin/users", (form, experience) => {
    const data = Object.fromEntries(new FormData(form).entries());
    return {
      username: data.username,
      password: experience ? experience.getValue() : data.password,
      role: data.role,
      must_change_password: data.must_change_password === "on",
    };
  });

  bindPasswordForm("admin-password-form", "admin-password-feedback", "/admin/change-password", (form, experience) => {
    const data = Object.fromEntries(new FormData(form).entries());
    return {
      current_password: data.current_password,
      new_password: experience ? experience.getValue() : data.new_password,
    };
  });

  // Filters and pagination on the users panel are now server-side. The
  // toolbar form (data-filter-form) submits to the same view; the AJAX
  // helper in app.js intercepts it and swaps just the panel HTML.

  // ---- Modal infrastructure ----
  const openModals = new Set();

  function openModal(modalId, contextSetup) {
    const modal = document.getElementById(modalId);
    if (!modal) return null;
    if (typeof contextSetup === "function") contextSetup(modal);
    modal.hidden = false;
    document.body.classList.add("modal-open");
    openModals.add(modalId);
    return modal;
  }

  function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.hidden = true;
    openModals.delete(modalId);
    if (openModals.size === 0) document.body.classList.remove("modal-open");
  }

  document.querySelectorAll(".modal-backdrop").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal(modal.id);
    });
    modal.querySelectorAll("[data-modal-close]").forEach((button) => {
      button.addEventListener("click", () => closeModal(modal.id));
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openModals.size > 0) {
      const last = Array.from(openModals).pop();
      if (last) closeModal(last);
    }
  });

  // ---- Reset password modal ----
  const resetForm = document.getElementById("reset-password-form");
  const resetFeedback = document.getElementById("reset-password-feedback");
  const resetMustChange = document.getElementById("reset-must-change");
  const resetExperience = resetForm ? window.AmeliPassword?.setupForm(resetForm) : null;
  let resetTargetUsername = "";

  function openResetPasswordModal(username) {
    resetTargetUsername = username;
    openModal("reset-password-modal", (modal) => {
      modal.querySelectorAll("[data-modal-target]").forEach((node) => { node.textContent = `@${username}`; });
      if (resetForm) resetForm.reset();
      if (resetMustChange) resetMustChange.checked = true;
      if (resetFeedback) resetFeedback.textContent = "";
      resetExperience?.sync();
    });
  }

  resetForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!resetExperience || !resetTargetUsername) return;
    const state = resetExperience.sync();
    if (!state.matches) {
      resetFeedback.textContent = "Confirma la contrasena antes de guardar.";
      return;
    }
    if (state.strength.level === "weak") {
      resetFeedback.textContent = "La contrasena aun es debil. Refuerzala antes de guardar.";
      return;
    }
    resetFeedback.textContent = "Guardando...";
    try {
      await requestJson(`/admin/users/${encodeURIComponent(resetTargetUsername)}/reset-password`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          password: resetExperience.getValue(),
          must_change_password: Boolean(resetMustChange?.checked),
        }),
      });
      resetFeedback.textContent = "Contrasena actualizada. Recargando...";
      window.setTimeout(() => window.location.reload(), 400);
    } catch (error) {
      resetFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    }
  });

  // ---- Change role modal ----
  const changeRoleForm = document.getElementById("change-role-form");
  const changeRoleSelect = document.getElementById("change-role-select");
  const changeRoleFeedback = document.getElementById("change-role-feedback");
  let changeRoleTargetUsername = "";

  function openChangeRoleModal(username, currentRole) {
    changeRoleTargetUsername = username;
    openModal("change-role-modal", (modal) => {
      modal.querySelectorAll("[data-modal-target]").forEach((node) => { node.textContent = `@${username}`; });
      if (changeRoleSelect) changeRoleSelect.value = currentRole === "superadmin" ? "superadmin" : "public";
      if (changeRoleFeedback) changeRoleFeedback.textContent = "";
    });
  }

  changeRoleForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!changeRoleTargetUsername || !changeRoleSelect) return;
    const next = changeRoleSelect.value;
    if (changeRoleFeedback) changeRoleFeedback.textContent = "Guardando...";
    try {
      await requestJson(`/admin/users/${encodeURIComponent(changeRoleTargetUsername)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ role: next }),
      });
      if (changeRoleFeedback) changeRoleFeedback.textContent = "Rol actualizado. Recargando...";
      window.setTimeout(() => window.location.reload(), 400);
    } catch (error) {
      if (changeRoleFeedback) changeRoleFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    }
  });

  // ---- Delete user modal ----
  const deleteForm = document.getElementById("delete-user-form");
  const deleteConfirmInput = document.getElementById("delete-user-confirm");
  const deleteHint = document.getElementById("delete-user-hint");
  const deleteSubmit = document.getElementById("delete-user-submit");
  const deleteFeedback = document.getElementById("delete-user-feedback");
  let deleteTargetUsername = "";

  function syncDeleteConfirm() {
    if (!deleteConfirmInput || !deleteSubmit) return;
    const ok = deleteConfirmInput.value.trim() === deleteTargetUsername;
    deleteSubmit.disabled = !ok;
    if (!deleteHint) return;
    if (!deleteConfirmInput.value) {
      deleteHint.textContent = "La accion se habilita cuando coincide con el usuario objetivo.";
      deleteHint.classList.remove("warn-text", "ok-text");
    } else if (ok) {
      deleteHint.textContent = "Coincide. La eliminacion esta habilitada.";
      deleteHint.classList.remove("warn-text");
      deleteHint.classList.add("ok-text");
    } else {
      deleteHint.textContent = "El nombre no coincide aun.";
      deleteHint.classList.add("warn-text");
      deleteHint.classList.remove("ok-text");
    }
  }

  function openDeleteUserModal(username) {
    deleteTargetUsername = username;
    openModal("delete-user-modal", (modal) => {
      modal.querySelectorAll("[data-modal-target]").forEach((node) => { node.textContent = `@${username}`; });
      if (deleteForm) deleteForm.reset();
      if (deleteFeedback) deleteFeedback.textContent = "";
      syncDeleteConfirm();
    });
  }

  deleteConfirmInput?.addEventListener("input", syncDeleteConfirm);

  deleteForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!deleteTargetUsername) return;
    if (deleteConfirmInput?.value.trim() !== deleteTargetUsername) return;
    if (deleteFeedback) deleteFeedback.textContent = "Eliminando...";
    try {
      await requestJson(`/admin/users/${encodeURIComponent(deleteTargetUsername)}`, { method: "DELETE" });
      if (deleteFeedback) deleteFeedback.textContent = "Usuario eliminado. Recargando...";
      window.setTimeout(() => window.location.reload(), 400);
    } catch (error) {
      if (deleteFeedback) deleteFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
    }
  });

  // ---- Direct PATCH actions: enable/disable, force-change toggle ----
  async function patchUser(username, payload, button) {
    const originalDisabled = button.disabled;
    button.disabled = true;
    try {
      await requestJson(`/admin/users/${encodeURIComponent(username)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      window.location.reload();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Error inesperado.");
      button.disabled = originalDisabled;
    }
  }

  // Delegated from document so the handler survives AJAX swaps of the users
  // panel; the closest() filter scopes matches to the users list only.
  document.addEventListener("click", (event) => {
    const button = event.target.closest("#users-list [data-user-action]");
    if (!(button instanceof HTMLButtonElement)) return;
    const action = button.dataset.userAction;
    const username = button.dataset.username || "";
    if (!username || !action) return;
    switch (action) {
      case "reset-password":
        openResetPasswordModal(username);
        break;
      case "toggle-enabled":
        patchUser(username, { enabled: button.dataset.enabled !== "1" }, button);
        break;
      case "change-role":
        openChangeRoleModal(username, button.dataset.role || "public");
        break;
      case "toggle-force-change":
        patchUser(username, { must_change_password: button.dataset.mustChange !== "1" }, button);
        break;
      case "toggle-mfa-required":
        patchUser(username, { mfa_required: button.dataset.mfaRequired !== "1" }, button);
        break;
      case "disable-mfa":
        if (confirm(`Confirmas desactivar el 2FA de @${username}? Esto borra el secreto y todos los codigos de recuperacion. El usuario debera re-enrolarse desde su perfil.`)) {
          (async () => {
            button.disabled = true;
            try {
              await requestJson(`/admin/users/${encodeURIComponent(username)}/disable-mfa`, { method: "POST" });
              window.location.reload();
            } catch (error) {
              alert(error instanceof Error ? error.message : "Error inesperado.");
              button.disabled = false;
            }
          })();
        }
        break;
      case "unlock":
        if (confirm(`Desbloquear la cuenta de @${username}? Va a poder volver a intentar iniciar sesion.`)) {
          (async () => {
            button.disabled = true;
            try {
              await requestJson(`/admin/users/${encodeURIComponent(username)}/unlock`, { method: "POST" });
              window.location.reload();
            } catch (error) {
              alert(error instanceof Error ? error.message : "Error inesperado.");
              button.disabled = false;
            }
          })();
        }
        break;
      case "delete":
        openDeleteUserModal(username);
        break;
    }
  });

  // ---- Jump into the native /django-admin/ via the sudo gate ----
  const enterDjangoAdminBtn = document.getElementById("enter-django-admin-btn");
  if (enterDjangoAdminBtn) {
    enterDjangoAdminBtn.addEventListener("click", async () => {
      try {
        const data = await requestJson("/admin/django-admin/enter/", { method: "POST" });
        if (data && data.redirect) {
          window.location.href = data.redirect;
        }
      } catch (error) {
        // requestJson already opens the sudo modal on a 401; the cancel
        // path lands here. Surface the same wording as elsewhere.
        alert(error instanceof Error ? error.message : "Accion cancelada.");
      }
    });
  }

});
