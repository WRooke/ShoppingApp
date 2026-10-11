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
    wrap.appendChild(el("span", "muted", row.alias_unit + " → " + row.canonical_unit));

    var deleteBtn = el("button", "btn-sm", "Remove");
    var rowErr = el("span", "form-error");

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.alias_unit + " → " + row.canonical_unit,
      consequence: "“" + row.alias_unit + "” is its own unit again.",
      row: wrap,
      onDeleted: function (container) {
        if (!container) return;
        global.SettingsRowActions.tidyAfterDelete(container, {
          listBody: container, rowSel: ".settings-row", emptyText: "No unit spellings added yet — add one below.",
        });
      },
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

    var addBtn = el("button", "btn-sm primary", "Save this spelling");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var alias = aliasInput.value.trim();
      var canonical = canonicalInput.value.trim();
      if (!alias || !canonical) {
        rowErr.textContent = "Fill in both units.";
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

    var preview = el("div", "pair-preview muted");
    function updatePreview() {
      var a = aliasInput.value.trim();
      var c = canonicalInput.value.trim();
      preview.textContent = a && c ? "“2 " + a + "” in a recipe will be counted as “2 " + c + "”." : "";
    }
    aliasInput.addEventListener("input", updatePreview);
    canonicalInput.addEventListener("input", updatePreview);

    wrap.appendChild(miniField("When a recipe says", aliasInput));
    wrap.appendChild(el("div", "pair-dir muted", "↓ count it as"));
    wrap.appendChild(miniField("Count it as", canonicalInput));
    wrap.appendChild(preview);
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
        "Whenever a recipe says the “When a recipe says” unit, your shopping list counts it as " +
          "the “Count it as” unit. Plain plurals (clove / cloves) are already handled. " +
          "Applies to every recipe, existing and new."
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
            listBody.appendChild(el("div", "empty-state", "No unit spellings added yet — add one below."));
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
