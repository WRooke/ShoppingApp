/* Minimal hash router. Views are plain functions that fill #view.
   Only Diagnostics is functional in Phase 1; the rest are stubs. */

(function (global) {
  "use strict";

  var viewEl = document.getElementById("view");
  var titleEl = document.getElementById("view-title");
  var navItems = document.querySelectorAll("[data-nav]");
  var activeCleanup = null;

  function stub(name, note) {
    return {
      title: name,
      mount: function (root) {
        var d = document.createElement("div");
        d.className = "stub";
        d.textContent = note;
        root.innerHTML = "";
        root.appendChild(d);
      },
    };
  }

  var routes = {
    home: stub("Home", "Phase 1 foundation is running. Use the Diagnostics tab to check status and logs."),
    recipes: stub("Recipes", "Recipe library arrives in Phase 2."),
    plan: stub("Plan", "Planning sessions arrive in Phase 4."),
    settings: stub("Settings", "Staples and product units editing arrives in Phase 2."),
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

  function currentKey() {
    var hash = (global.location.hash || "#/home").replace(/^#\//, "");
    return routes[hash] ? hash : "home";
  }

  function render() {
    if (typeof activeCleanup === "function") {
      try {
        activeCleanup();
      } catch (_) {}
      activeCleanup = null;
    }

    var key = currentKey();
    var route = routes[key];

    titleEl.textContent = route.title;
    document.title = "ShoppingApp — " + route.title;

    navItems.forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-nav") === key);
    });

    route.mount(viewEl);
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
})(window);
