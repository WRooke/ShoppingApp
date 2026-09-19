/* Settings — "Product units" card (see CLAUDE.md > Build Phases > Phase 2 > Chunk 2.5, and
   > Phase 4 > product_units multi-pack-size note). Split out of settings.js per CLAUDE.md >
   Code Architecture & Maintainability > file size discipline.

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM updates instead of a full list rebuild on
   every Save/Add/Delete (the scroll-position bug). */

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

  function renderProductUnitRow(unit, listBody) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = unit.ingredient_name;
    nameInput.className = "settings-name-input";

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
    var deleteBtn = el("button", "btn-sm", "Delete");
    var rowErr = el("span", "form-error");

    if (unit.is_preseeded) {
      row.appendChild(el("span", "muted", "Seeded"));
    }

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var qty = parseFloat(qtyInput.value);
      if (isNaN(qty) || qty <= 0) {
        rowErr.textContent = "Purchase quantity must be a positive number.";
        return;
      }
      api.settings.productUnits
        .update(unit.id, {
          ingredient_name: nameInput.value.trim(),
          purchase_label: labelInput.value.trim(),
          purchase_qty: qty,
          purchase_unit: unitInput.value.trim() || null,
          notes: notesInput.value.trim() || null,
        })
        .then(function (updated) {
          unit.ingredient_name = updated.ingredient_name;
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
      onRestored: function (created) {
        listBody.appendChild(renderProductUnitRow(created, listBody));
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    var grid = el("div", "ing-grid");
    grid.appendChild(miniField("Ingredient", nameInput));
    grid.appendChild(miniField("Pack label", labelInput));
    grid.appendChild(miniField("Notes", notesInput));
    row.appendChild(grid);
    var grid2 = el("div", "ing-grid");
    grid2.style.gridTemplateColumns = "1fr 1fr";
    grid2.appendChild(miniField("Pack quantity", qtyInput));
    grid2.appendChild(miniField("Unit", unitInput));
    row.appendChild(grid2);
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(rowErr);
    row.appendChild(actions);
    return row;
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
        "How each ingredient is actually bought, e.g. eggs as a dozen. Used to turn a scaled quantity into a shopping-list amount."
      )
    );

    var listBody = el("div", "settings-list");
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    listBody.appendChild(skel);
    card.appendChild(listBody);

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

    var addWrap = el("div");
    addWrap.style.marginTop = "12px";
    var addGrid = el("div", "ing-grid");
    addGrid.appendChild(miniField("Ingredient", nameInput));
    addGrid.appendChild(miniField("Pack label", labelInput));
    addGrid.appendChild(miniField("Notes", notesInput));
    addWrap.appendChild(addGrid);
    var addGrid2 = el("div", "ing-grid");
    addGrid2.style.gridTemplateColumns = "1fr 1fr";
    addGrid2.appendChild(miniField("Pack quantity", qtyInput));
    addGrid2.appendChild(miniField("Unit", unitInput));
    addWrap.appendChild(addGrid2);
    var addActions = el("div", "log-controls");
    addActions.style.marginTop = "6px";
    addActions.appendChild(addBtn);
    addActions.appendChild(addErr);
    addWrap.appendChild(addActions);
    card.appendChild(addWrap);
    root.appendChild(card);

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
        .then(function (created) {
          if (listBody.querySelector(".empty-state")) listBody.innerHTML = "";
          listBody.appendChild(renderProductUnitRow(created, listBody));
          nameInput.value = "";
          labelInput.value = "";
          qtyInput.value = "";
          unitInput.value = "";
          notesInput.value = "";
        })
        .catch(function (err) {
          addErr.textContent = err.message;
        });
    });

    api.settings.productUnits
      .list()
      .then(function (data) {
        listBody.innerHTML = "";
        var items = data.items || [];
        if (items.length === 0) {
          listBody.appendChild(el("div", "empty-state", "No product units yet."));
        } else {
          items.forEach(function (u) {
            listBody.appendChild(renderProductUnitRow(u, listBody));
          });
        }
      })
      .catch(function (err) {
        listBody.innerHTML = "";
        listBody.appendChild(el("div", "error-state", "Couldn't load product units: " + err.message));
      });
  }

  global.SettingsProductUnitsView = { renderCard: renderCard };
})(window);
