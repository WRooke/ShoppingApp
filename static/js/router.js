/* Minimal hash router. Views are plain functions that fill #view.
   Every route below is a real view as of Phase 6 Chunk 6.1 (Home was the last stub). */

(function (global) {
  "use strict";

  var viewEl = document.getElementById("view");
  var titleEl = document.getElementById("view-title");
  var navItems = document.querySelectorAll("[data-nav]");
  var activeCleanup = null;

  var routes = {
    home: {
      title: "Home",
      mount: function (root) {
        global.HomeView.mount(root);
      },
      unmount: function () {
        if (global.HomeView.unmount) global.HomeView.unmount();
      },
    },
    recipes: {
      title: "Recipes",
      mount: function (root, param) {
        global.RecipesView.mount(root, param);
      },
      unmount: function () {
        global.RecipesView.unmount();
      },
    },
    plan: {
      title: "Plan",
      mount: function (root, param) {
        global.SessionsView.mount(root, param);
      },
      unmount: function () {
        global.SessionsView.unmount();
      },
    },
    checklist: {
      title: "Checklist",
      mount: function (root, param) {
        global.ChecklistView.mount(root, param);
      },
      unmount: function () {
        if (global.ChecklistView.unmount) global.ChecklistView.unmount();
      },
    },
    settings: {
      title: "Settings",
      mount: function (root) {
        global.SettingsView.mount(root);
      },
      unmount: function () {
        global.SettingsView.unmount();
      },
    },
    diagnostics: {
      title: "Diagnostics",
      mount: function (root) {
        global.DiagnosticsView.mount(root);
      },
      unmount: function () {
        global.DiagnosticsView.unmount();
      },
    },
  };

  // Hash shapes supported: "#/<key>" and "#/<key>/<param>" (e.g. "#/recipes/42"
  // for the recipe detail view). Parsing the hash lives here and only here —
  // feature files receive an already-extracted param, never location.hash
  // itself (see CLAUDE.md > Code Architecture & Maintainability: "router.js is
  // the only file that knows hash routes exist").
  function parseHash() {
    var hash = (global.location.hash || "#/home").replace(/^#\//, "");
    var parts = hash.split("/").filter(Boolean);
    var key = routes[parts[0]] ? parts[0] : "home";
    return { key: key, param: parts[1] || null };
  }

  function render() {
    // A toast is scoped to the screen that raised it (kickoff decision #12) — never let one
    // survive onto whatever the user navigates to next.
    if (global.Toast) global.Toast.dismiss();

    if (typeof activeCleanup === "function") {
      try {
        activeCleanup();
      } catch (_) {}
      activeCleanup = null;
    }

    var parsed = parseHash();
    var route = routes[parsed.key];

    titleEl.textContent = route.title;
    document.title = "ShoppingApp — " + route.title;

    navItems.forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-nav") === parsed.key);
    });

    route.mount(viewEl, parsed.param);
    activeCleanup = route.unmount || null;
  }

  global.addEventListener("hashchange", render);
  global.addEventListener("DOMContentLoaded", function () {
    if (!global.location.hash) global.location.hash = "#/home";
    render();
  });

  // DOMContentLoaded may have already fired (scripts at end of body).
  if (document.readyState !== "loading") {
    if (!global.location.hash) global.location.hash = "#/home";
    render();
  }

  // Programmatic navigation (e.g. "saved, now go to the detail view") goes
  // through here rather than a feature file setting global.location.hash
  // directly — keeps the "#/<key>/<param>" shape known only to router.js
  // (see CLAUDE.md > Code Architecture & Maintainability). Plain <a href="#/...">
  // links in feature files are fine — only route-shape construction in JS
  // needs to live here.
  global.Router = {
    navigate: function (key, param) {
      global.location.hash = "#/" + key + (param != null ? "/" + param : "");
    },
  };
})(window);
