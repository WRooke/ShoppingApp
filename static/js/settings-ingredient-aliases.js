/* Settings — "Ingredient groups" card (2026-09-10). "Same shopping item" aliases — e.g.
   "canola oil" and "oil spray" both folded into "vegetable oil" on the shopping list, or
   "lemon juice"/"lemon zest" folded into "lemon" with a quantity/unit conversion.

   Deliberately NOT the same feature as "Saved ingredient swaps" (settings-substitutions.js)
   even though the two cards look superficially similar (both group rows and offer a
   free-text pair). A substitution is "I don't want to buy X, buy Y instead" — a genuinely
   different product, confirmed per recipe, never silent. An alias is "X and Y are the same
   thing to my household" — no swap, no confirmation, no per-recipe record; it's applied
   silently, uniformly, and immediately to every recipe (past and future) at shopping-list
   time. See CLAUDE.md > Ingredient Aliases.

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM removal on delete instead of a full list
   rebuild (the scroll-position bug) — see settings-substitutions.js's header comment for
   why Add still rebuilds the whole list (same reasoning applies here). */

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

  /* The optional "N unit ≈ M unit" equivalence pair (e.g. "3 tbsp ≈ 1 [blank]" for lemon
     juice -> lemon). Unlike settings-substitutions.js's pairFields(), the canonical-side
     unit is explicitly allowed to stay blank — the canonical target is very often a bare
     count ("1 lemon"), not a purchasable-product-with-a-unit like a substitution's substitute. */
  function pairFields(row) {
    row = row || {};
    function num(v) {
      var n = el("input");
      n.type = "number";
      n.step = "any";
      n.inputMode = "decimal";
      n.className = "ingredient-qty-input";
      n.value = v != null ? v : "";
      return n;
    }
    function txt(v) {
      var t = el("input");
      t.type = "text";
      t.className = "ingredient-unit-input";
      t.value = v || "";
      return t;
    }
    var aqty = num(row.alias_qty);
    var aunit = txt(row.alias_unit);
    var cqty = num(row.canonical_qty);
    var cunit = txt(row.canonical_unit);
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr 1fr 1fr";
    grid.appendChild(miniField("Alias amount", aqty));
    grid.appendChild(miniField("Alias unit", aunit));
    grid.appendChild(miniField("= Canonical amount", cqty));
    grid.appendChild(miniField("Canonical unit (blank = count)", cunit));
    return {
      grid: grid,
      values: function () {
        var aq = parseFloat(aqty.value);
        var cq = parseFloat(cqty.value);
        return {
          alias_qty: isNaN(aq) ? null : aq,
          alias_unit: aunit.value.trim() || null,
          canonical_qty: isNaN(cq) ? null : cq,
          canonical_unit: cunit.value.trim() || null,
        };
      },
    };
  }

  function groupByCanonical(items) {
    var groups = {};
    var order = [];
    (items || []).forEach(function (row) {
      if (!groups[row.canonical_name]) {
        groups[row.canonical_name] = [];
        order.push(row.canonical_name);
      }
      groups[row.canonical_name].push(row);
    });
    return order.map(function (name) {
      return { canonical_name: name, rows: groups[name] };
    });
  }

  function renderAliasRow(row, reload) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.alias_name));

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.value = row.note || "";
    noteInput.className = "settings-notes-input";

    var pair = pairFields(row);

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-sm", "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var payload = { note: noteInput.value.trim() || null };
      var p = pair.values();
      payload.alias_qty = p.alias_qty;
      payload.alias_unit = p.alias_unit;
      payload.canonical_qty = p.canonical_qty;
      payload.canonical_unit = p.canonical_unit;
      api.settings.ingredientAliases
        .update(row.id, payload)
        .then(function (updated) {
          row.note = updated.note;
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.alias_name,
      row: wrap,
      doDelete: function () {
        return api.settings.ingredientAliases.delete(row.id);
      },
      recreate: function () {
        return api.settings.ingredientAliases.create({
          alias_name: row.alias_name,
          canonical_name: row.canonical_name,
          note: row.note,
          alias_qty: row.alias_qty,
          alias_unit: row.alias_unit,
          canonical_qty: row.canonical_qty,
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

    wrap.appendChild(miniField("Note", noteInput));
    wrap.appendChild(pair.grid);
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var aliasInput = el("input");
    aliasInput.type = "text";
    aliasInput.placeholder = "e.g. lemon juice";
    aliasInput.className = "settings-name-input";

    var canonicalInput = el("input");
    canonicalInput.type = "text";
    canonicalInput.placeholder = "e.g. lemon";
    canonicalInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "optional";
    noteInput.className = "settings-notes-input";

    var pair = pairFields();
    var addBtn = el("button", "btn-sm primary", "Group these");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var alias = aliasInput.value.trim();
      var canonical = canonicalInput.value.trim();
      if (!alias || !canonical) {
        rowErr.textContent = "Both names are required.";
        return;
      }
      var p = pair.values();
      api.settings.ingredientAliases
        .create({
          alias_name: alias,
          canonical_name: canonical,
          note: noteInput.value.trim() || null,
          alias_qty: p.alias_qty,
          alias_unit: p.alias_unit,
          canonical_qty: p.canonical_qty,
          canonical_unit: p.canonical_unit,
        })
        .then(function () {
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(miniField("Ingredient name", aliasInput));
    wrap.appendChild(el("span", "muted", "="));
    wrap.appendChild(miniField("Same shopping item as", canonicalInput));
    wrap.appendChild(miniField("Note", noteInput));
    wrap.appendChild(pair.grid);
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(addBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Ingredient groups"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Ingredients that are the same thing to you, shown as one line on the shopping list " +
          "— e.g. “canola oil” and “oil spray” grouped under “vegetable oil”, or “lemon juice” " +
          "grouped under “lemon” with an optional amount conversion (leave the amount fields " +
          "blank for a plain rename). This never changes a recipe's own ingredient list, and " +
          "adding a group applies to every existing recipe immediately, not just future ones."
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
      api.settings.ingredientAliases
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByCanonical(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "empty-state", "No groups yet — add one below."));
          } else {
            groups.forEach(function (group) {
              listBody.appendChild(el("div", "sub-group-heading", group.canonical_name));
              group.rows.forEach(function (row) {
                listBody.appendChild(renderAliasRow(row, load));
              });
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.innerHTML = "";
          listBody.appendChild(el("div", "error-state", "Couldn't load ingredient groups: " + err.message));
        });
    }

    load();
  }

  global.SettingsIngredientAliasesView = { renderCard: renderCard };
})(window);
