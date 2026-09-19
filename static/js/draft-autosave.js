/* Draft autosave — Phase 6 Chunk 6.2 (see docs/build-status/phase-6-polish.md kickoff
   decision #12). A `localStorage` draft of a form's recipe-level fields, surviving a
   killed/reloaded phone tab (common when backgrounding for a while mid-edit). Scoped to
   the top-level fields only (name, servings, cuisine, protein, source, notes) — the dynamic
   ingredient list is deliberately not drafted: restoring a variable-length list of rows
   correctly is a lot more machinery for comparatively little benefit next to the real pain
   point (losing a half-typed recipe name/notes), and every ingredient row already gets its
   own explicit Save/Add action with immediate feedback, unlike the top fields which only
   save once, at the very end. */

(function (global) {
  "use strict";

  function storageKey(formKey) {
    return "sa-draft:" + formKey;
  }

  // fields: { fieldName: <input|textarea|select> }. Returns { restore(), clear() } —
  // restore() returns true if anything was actually restored, so a caller can show a small
  // "draft restored" note only when it's true.
  function attach(formKey, fields) {
    var key = storageKey(formKey);
    var debounceTimer = null;

    function save() {
      var data = {};
      Object.keys(fields).forEach(function (name) {
        data[name] = fields[name].value;
      });
      try {
        global.localStorage.setItem(key, JSON.stringify(data));
      } catch (_) {
        // Private/locked-down browsing context, or storage full — a lost draft is a
        // nicety gone missing, not a broken save. Nothing else to do here.
      }
    }

    Object.keys(fields).forEach(function (name) {
      fields[name].addEventListener("input", function () {
        global.clearTimeout(debounceTimer);
        debounceTimer = global.setTimeout(save, 400);
      });
    });

    function restore() {
      var raw;
      try {
        raw = global.localStorage.getItem(key);
      } catch (_) {
        return false;
      }
      if (!raw) return false;
      var data;
      try {
        data = JSON.parse(raw);
      } catch (_) {
        return false;
      }
      var restoredAny = false;
      Object.keys(fields).forEach(function (name) {
        if (data[name]) {
          fields[name].value = data[name];
          restoredAny = true;
        }
      });
      return restoredAny;
    }

    function clear() {
      try {
        global.localStorage.removeItem(key);
      } catch (_) {}
    }

    return { restore: restore, clear: clear };
  }

  global.DraftAutosave = { attach: attach };
})(window);
