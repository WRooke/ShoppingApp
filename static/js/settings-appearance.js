/* Settings — "Appearance" card (Phase 6 Chunk 6.4, kickoff decision #9). The Light/Dark/
   System toggle, built on Chunk 6.1's data-theme token mechanism (see tokens.css, and
   index.html's own pre-paint script that reads this same `localStorage["theme"]` key
   before first render). Split out of settings.js per CLAUDE.md > Code Architecture &
   Maintainability > file size discipline — settings.js was pushing well past 400 lines
   once the index + staples + product-units + this card all landed in one file. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // Exposed (not just used internally) — settings.js's index card reads this to show the
  // current choice ("Light"/"Dark"/"System") next to the Appearance row.
  function label() {
    var saved = null;
    try {
      saved = global.localStorage.getItem("theme");
    } catch (_) {}
    if (saved === "light") return "Light";
    if (saved === "dark") return "Dark";
    return "System";
  }

  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "light") root.setAttribute("data-theme", "light");
    else if (mode === "dark") root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");
    try {
      if (mode === "light" || mode === "dark") global.localStorage.setItem("theme", mode);
      else global.localStorage.removeItem("theme");
    } catch (_) {
      // localStorage can throw in a locked-down/private context — the toggle still works
      // for this page load, it just won't be remembered next time.
    }
  }

  function renderCard(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("settings"));
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Appearance"));
    card.appendChild(el("div", "muted", "Saved to this device — not shared between phones."));

    var current = label();
    var switchWrap = el("div", "theme-switch");
    switchWrap.setAttribute("role", "group");
    switchWrap.setAttribute("aria-label", "App theme");
    switchWrap.style.marginTop = "12px";
    [
      { mode: "light", label: "Light" },
      { mode: "system", label: "System" },
      { mode: "dark", label: "Dark" },
    ].forEach(function (opt) {
      var btn = el("button", null, opt.label);
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(opt.label === current));
      btn.addEventListener("click", function () {
        applyTheme(opt.mode);
        switchWrap.querySelectorAll("button").forEach(function (b) {
          b.setAttribute("aria-pressed", String(b === btn));
        });
      });
      switchWrap.appendChild(btn);
    });
    card.appendChild(switchWrap);
    root.appendChild(card);
  }

  global.SettingsAppearanceView = { renderCard: renderCard, label: label };
})(window);
