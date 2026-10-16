/* Home screen — Phase 6 Chunk 6.1 (see docs/ui-ux.md > UI / UX and
   docs/build-status/phase-6-polish.md Phase 6 decision: Home shows quick actions only). Replaces the Phase 1 stub.

   Quick actions only, per the maintainer's explicit call — no recent/past-sessions list (that's
   Chunk 6.6 (mark cooked, history and archive)'s history view instead). The one thing Home does surface: a "Continue: <label>"
   button per session currently `status='active'` — a session mid-edit is the thing you're most
   likely to want the instant the app opens, which is a different question from "what did I do
   before" (history). The common case is exactly one active session; more than one is handled
   (each gets its own button) rather than assumed away. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function sessionLabel(s) {
    // planning_sessions.label is nullable (docs/data-model.md) — a blank "Continue: " button
    // would look broken, not just plain.
    return s.label || "Plan started " + new Date(s.created_at).toLocaleDateString();
  }

  function renderSkeleton(root) {
    var block = el("div");
    for (var i = 0; i < 2; i++) {
      var row = el("div", "skel-row");
      row.style.marginBottom = "12px";
      var line = el("div", "skeleton skel-line");
      line.style.width = "100%";
      line.style.height = "60px";
      line.style.borderRadius = "var(--r-md)";
      row.appendChild(line);
      block.appendChild(row);
    }
    root.appendChild(block);
  }

  function renderActions(root) {
    var actions = el("div", "home-actions");

    var newSession = el("a", "btn primary btn-block", "New plan");
    newSession.href = "#/plan/new";
    actions.appendChild(newSession);

    var newRecipe = el("a", "btn btn-block", "Recipes");
    newRecipe.href = "#/recipes";
    actions.appendChild(newRecipe);

    root.appendChild(actions);
  }

  function renderContinueCards(root, sessions) {
    sessions.forEach(function (s) {
      var card = el("a", "continue-card");
      card.href = "#/plan/" + encodeURIComponent(s.id);
      card.appendChild(el("span", "k", "Continue"));
      card.appendChild(el("span", "v", sessionLabel(s)));
      root.appendChild(card);
    });
  }

  function mount(root) {
    root.innerHTML = "";
    var wrap = el("div");
    wrap.appendChild(el("h3", null, "Home"));
    root.appendChild(wrap);

    renderSkeleton(wrap);

    global.api.sessions
      .list({ status: "active" })
      .then(function (res) {
        // api.js's request() already unwraps the {ok, data} envelope (returns body.data) —
        // res here IS the data payload, not a second .data to dig through.
        var items = (res && res.items) || [];
        wrap.innerHTML = "";
        wrap.appendChild(el("h3", null, "Home"));
        renderContinueCards(wrap, items);
        renderActions(wrap);
      })
      .catch(function (e) {
        if (global.ErrorReport) global.ErrorReport.reportCaught("home", e);
        // A failed lookup shouldn't block the two actions that always work — degrade to just
        // those rather than an error screen for what's meant to be the app's landing page.
        wrap.innerHTML = "";
        wrap.appendChild(el("h3", null, "Home"));
        renderActions(wrap);
      });
  }

  global.HomeView = { mount: mount };
})(window);
