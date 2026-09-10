/* Settings — "Ingredient groups" card (2026-09-10). "Same shopping item" aliases — e.g.
   "canola oil" and "oil spray" both folded into "vegetable oil" on the shopping list, or
   "lemon juice"/"lemon zest" folded into "lemon" with a quantity/unit conversion.

   Deliberately NOT the same feature as "Saved ingredient swaps" (settings-substitutions.js)
   even though the two cards look superficially similar (both group rows and offer a
   free-text pair). A substitution is "I don't want to buy X, buy Y instead" — a genuinely
   different product, confirmed per recipe, never silent. An alias is "X and Y are the same
   thing to my household" — no swap, no confirmation, no per-recipe record; it's applied
   silently, uniformly, and immediately to every recipe (past and future) at shopping-list
   time. See CLAUDE.md > Ingredient Aliases. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  /* The optional "N unit ≈ M unit" equivalence pair (e.g. "3 tbsp ≈ 1 [blank]" for lemon
     juice -> lemon). Unlike settings-substitutions.js's pairInputs(), the canonical-side unit
     is explicitly allowed to stay blank — the canonical target is very often a bare count
     ("1 lemon"), not a purchasable-product-with-a-unit like a substitution's substitute. */
  function pairInputs(row) {
    row = row || {};
    function num(v) {
      var n = el("input");
      n.type = "number";
      n.step = "any";
      n.className = "ingredient-qty-input";
      n.value = v != null ? v : "";
      return n;
    }
    function txt(v, ph) {
      var t = el("input");
      t.type = "text";
      t.className = "ingredient-unit-input";
      t.placeholder = ph;
      t.value = v || "";
      return t;
    }
    var aqty = num(row.alias_qty);
    aqty.placeholder = "amt";
    var aunit = txt(row.alias_unit, "unit");
    var cqty = num(row.canonical_qty);
    cqty.placeholder = "amt";
    var cunit = txt(row.canonical_unit, "unit (blank = count)");
    return {
      nodes: [aqty, aunit, el("span", "muted", "≈"), cqty, cunit],
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

  function renderAliasRow(row, onChanged) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.alias_name));

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.value = row.note || "";
    noteInput.placeholder = "note (optional)";
    noteInput.className = "settings-notes-input";

    var pair = pairInputs(row);

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
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
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Stop grouping "' + row.alias_name + '" with "' + row.canonical_name + '"?')) {
        return;
      }
      api.settings.ingredientAliases
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [noteInput].concat(pair.nodes).concat([saveBtn, deleteBtn, rowErr]).forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var aliasInput = el("input");
    aliasInput.type = "text";
    aliasInput.placeholder = "ingredient name, e.g. lemon juice";
    aliasInput.className = "settings-name-input";

    var canonicalInput = el("input");
    canonicalInput.type = "text";
    canonicalInput.placeholder = "same shopping item as, e.g. lemon";
    canonicalInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "note (optional)";
    noteInput.className = "settings-notes-input";

    var pair = pairInputs();
    var addBtn = el("button", "primary", "Group these");
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
          aliasInput.value = "";
          canonicalInput.value = "";
          noteInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [aliasInput, el("span", "muted", "="), canonicalInput, noteInput]
      .concat(pair.nodes)
      .concat([addBtn, rowErr])
      .forEach(function (n) {
        wrap.appendChild(n);
      });
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
    listBody.textContent = "Loading...";
    card.appendChild(listBody);
    var addSlot = el("div");
    card.appendChild(addSlot);
    root.appendChild(card);

    function load() {
      listBody.textContent = "Loading...";
      api.settings.ingredientAliases
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByCanonical(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "muted", "No groups yet — add one below."));
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
          listBody.textContent = "Couldn't load ingredient groups: " + err.message;
        });
    }

    load();
  }

  global.SettingsIngredientAliasesView = { renderCard: renderCard };
})(window);
