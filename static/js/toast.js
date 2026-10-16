/* Shared toast / undo snackbar — Phase 6 Chunk 6.1 (see docs/ui-ux.md > UI / UX and
   docs/build-status/phase-6-polish.md Phase 6 decision: Undo toast on delete). Built once here as app-shell
   infrastructure; Chunks 6.2 (recipe and import screen design)/6.3/6.3b/6.4/6.6 call global.Toast.show() from their own delete
   flows — this file has no delete logic of its own, it only renders the message and, if given
   one, runs an "undo" callback.

   Deliberately simple: one toast visible at a time (a second call replaces the first, it does
   not queue), and it dies on navigation rather than persisting across a route change (the maintainer's own call, weighed against the extra state management a
   persist-across-navigation version would need). router.js's hashchange handler calls
   Toast.dismiss() so a stale toast never survives onto a screen it no longer describes. */

(function (global) {
  "use strict";

  var AUTO_DISMISS_MS = 5000;
  var ERROR_DISMISS_MS = 9000; // an error needs longer to read (and its Retry to be tapped)
  var root = null;
  var hideTimer = null;
  var currentToastEl = null;

  function ensureRoot() {
    if (root) return root;
    root = document.getElementById("toast-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "toast-root";
      document.body.appendChild(root);
    }
    return root;
  }

  function dismiss() {
    clearTimeout(hideTimer);
    hideTimer = null;
    if (currentToastEl) {
      currentToastEl.classList.remove("show");
      var el = currentToastEl;
      currentToastEl = null;
      // Let the fade-out transition finish before removing the node.
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 200);
    }
  }

  /* show(message, opts) — opts.actionLabel / opts.onAction for an "Undo"/"Retry"-style button;
     opts.tone === "error" for an error (danger colour, role=alert, stays a little longer).
     Undoing is the caller's job (re-POST the just-deleted data, etc.) — this component only
     renders the prompt and the button, per docs/code-architecture.md > Code Architecture ("a small, stable
     interface", same discipline as the external-integration clients). */
  function show(message, opts) {
    opts = opts || {};
    dismiss();

    var el = document.createElement("div");
    var isError = opts.tone === "error";
    el.className = isError ? "toast error" : "toast";
    // role=alert makes a screen reader announce an error immediately; status is the polite default.
    el.setAttribute("role", isError ? "alert" : "status");

    var text = document.createElement("span");
    text.textContent = message;
    el.appendChild(text);

    if (opts.actionLabel && typeof opts.onAction === "function") {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opts.actionLabel;
      btn.addEventListener("click", function () {
        opts.onAction();
        dismiss();
      });
      el.appendChild(btn);
    }

    ensureRoot().appendChild(el);
    currentToastEl = el;
    // Two rAFs so the initial (opacity: 0) state actually paints before the "show" transition
    // starts — a single one can still land in the same frame on some browsers.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (el === currentToastEl) el.classList.add("show");
      });
    });

    hideTimer = setTimeout(dismiss, isError ? ERROR_DISMISS_MS : AUTO_DISMISS_MS);
  }

  global.Toast = { show: show, dismiss: dismiss };
})(window);
