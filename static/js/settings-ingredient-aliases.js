/* Settings — "Ingredient groups" card (2026-09-10). "Same shopping item" aliases — e.g.
   "canola oil" and "oil spray" both folded into "vegetable oil" on the shopping list, or
   "lemon juice"/"lemon zest" folded into "lemon" with a quantity/unit conversion.

   Deliberately NOT the same feature as "Saved ingredient swaps" (settings-substitutions.js)
   even though the two cards look superficially similar (both group rows and offer a
   free-text pair). A substitution is "I don't want to buy X, buy Y instead" — a genuinely
   different product, confirmed per recipe, never silent. An alias is "X and Y are the same
   thing to my household" — no swap, no confirmation, no per-recipe record; it's applied
   silently, uniformly, and immediately to every recipe (past and future) at shopping-list
   time. See docs/ingredient-handling.md > Ingredient Aliases.

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM removal on delete instead of a full list
   rebuild (the scroll-position bug) — see settings-substitutions.js's header comment for
   why Add still rebuilds the whole list (same reasoning applies here).

   2026-09-23 redesign (see docs/ui-ux.md > UI/UX, mockup-approved): the alias name is now a
   labelled, visibly-disabled field instead of a bare unexplained span, the 4-field
   equivalence pair sits under its own "Amount conversion" sub-heading so it reads as one
   concept, Delete is visually de-emphasised (a plain underlined text button) and separated
   from the primary Save action, each canonical group's heading shows a count, and the
   add-new form is visually set apart under its own "Add a new group" heading. Layout only —
   no change to the underlying add/edit/delete/reload flow. */

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
    if (!row.id) {
      // the add form shows an example; saved rows show their own values
      aqty.placeholder = "3";
      aunit.placeholder = "tbsp";
      cqty.placeholder = "1";
      cunit.placeholder = "whole";
    }
    // "N unit = M unit" as two labelled rows, so which side is the recipe's and which the
    // shopping list's is stated rather than implied by position (docs/ui-ux.md > Plain language
    // & no ambiguity). The fields stack on a phone, so the labels never say left/right.
    var box = el("div", "pair-box");
    box.appendChild(el("div", "settings-sub-head", "Change the amount too? (optional)"));
    var r1 = el("div", "pair-row");
    r1.appendChild(el("span", null, "When a recipe says"));
    r1.appendChild(aqty);
    r1.appendChild(aunit);
    var r2 = el("div", "pair-row");
    r2.appendChild(el("span", null, "count it as"));
    r2.appendChild(cqty);
    r2.appendChild(cunit);
    box.appendChild(r1);
    box.appendChild(r2);
    box.appendChild(
      el(
        "div",
        "muted",
        "Only used when the recipe measures it in exactly that unit. Otherwise only the name " +
          "changes. Leave all four blank to only rename. Leave the last unit blank for whole items."
      )
    );
    return {
      grid: box,
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
      // True when exactly one of the two amounts is filled: the server clears a half pair, so
      // say so before it silently does (docs/ui-ux.md rule 7).
      halfFilled: function () {
        return (parseFloat(aqty.value) > 0) !== (parseFloat(cqty.value) > 0);
      },
      inputs: [aqty, aunit, cqty, cunit],
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
    var wrap = el("div", "settings-group-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = row.alias_name;
    nameInput.disabled = true;
    nameInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.value = row.note || "";
    noteInput.className = "settings-notes-input";

    var pair = pairFields(row);

    var saveBtn = el("button", "btn-sm primary", "Save changes");
    var deleteBtn = el("button", "btn-link-danger", "Remove");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      if (pair.halfFilled()) {
        rowErr.textContent = "Fill in both amounts, or leave all four blank.";
        return;
      }
      var payload = { note: noteInput.value.trim() || null };
      var p = pair.values();
      payload.alias_qty = p.alias_qty;
      payload.alias_unit = p.alias_unit;
      payload.canonical_qty = p.canonical_qty;
      payload.canonical_unit = p.canonical_unit;
      api.settings.ingredientAliases
        .update(row.id, payload)
        .then(function (updated) {
          // Every field, not just the note: the server clears a half-filled pair, and the
          // Delete -> Undo payload below is built from this cached row.
          ["note", "alias_qty", "alias_unit", "canonical_qty", "canonical_unit"].forEach(function (k) {
            row[k] = updated[k];
          });
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.alias_name,
      consequence: "It shows as itself again.",
      row: wrap,
      onDeleted: function (container) {
        var list = container && container.closest ? container.closest(".settings-list") : null;
        if (!list) return;
        global.SettingsRowActions.tidyAfterDelete(container, {
          listBody: list, rowSel: ".settings-group-row", cardSel: ".settings-group-card",
          countSel: ".settings-group-count",
          countText: function (n) { return n + (n === 1 ? " name" : " names"); },
          emptyText: "No name groups yet — add one below.",
        });
      },
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

    // Where a group came from (Chunk 6.7, user-feedback batch, mockups: popups.html #9): a small tag for built-in groups
    // (migration-seeded, source "system") and for groups a checklist "merge every time" created
    // (source "merge"), so a learned merge can be told apart from one typed by hand (no tag).
    var nameLine = el("div");
    nameLine.style.cssText = "display:flex;gap:8px;align-items:center";
    nameInput.style.flex = "1";
    nameLine.appendChild(nameInput);
    var TAGS = { merge: ["merge", "Added from a checklist combine"], system: ["system", "Built in"] };
    if (TAGS[row.source]) nameLine.appendChild(el("span", "source-tag " + TAGS[row.source][0], TAGS[row.source][1]));
    wrap.appendChild(miniField("When a recipe says (fixed — remove and re-add to change)", nameLine));
    wrap.appendChild(miniField("Note (only shown here)", noteInput));
    wrap.appendChild(pair.grid);
    var actions = el("div", "settings-row-actions-line");
    actions.appendChild(deleteBtn);
    actions.appendChild(saveBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-add-card");
    wrap.appendChild(el("div", "settings-add-title", "Add one"));

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
    var addBtn = el("button", "btn-sm primary", "Save this name group");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var alias = aliasInput.value.trim();
      var canonical = canonicalInput.value.trim();
      if (!alias || !canonical) {
        rowErr.textContent = "Fill in what the recipe says and what the shopping list shows.";
        return;
      }
      if (pair.halfFilled()) {
        rowErr.textContent = "Fill in both amounts, or leave all four blank.";
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

    // A live sentence of exactly what will happen, so the direction can't be misread.
    var preview = el("div", "pair-preview muted");
    function updatePreview() {
      var a = aliasInput.value.trim();
      var c = canonicalInput.value.trim();
      if (!a || !c) {
        preview.textContent = "";
        return;
      }
      var p = pair.values();
      var txt = "“" + a + "” in a recipe will show as “" + c + "” on your shopping list.";
      if (p.alias_qty != null && p.canonical_qty != null) {
        txt +=
          " " + p.alias_qty + (p.alias_unit ? " " + p.alias_unit : "") + " " + a + " becomes " +
          p.canonical_qty + (p.canonical_unit ? " " + p.canonical_unit : "") + " " + c + ".";
      }
      preview.textContent = txt;
    }
    [aliasInput, canonicalInput].concat(pair.inputs).forEach(function (i) {
      i.addEventListener("input", updatePreview);
    });

    wrap.appendChild(miniField("When a recipe says", aliasInput));
    wrap.appendChild(el("div", "pair-dir muted", "↓ show it on my shopping list as"));
    wrap.appendChild(miniField("Shopping list shows", canonicalInput));
    wrap.appendChild(pair.grid);
    wrap.appendChild(preview);
    wrap.appendChild(miniField("Note (only shown here)", noteInput));
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(addBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Same item, different names"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Whenever a recipe says the “When a recipe says” name, your shopping list shows the " +
          "“Shopping list shows” name instead. Recipes themselves aren’t changed. Applies to " +
          "every recipe, existing and new."
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
            listBody.appendChild(el("div", "empty-state", "No name groups yet — add one below."));
          } else {
            groups.forEach(function (group) {
              var groupCard = el("div", "settings-group-card");
              var head = el("div", "settings-group-head");
              head.appendChild(el("span", "settings-group-name", "Shown as “" + group.canonical_name + "”"));
              var count = group.rows.length;
              head.appendChild(el("span", "settings-group-count", count + (count === 1 ? " name" : " names")));
              groupCard.appendChild(head);
              group.rows.forEach(function (row) {
                groupCard.appendChild(renderAliasRow(row, load));
              });
              listBody.appendChild(groupCard);
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.innerHTML = "";
          listBody.appendChild(el("div", "error-state", "Couldn't load the name groups: " + err.message));
        });
    }

    load();
  }

  global.SettingsIngredientAliasesView = { renderCard: renderCard };
})(window);
