/* Bottom-nav badge dots — Phase 6 Chunk 6.1 (see CLAUDE.md > UI / UX and
   docs/build-status/phase-6-polish.md kickoff decisions #3/#11). App-shell level, not tied to
   any one view — static/index.html's nav markup already carries the (hidden-by-default)
   `<span class="nav-dot" data-badge="...">` slots this file toggles.

   Wired here: "Plan" (a session is currently active/unpushed) and "Diagnostics" (a recent
   unresolved error exists) — both piggyback on data this chunk already needs or that already
   has a cheap endpoint. NOT wired here: "Recipes" (pending AI processing) — deciding "does any
   recipe have ai_tasks_pending" is a recipes-domain question, more naturally Chunk 6.2's own
   job when it's actually working in that screen; the markup slot exists (`data-badge="recipes"`)
   but stays hidden until that chunk populates it. Documented here rather than silently done, so
   it isn't mistaken for an oversight.

   Refreshed once on load and again on every hash change (cheap enough — two small GETs — not to
   need a poll timer; a push/archive/error happening while the app sits open in the background
   catches up next time the user actually navigates). */

(function (global) {
  "use strict";

  function setBadge(key, visible) {
    var el = document.querySelector('.nav-dot[data-badge="' + key + '"]');
    if (!el) return;
    if (visible) el.removeAttribute("hidden");
    else el.setAttribute("hidden", "");
  }

  function refreshPlanBadge() {
    if (!(global.api && global.api.sessions)) return;
    global.api.sessions
      .list({ status: "active" })
      .then(function (res) {
        var items = (res && res.data && res.data.items) || [];
        setBadge("plan", items.length > 0);
      })
      .catch(function () {
        // Diagnostics-adjacent, not load-bearing — a failed check just leaves the dot as it
        // was rather than surfacing its own error.
      });
  }

  function refreshDiagnosticsBadge() {
    if (!(global.api && global.api.diagnostics)) return;
    global.api.diagnostics
      .recentErrors()
      .then(function (res) {
        var entries = (res && res.data && res.data.entries) || [];
        setBadge("diagnostics", entries.length > 0);
      })
      .catch(function () {});
  }

  function refreshAll() {
    refreshPlanBadge();
    refreshDiagnosticsBadge();
  }

  global.addEventListener("hashchange", refreshAll);
  global.addEventListener("DOMContentLoaded", refreshAll);
  if (document.readyState !== "loading") refreshAll();

  // Exposed so Home (and, later, wherever a session/push/error state changes within the same
  // view without a hash change) can ask for an immediate re-check rather than waiting.
  global.NavBadges = { refresh: refreshAll };
})(window);
