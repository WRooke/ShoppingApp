/* Settings — index + drill-down sub-pages (Phase 6 Chunk 6.4, kickoff decisions #9/#10).
   Used to be one long scroll through 7 cards; `#/settings` is now a menu, and each section
   (including the new Appearance one) lives at its own `#/settings/<section>` route —
   router.js's existing key/param hash shape already supports this, no router changes needed
   beyond passing the param through. Each section's own renderCard() lives in its own file
   (settings-appearance.js, settings-staples.js, settings-product-units.js,
   settings-substitutions.js, settings-usuals.js, settings-ingredient-aliases.js,
   settings-unit-synonyms.js, settings-coarse-ingredients.js) — this file is just the index
   and the dispatch between them, split out once the combined file passed the ~400 line
   guideline. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  var SECTIONS = [
    { slug: "staples", name: "Staples", count: function () { return api.settings.staples.list(); } },
    { slug: "product-units", name: "Product units", count: function () { return api.settings.productUnits.list(); } },
    { slug: "substitutions", name: "Substitutions", count: function () { return api.settings.substitutions.list(); } },
    { slug: "usuals", name: "The usuals", count: function () { return api.settings.usuals.list(); } },
    { slug: "ingredient-aliases", name: "Ingredient groups", count: function () { return api.settings.ingredientAliases.list(); } },
    { slug: "unit-synonyms", name: "Unit spellings", count: function () { return api.settings.unitSynonyms.list(); } },
    { slug: "coarse-ingredients", name: "Coarse ingredients", count: function () { return api.settings.coarseIngredients.list(); } },
  ];

  function renderIndex(root) {
    root.innerHTML = "";
    root.appendChild(el("h3", null, "Settings"));

    var card = el("div", "card");
    card.style.padding = "0";
    var list = el("div", "section-list");
    card.appendChild(list);
    root.appendChild(card);

    function row(name, countText, href) {
      var a = el("a", null);
      a.href = href;
      a.appendChild(el("span", "name", name));
      a.appendChild(el("span", "count muted", countText));
      list.appendChild(a);
      return a;
    }

    row("Appearance", global.SettingsAppearanceView.label(), "#/settings/appearance");

    SECTIONS.forEach(function (s) {
      var a = row(s.name, "…", "#/settings/" + s.slug);
      var countEl = a.querySelector(".count");
      s.count()
        .then(function (data) {
          var n = data.total != null ? data.total : (data.items || []).length;
          countEl.textContent = n;
        })
        .catch(function () {
          countEl.textContent = "";
        });
    });
  }

  // Appearance/staples/product-units clear root and add the Back link themselves; the other
  // four sections' renderCard() only append a card (unchanged from their pre-6.4 shape), so
  // this dispatch does that wrapping for them.
  function withBack(renderFn) {
    return function (root) {
      root.innerHTML = "";
      root.appendChild(global.BackLink.render("settings"));
      renderFn(root);
    };
  }

  var SECTION_MOUNTS = {
    appearance: global.SettingsAppearanceView.renderCard,
    staples: global.SettingsStaplesView.renderCard,
    "product-units": global.SettingsProductUnitsView.renderCard,
    substitutions: withBack(global.SettingsSubstitutionsView.renderCard),
    usuals: withBack(global.SettingsUsualsView.renderCard),
    "ingredient-aliases": withBack(global.SettingsIngredientAliasesView.renderCard),
    "unit-synonyms": withBack(global.SettingsUnitSynonymsView.renderCard),
    "coarse-ingredients": withBack(global.SettingsCoarseIngredientsView.renderCard),
  };

  function mount(root, param) {
    var fn = param && SECTION_MOUNTS[param];
    if (fn) fn(root);
    else renderIndex(root);
  }

  function unmount() {
    // Nothing to tear down yet — no timers/intervals in this view.
  }

  global.SettingsView = { mount: mount, unmount: unmount };
})(window);
