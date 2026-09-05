/* Settings view: view/add/edit/delete for the `staples` and `product_units`
   reference catalogue (see CLAUDE.md > Build Phases > Phase 2 > Chunk 2.5).
   This is what makes the seeded data from Chunk 2.1 actually editable. Two
   independent cards, each following the same list-of-editable-rows + add-row
   pattern already established in recipes.js for ingredients — kept as its
   own file per CLAUDE.md > Code Architecture & Maintainability (own feature
   area, own DOM/state, never reaches into recipes.js). */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // --- staples ---------------------------------------------------------

  function renderStapleRow(staple, onChanged) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = staple.name;
    nameInput.className = "settings-name-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = staple.notes || "";
    notesInput.placeholder = "notes";
    notesInput.className = "settings-notes-input";

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      api.settings.staples
        .update(staple.id, {
          name: nameInput.value.trim(),
          notes: notesInput.value.trim() || null,
        })
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Remove "' + staple.name + '" from staples?')) return;
      api.settings.staples
        .delete(staple.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, notesInput, saveBtn, deleteBtn, rowErr].forEach(function (n) {
      row.appendChild(n);
    });
    return row;
  }

  function renderAddStapleRow(onAdded) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "New staple name";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "notes";

    var addBtn = el("button", "primary", "Add");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      if (!name) {
        rowErr.textContent = "Name is required.";
        return;
      }
      api.settings.staples
        .create({ name: name, notes: notesInput.value.trim() || null })
        .then(onAdded)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, notesInput, addBtn, rowErr].forEach(function (n) {
      row.appendChild(n);
    });
    return row;
  }

  function renderStaplesCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Staples"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Assumed to already be on hand — only shown on the checklist when a recipe in the session needs them."
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
      api.settings.staples
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          if (!data.items || data.items.length === 0) {
            listBody.appendChild(el("div", "muted", "No staples yet."));
          } else {
            data.items.forEach(function (s) {
              listBody.appendChild(renderStapleRow(s, load));
            });
          }
          addSlot.appendChild(renderAddStapleRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load staples: " + err.message;
        });
    }

    load();
  }

  // --- product units -----------------------------------------------------

  function renderProductUnitRow(unit, onChanged) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = unit.ingredient_name;
    nameInput.className = "settings-name-input";
    nameInput.placeholder = "ingredient";

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.value = unit.purchase_label;
    labelInput.placeholder = "pack label";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.value = unit.purchase_qty;
    qtyInput.className = "ingredient-qty-input";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.value = unit.purchase_unit || "";
    unitInput.placeholder = "unit";
    unitInput.className = "ingredient-unit-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = unit.notes || "";
    notesInput.placeholder = "notes";
    notesInput.className = "settings-notes-input";

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    if (unit.is_preseeded) {
      row.appendChild(el("span", "muted", "seeded"));
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
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Remove the purchase unit for "' + unit.ingredient_name + '"?')) return;
      api.settings.productUnits
        .delete(unit.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, labelInput, qtyInput, unitInput, notesInput, saveBtn, deleteBtn, rowErr].forEach(
      function (n) {
        row.appendChild(n);
      }
    );
    return row;
  }

  function renderAddProductUnitRow(onAdded) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "ingredient";

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "pack label, e.g. 500g pack";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.placeholder = "qty";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "unit, e.g. g";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "notes";

    var addBtn = el("button", "primary", "Add");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      var label = labelInput.value.trim();
      var qty = parseFloat(qtyInput.value);
      if (!name || !label || isNaN(qty) || qty <= 0) {
        rowErr.textContent = "Ingredient, pack label, and a positive quantity are required.";
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
        .then(onAdded)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, labelInput, qtyInput, unitInput, notesInput, addBtn, rowErr].forEach(function (n) {
      row.appendChild(n);
    });
    return row;
  }

  function renderProductUnitsCard(root) {
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
    listBody.textContent = "Loading...";
    card.appendChild(listBody);
    var addSlot = el("div");
    card.appendChild(addSlot);
    root.appendChild(card);

    function load() {
      listBody.textContent = "Loading...";
      api.settings.productUnits
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          if (!data.items || data.items.length === 0) {
            listBody.appendChild(el("div", "muted", "No product units yet."));
          } else {
            data.items.forEach(function (u) {
              listBody.appendChild(renderProductUnitRow(u, load));
            });
          }
          addSlot.appendChild(renderAddProductUnitRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load product units: " + err.message;
        });
    }

    load();
  }

  // --- entry point -----------------------------------------------------

  function mount(root) {
    root.innerHTML = "";
    renderStaplesCard(root);
    renderProductUnitsCard(root);
  }

  function unmount() {
    // Nothing to tear down yet — no timers/intervals in this view.
  }

  global.SettingsView = { mount: mount, unmount: unmount };
})(window);
