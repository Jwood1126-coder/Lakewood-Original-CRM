/* Replace native window.confirm() in form onsubmit handlers with a styled
 * modal. Two ways to trigger the modal:
 *
 *   1. <form data-confirm="Are you sure?">  -- preferred, robust
 *      Attribute value is plain text, HTML-attribute-escaped. Works
 *      correctly even when the message contains apostrophes or quotes
 *      because we read it via .dataset (browser handles HTML decoding).
 *
 *   2. <form onsubmit="return confirm('Are you sure?')">  -- legacy
 *      We regex-match the attribute. Fragile with apostrophes inside the
 *      message; use data-confirm for any message containing user-supplied
 *      text (e.g. client names).
 *
 * Fail-safe: if this script doesn't load, the legacy onsubmit handlers
 * still fire native confirm(). data-confirm forms have no JS-off fallback
 * — use them only where a missed confirm is acceptable.
 */
(function () {
  "use strict";

  function buildModal() {
    const overlay = document.createElement("div");
    overlay.id = "lo-confirm-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "lo-confirm-msg");
    overlay.innerHTML = `
      <div class="lo-confirm-card">
        <p id="lo-confirm-msg"></p>
        <div class="lo-confirm-actions">
          <button type="button" class="secondary outline" data-lo-confirm="cancel">Cancel</button>
          <button type="button" class="contrast lo-confirm-go" data-lo-confirm="ok">Confirm</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    return overlay;
  }

  let overlay;
  let pendingForm = null;

  function openModal(message, dangerous) {
    overlay = overlay || buildModal();
    overlay.querySelector("#lo-confirm-msg").textContent = message;
    const okBtn = overlay.querySelector(".lo-confirm-go");
    okBtn.textContent = dangerous ? "Yes, do it" : "Confirm";
    okBtn.classList.toggle("lo-danger", !!dangerous);
    overlay.classList.add("open");
    setTimeout(() => okBtn.focus(), 0);
  }

  function closeModal() {
    if (overlay) overlay.classList.remove("open");
    pendingForm = null;
  }

  document.addEventListener("click", function (ev) {
    const t = ev.target.closest("[data-lo-confirm]");
    if (!t || !overlay || !overlay.classList.contains("open")) return;
    ev.preventDefault();
    if (t.dataset.loConfirm === "ok" && pendingForm) {
      const form = pendingForm;
      // Clear onsubmit so submit() doesn't re-trigger the native confirm.
      form.removeAttribute("onsubmit");
      closeModal();
      form.submit();
    } else {
      closeModal();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (!overlay || !overlay.classList.contains("open")) return;
    if (ev.key === "Escape") { closeModal(); }
  });

  // Capture phase so we run before the inline onsubmit attribute handler.
  document.addEventListener("submit", function (ev) {
    const form = ev.target;
    if (!(form instanceof HTMLFormElement)) return;
    let msg = form.dataset.confirm;
    if (!msg) {
      const onsub = form.getAttribute("onsubmit") || "";
      const m = onsub.match(/return\s+confirm\(\s*['"]([\s\S]*?)['"]\s*\)/);
      if (!m) return;
      msg = m[1].replace(/\\'/g, "'").replace(/\\"/g, '"');
    }
    ev.preventDefault();
    ev.stopImmediatePropagation();
    pendingForm = form;
    const dangerous = /delete|permanently|cancel|void|disconnect|remove/i.test(msg);
    openModal(msg, dangerous);
  }, true);
})();
