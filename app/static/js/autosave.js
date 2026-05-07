/* Tiny form auto-save to localStorage.
 *
 * Usage: <form class="autosave" data-autosave-key="estimate-form-new">
 *
 * On every input change:
 *   - serialize all named fields with values to localStorage under the key
 *
 * On page load:
 *   - if localStorage has data and the form is empty (no server-side data),
 *     restore the saved values + show a small "Restored from your last
 *     unsaved draft" indicator with an "Undo" link
 *
 * On successful submit:
 *   - clear the saved data so navigating back to the form gives a clean slate
 *
 * Limitations:
 *   - localStorage is per-browser-per-device (laptop drafts won't sync to phone)
 *   - capped at ~5MB total per origin; line items + notes won't realistically
 *     come close
 *   - skips file inputs (can't be serialized) and CSRF tokens (different per
 *     session — restoring stale ones would 400)
 */
(function () {
  "use strict";

  const SKIP_NAMES = new Set(["csrf_token", "next"]);
  const SKIP_TYPES = new Set(["file", "submit", "button", "hidden"]);
  // We DO want to keep hidden fields with semantic value (e.g. status filter
  // on search forms) — but auto-save is opt-in via class="autosave", and
  // those forms are typically the ones we want full restore on. Override
  // SKIP_TYPES for fields that have a non-empty name/value pair? Keep it
  // simple: skip hidden by default. Operator can re-toggle their selection.

  function fieldsOf(form) {
    const out = [];
    for (const el of form.elements) {
      if (!el.name || SKIP_NAMES.has(el.name)) continue;
      if (SKIP_TYPES.has(el.type)) continue;
      out.push(el);
    }
    return out;
  }

  function serialize(form) {
    const data = {};
    for (const el of fieldsOf(form)) {
      // Multiple inputs with same name (e.g. li_description[]) → array
      if (el.name.endsWith("[]")) {
        data[el.name] = data[el.name] || [];
        if (el.type === "checkbox") {
          if (el.checked) data[el.name].push(el.value);
        } else {
          data[el.name].push(el.value);
        }
      } else if (el.type === "checkbox") {
        data[el.name] = el.checked;
      } else if (el.type === "radio") {
        if (el.checked) data[el.name] = el.value;
      } else {
        data[el.name] = el.value;
      }
    }
    return data;
  }

  function restore(form, data) {
    const arrayCounters = {};
    for (const el of fieldsOf(form)) {
      const v = data[el.name];
      if (v === undefined) continue;
      if (el.name.endsWith("[]")) {
        const i = arrayCounters[el.name] || 0;
        if (Array.isArray(v) && i < v.length) {
          if (el.type === "checkbox") {
            el.checked = v.includes(el.value);
          } else {
            el.value = v[i];
          }
        }
        arrayCounters[el.name] = i + 1;
      } else if (el.type === "checkbox") {
        el.checked = !!v;
      } else if (el.type === "radio") {
        el.checked = (el.value === v);
      } else {
        el.value = v;
      }
    }
  }

  function isFormEffectivelyEmpty(form) {
    // Heuristic: form is "empty" if all main user-visible text/select fields
    // are blank or default. We check the first 5 named non-hidden inputs.
    let checked = 0;
    for (const el of fieldsOf(form)) {
      if (checked >= 5) break;
      if (el.value && el.value.trim() !== "" && el.value !== "0") return false;
      checked++;
    }
    return true;
  }

  function showStatus(form, msg) {
    const slot = form.querySelector(".autosave-status");
    if (slot) slot.textContent = msg;
  }

  function attach(form) {
    const key = "lo-autosave:" + form.dataset.autosaveKey;
    if (!form.dataset.autosaveKey) return;

    // Try to restore on load
    try {
      const raw = localStorage.getItem(key);
      if (raw && isFormEffectivelyEmpty(form)) {
        const data = JSON.parse(raw);
        restore(form, data);
        showStatus(form, "Restored your last unsaved draft.");
      }
    } catch (e) {
      // Stale/corrupt data — drop it.
      try { localStorage.removeItem(key); } catch (_) { /* noop */ }
    }

    // Save on input changes (debounced)
    let t;
    const save = function () {
      clearTimeout(t);
      t = setTimeout(function () {
        try {
          localStorage.setItem(key, JSON.stringify(serialize(form)));
          showStatus(form, "Saved draft locally.");
        } catch (e) {
          showStatus(form, "");
        }
      }, 400);
    };
    form.addEventListener("input", save);
    form.addEventListener("change", save);

    // Clear on real submit (the form is being saved server-side)
    form.addEventListener("submit", function () {
      try { localStorage.removeItem(key); } catch (_) { /* noop */ }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form.autosave").forEach(attach);
  });
})();
