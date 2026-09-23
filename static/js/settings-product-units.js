/* Settings — "Product units" card (see CLAUDE.md > Build Phases > Phase 2 > Chunk 2.5, and
   > Phase 4 > product_units multi-pack-size note). Split out of settings.js per CLAUDE.md >
   Code Architecture & Maintainability > file size discipline.

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM updates instead of a full list rebuild on
   every Save/Add/Delete (the scroll-position bug).

   2026-09-23 redesign (see CLAUDE.md > UI/UX, mockup-approved): an ingredient with more than
   one pack size (e.g. eggs — half-dozen + dozen) used to render as two visually unrelated
   flat rows; now grouped under one card per ingredient, same "grouped card" treatment as
   settings-ingredient-aliases.js. The ingredient name moves to the group heading (a rename
   there renames every pack-size row in the group in one action — see `renameGroup()`); each
   pack-size sub-row keeps only what's actually per-pack: label, quantity, unit, notes.
   Same documented simplification as the other grouped-list Settings cards (Chunk 6.4's
   substitutions/aliases/unit-synonyms note): in-place delete, but Add and a group rename
   both trigger a full `load()` rebuild — a grouping recompute on every mutation would be
   more code than this card's real usage pattern (occasional edits, not rapid-fire) justifies. */

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

  function groupByIngredient(items) {
    var groups = {};
    var order = [];
    (items || []).forEach(function (row) {
      if (!groups[row.ingredient_name]) {
        groups[row.ingredient_name] = [];
        order.push(row.ingredient_name);
      }
      groups[row.ingredient_name].push(row);
    });
    return order.map(function (name) {
      return { ingredient_name: name, rows: groups[name] };
    });
  }

  /* Renames every row in a group in one action (Promise.all over each row's own PATCH) —
     the group heading is the household's one mental handle on "this ingredient", so a rename
     there should mean all of it, not just one pack size drifting out of sync with the rest. */
  function renameGroup(rows, newName, onDone, onError) {
    Promise.all(
      rows.map(function (row) {
        return api.settings.productUnits.update(row.id, { ingredient_name: newName });
      })
    )
      .then(onDone)
      .catch(onError);
  }

  function renderPackRow(unit, load) {
    var row = el("div", "settings-group-row");

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.value = unit.purchase_label;

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.inputMode = "decimal";
    qtyInput.value = unit.purchase_qty;
    qtyInput.className = "ingredient-qty-input";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.value = unit.purchase_unit || "";
    unitInput.className = "ingredient-unit-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = unit.notes || "";
    notesInput.className = "settings-notes-input";

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-link-danger", "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var qty = parseFloat(qtyInput.value);
      if (isNaN(qty) || qty <= 0) {
        rowErr.textContent = "Purchase quantity must be a positive number.";
        return;
      }
      api.settings.productUnits
        .update(unit.id, {
          purchase_label: labelInput.value.trim(),
          purchase_qty: qty,
          purchase_unit: unitInput.value.trim() || null,
          notes: notesInput.value.trim() || null,
        })
        .then(function (updated) {
          unit.purchase_label = updated.purchase_label;
          unit.purchase_qty = updated.purchase_qty;
          unit.purchase_unit = updated.purchase_unit;
          unit.notes = updated.notes;
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: unit.ingredient_name + " (" + unit.purchase_label + ")",
      row: row,
      doDelete: function () {
        return api.settings.productUnits.delete(unit.id);
      },
      recreate: function () {
        return api.settings.productUnits.create({
          ingredient_name: unit.ingredient_name,
          purchase_label: unit.purchase_label,
          purchase_qty: unit.purchase_qty,
          purchase_unit: unit.purchase_unit,
          notes: unit.notes,
        });
      },
      // Grouped-list card (same precedent as substitutions/aliases, Chunk 6.4): a restored
      // row may need its own group card rebuilt (e.g. the last pack size in a group was just
      // deleted, removing the whole card), so Undo triggers a full reload rather than trying
      // to re-insert into a group card that might no longer exist.
      onRestored: function () {
        load();
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    if (unit.is_preseeded) row.appendChild(el("span", "muted", "Seeded"));
    row.appendChild(miniField("Pack label", labelInput));
    var grid2 = el("div", "ing-grid");
    grid2.style.gridTemplateColumns = "1fr 1fr";
    grid2.appendChild(miniField("Pack quantity", qtyInput));
    grid2.appendChild(miniField("Unit", unitInput));
    row.appendChild(grid2);
    row.appendChild(miniField("Notes", notesInput));
    var actions = el("div", "settings-row-actions-line");
    actions.appendChild(deleteBtn);
    actions.appendChild(saveBtn);
    actions.appendChild(rowErr);
    row.appendChild(actions);
    return row;
  }

  function renderGroupCard(group, load) {
    var card = el("div", "settings-group-card");
    var head = el("div", "settings-group-head");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = group.ingredient_name;
    var headErr = el("span", "form-error");
    nameInput.addEventListener("change", function () {
      var newName = nameInput.value.trim();
      if (!newName || newName === group.ingredient_name) {
        nameInput.value = group.ingredient_name;
        return;
      }
      headErr.textContent = "";
      renameGroup(
        group.rows,
        newName,
        function () { load(); },
        function (err) {
          nameInput.value = group.ingredient_name;
          headErr.textContent = err.message;
        }
      );
    });
    head.appendChild(el("span", "settings-group-name")).appendChild(nameInput);

    var count = group.rows.length;
    var countText = count + (count === 1 ? " pack size" : " pack sizes");
    if (group.rows.some(function (r) { return r.is_preseeded; })) countText += " · Seeded";
    head.appendChild(el("span", "settings-group-count", countText));

    card.appendChild(head);
    card.appendChild(headErr);
    group.rows.forEach(function (unit) {
      card.appendChild(renderPackRow(unit, load));
    });
    return card;
  }

  function renderCard(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("settings"));
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Product units"));
    card.appendChild(
      el(
        "div",
        "muted",
        "How each ingredient is actually bought, e.g. eggs as a dozen. Used to turn a scaled quantity into a shopping-list amount. An ingredient with more than one pack size groups into one card."
      )
    );

    var listBody = el("div", "settings-list");
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    listBody.appendChild(skel);
    card.appendChild(listBody);

    var addCard = el("div", "settings-add-card");
    addCard.appendChild(el("div", "settings-add-title", "Add a pack size"));

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. beef mince";
    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "e.g. 500g pack";
    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.inputMode = "decimal";
    qtyInput.placeholder = "e.g. 500";
    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "e.g. g";
    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "optional";
    var addBtn = el("button", "btn-sm primary", "Add");
    var addErr = el("span", "form-error");

    addCard.appendChild(miniField("Ingredient", nameInput));
    addCard.appendChild(miniField("Pack label", labelInput));
    var addGrid2 = el("div", "ing-grid");
    addGrid2.style.gridTemplateColumns = "1fr 1fr";
    addGrid2.appendChild(miniField("Pack quantity", qtyInput));
    addGrid2.appendChild(miniField("Unit", unitInput));
    addCard.appendChild(addGrid2);
    addCard.appendChild(miniField("Notes", notesInput));
    var addActions = el("div", "settings-row-actions-line");
    addActions.style.justifyContent = "flex-start";
    addActions.appendChild(addBtn);
    addActions.appendChild(addErr);
    addCard.appendChild(addActions);
    card.appendChild(addCard);
    root.appendChild(card);

    function load() {
      api.settings.productUnits
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          var groups = groupByIngredient(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "empty-state", "No product units yet."));
          } else {
            groups.forEach(function (group) {
              listBody.appendChild(renderGroupCard(group, load));
            });
          }
        })
        .catch(function (err) {
          listBody.innerHTML = "";
          listBody.appendChild(el("div", "error-state", "Couldn't load product units: " + err.message));
        });
    }

    addBtn.addEventListener("click", function () {
      addErr.textContent = "";
      var name = nameInput.value.trim();
      var label = labelInput.value.trim();
      var qty = parseFloat(qtyInput.value);
      if (!name || !label || isNaN(qty) || qty <= 0) {
        addErr.textContent = "Ingredient, pack label, and a positive quantity are required.";
        return;
      }
      api.settings.productUnits
        .create({
          ingredient_name: name,
          purchase_label: label,
          purchase_qty: qty,
          purchase_unit: unitInput.value.trim() || null,
          notes: notesInput.value.trim() || null,
        })
        .then(function () {
          nameInput.value = "";
          labelInput.value = "";
          qtyInput.value = "";
          unitInput.value = "";
          notesInput.value = "";
          load();
        })
        .catch(function (err) {
          addErr.textContent = err.message;
        });
    });

    load();
  }

  global.SettingsProductUnitsView = { renderCard: renderCard };
})(window);
