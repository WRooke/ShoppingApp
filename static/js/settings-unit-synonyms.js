/* Settings — "Unit spellings" card (2026-09-12). Unit-spelling canonicalisation — e.g.
   "gram"/"grams" and "kgs" both folded into "g"/"kg" on the shopping list. See CLAUDE.md >
   Ingredient Unit Handling > Layer A.

   Distinct from "Ingredient groups" (settings-ingredient-aliases.js) even though the two
   cards look similar — that resolves two *ingredient names* being the same shopping item;
   this resolves a *unit* being spelled two ways. Plain plurals (clove/cloves) don't need a
   row here at all — services/unit_synonyms.py's strip_plural() handles those generically;
   this card is only for genuine word-form differences (gram vs g, tablespoon vs tbsp).

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM removal on delete instead of a full list
   rebuild (the scroll-position bug) — see settings-substitutions.js's header comment for
   why Add still rebuilds the whole list (same reasoning applies here). This card's rows
   have no editable fields besides delete (a unit spelling is either right or it's deleted
   and re-added correctly) — no Save button needed. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function miniField(labelText, inputEl) {
    var wrap = el("div", "mini-field");
    wrap.appendChild(el("label", null, labelText));
    wrap.appendChild(inputEl);
    return wrap;
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

  function renderSynonymRow(row, reload) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.alias_unit));

    var deleteBtn = el("button", "btn-sm", "Delete");
    var rowErr = el("span", "form-error");

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.alias_unit + " → " + row.canonical_unit,
      row: wrap,
      doDelete: function () {
        return api.settings.unitSynonyms.delete(row.id);
      },
      recreate: function () {
        return api.settings.unitSynonyms.create({
          alias_unit: row.alias_unit,
          canonical_unit: row.canonical_unit,
        });
      },
      onRestored: function () {
        reload(); // see settings-substitutions.js's header comment — same reasoning
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    wrap.appendChild(deleteBtn);
    wrap.appendChild(rowErr);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var aliasInput = el("input");
    aliasInput.type = "text";
    aliasInput.placeholder = "e.g. tablespoon";
    aliasInput.className = "settings-name-input";

    var canonicalInput = el("input");
    canonicalInput.type = "text";
    canonicalInput.placeholder = "e.g. tbsp";
    canonicalInput.className = "settings-name-input";

    var addBtn = el("button", "btn-sm primary", "Treat as the same unit");
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
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(miniField("Unit as typed", aliasInput));
    wrap.appendChild(el("span", "muted", "="));
    wrap.appendChild(miniField("Same unit as", canonicalInput));
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(addBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
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
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    listBody.appendChild(skel);
    card.appendChild(listBody);
    var addSlot = el("div");
    addSlot.style.marginTop = "12px";
    card.appendChild(addSlot);
    root.appendChild(card);

    function load() {
      api.settings.unitSynonyms
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByCanonical(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "empty-state", "No custom spellings yet — add one below."));
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
          listBody.innerHTML = "";
          listBody.appendChild(el("div", "error-state", "Couldn't load unit spellings: " + err.message));
        });
    }

    load();
  }

  global.SettingsUnitSynonymsView = { renderCard: renderCard };
})(window);
