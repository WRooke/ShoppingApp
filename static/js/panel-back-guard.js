/* History-balanced panel-close guard (2026-09-30, chunk 7.6 — back-navigation feedback item).

   Problem this solves: a naive "push one synthetic history entry when a panel opens, pop it on
   Back" approach leaves that entry DANGLING whenever the panel closes any other way (tapping
   it closed again, tapping a link inside it, navigating elsewhere via the nav bar) — the stack
   then has one more entry than visible screen transitions, so the *next* Back press is
   silently absorbed by the stale entry (no visible change), and the press after that jumps
   further than expected. Flagged directly by the maintainer during chunk 7.1/7.6 review: "if I
   get redirected mistakenly to 'three screens ago' if I hit the back button again I'll lose
   it."

   Fix: exactly ONE function (`close()`) ever closes a panel, and it always keeps the stack
   balanced, however the close was triggered:
     - Pressing Back — hardware button, the browser's own back control, or an Android edge-
       swipe gesture — all fire the identical `popstate` event; the one listener below handles
       all three uniformly, no special-casing needed.
     - Tapping ANY link while a panel is open (the nav bar, a recipe-breakdown link inside the
       panel, anything else) — intercepted globally below, in the capturing phase, BEFORE the
       link's own default navigation runs. This is not optional: a plain hash-changing link
       click fires `hashchange` but never `popstate` (confirmed — only back/forward/`history.go`
       trigger `popstate`), so without this the popstate listener alone would never see a
       nav-bar click at all, and it would push a real entry on top of the still-open synthetic
       one every time.
     - Any other explicit close (collapsing the row again, switching to a different row) also
       goes through `close()`.
   Every path pops the synthetic entry via `history.back()` FIRST and only then runs whatever
   was meant to happen next (the real navigation, or nothing) — so the stack never grows by
   more than one entry regardless of how the panel gets closed.

   Only one panel can be "open" (in the back-guard sense) at a time — callers are expected to
   close any previously-open panel before opening a new one (checklist.js's row expansion is
   already select-exclusive across the whole screen, so this holds naturally). */

(function (global) {
  "use strict";

  var isOpen = false;
  var openCloseFn = null; // the caller's own "actually close" callback, set by open()
  var pendingCloseFn = null; // set only while close()'s own history.back() is in flight
  var pendingAfter = null;

  function open(onClose) {
    if (isOpen) return; // a caller should close() the previous panel first; defensive no-op
    isOpen = true;
    openCloseFn = onClose;
    history.pushState({ panelBackGuard: true }, "", location.hash);
  }

  // Call from any NON-popstate close trigger. Pops the synthetic entry via history.back()
  // first; `after` (optional) runs once that pop's own popstate has actually been observed —
  // e.g. to perform a real navigation only once the entry is gone, keeping the stack balanced
  // at every point in between, not just at the start and end.
  function close(after) {
    if (!isOpen) {
      if (after) after();
      return;
    }
    pendingCloseFn = openCloseFn;
    pendingAfter = after || null;
    isOpen = false;
    openCloseFn = null;
    history.back();
  }

  window.addEventListener("popstate", function () {
    if (pendingCloseFn) {
      // This popstate is the one close() itself just triggered via history.back() above —
      // run the queued state-cleanup, then whatever was meant to happen after (e.g. the real
      // navigation a link tap wanted), in that order.
      var cb = pendingCloseFn;
      var after = pendingAfter;
      pendingCloseFn = null;
      pendingAfter = null;
      cb();
      if (after) after();
      return;
    }
    if (isOpen) {
      // Nothing we triggered ourselves was pending -- this is a real Back press (button,
      // gesture, or the in-app Back link's own history.back() call, all indistinguishable at
      // this level) popping our synthetic entry directly. Close now.
      var cb2 = openCloseFn;
      isOpen = false;
      openCloseFn = null;
      cb2();
    }
  });

  // Global link interception, capturing phase (runs before the link's own default navigation,
  // and before any bubble-phase handler on the link itself) — see the module docstring for why
  // this can't just be the popstate listener above. Only internal hash links ("#/...") are
  // intercepted; anything else (an external URL, a mailto:, etc. — none exist in this app
  // today, but the check costs nothing) navigates normally.
  document.addEventListener(
    "click",
    function (ev) {
      if (!isOpen) return;
      var link = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
      if (!link) return;
      var href = link.getAttribute("href");
      if (!href || href.charAt(0) !== "#") return;
      ev.preventDefault();
      close(function () {
        location.hash = href;
      });
    },
    true
  );

  global.PanelBackGuard = { open: open, close: close };
})(window);
