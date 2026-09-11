/* Settings — "Unit spellings" card (2026-09-12). Unit-spelling canonicalisation — e.g.
   "gram"/"grams" and "kgs" both folded into "g"/"kg" on the shopping list. See CLAUDE.md >
   Ingredient Unit Handling > Layer A.

   Distinct from "Ingredient groups" (settings-ingredient-aliases.js) even though the two
   cards look similar — that resolves two *ingredient names* being the same shopping item;
   this resolves a *unit* being spelled two ways. Plain plurals (clove/cloves) don't need a
   row here at all — services/unit_synonyms.py's strip_plural() handles those generically;
   this card is only for genuine word-form differences (gram vs g, tablespoon vs tbsp). */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function groupByCanonical(items) {
    var groups = {};
    var order = [];
    (items || []).forEach(function (row) {
      if (!groups[row.canonical_unit]) {
        groups[row.canonical_unit] = [];
        order.push(row.canonical_unit);
      }
      groups[row.canonical_unit].push(row);
    });
    return order.map(function (unit) {
      return { canonical_unit: unit, rows: groups[unit] };
    });
  }

  function renderSynonymRow(row, onChanged) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.alias_unit));

    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Stop treating "' + row.alias_unit + '" as "' + row.canonical_unit + '"?')) {
        return;
      }
      api.settings.unitSynonyms
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(deleteBtn);
    wrap.appendChild(rowErr);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var aliasInput = el("input");
    aliasInput.type = "text";
    aliasInput.placeholder = "unit as typed, e.g. tablespoon";
    aliasInput.className = "settings-name-input";

    var canonicalInput = el("input");
    canonicalInput.type = "text";
    canonicalInput.placeholder = "same unit as, e.g. tbsp";
    canonicalInput.className = "settings-name-input";

    var addBtn = el("button", "primary", "Treat as the same unit");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var alias = aliasInput.value.trim();
      var canonical = canonicalInput.value.trim();
      if (!alias || !canonical) {
        rowErr.textContent = "Both units are required.";
        return;
      }
      api.settings.unitSynonyms
        .create({ alias_unit: alias, canonical_unit: canonical })
        .then(function () {
          aliasInput.value = "";
          canonicalInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [aliasInput, el("span", "muted", "="), canonicalInput, addBtn, rowErr].forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Unit spellings"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Units that are the same measurement, just spelled differently — e.g. “tablespoon” " +
          "and “tbsp”, or “kgs” and “kg”. Plain plurals like “clove”/“cloves” are already " +
          "handled automatically and don't need adding here. Applies to every existing " +
          "recipe immediately, and never changes a recipe's own stored data."
      )
    );

    var listBody = el("div", "settings-list");
    listBody.textContent = "Loading...";
    card.appendChild(listBody);
    var addSlot = el("div");
    card.appendChild(addSlot);
    root.appendChild(card);

    function load() {
      listBody.textContent = "Loading...";
      api.settings.unitSynonyms
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByCanonical(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "muted", "No custom spellings yet — add one below."));
          } else {
            groups.forEach(function (group) {
              listBody.appendChild(el("div", "sub-group-heading", group.canonical_unit));
              group.rows.forEach(function (row) {
                listBody.appendChild(renderSynonymRow(row, load));
              });
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load unit spellings: " + err.message;
        });
    }

    load();
  }

  global.SettingsUnitSynonymsView = { renderCard: renderCard };
})(window);
