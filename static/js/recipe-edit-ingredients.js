/* Ingredient row rendering for recipe-edit.js — split out per CLAUDE.md > Code Architecture
   & Maintainability > file size discipline (recipe-edit.js was pushing past ~400 lines once
   the Chunk 6.2 labelled-field rewrite + Undo-toast wiring landed). Small DOM helpers are
   duplicated rather than imported, matching this file family's existing precedent (recipes.js/
   recipe-form.js/capture-review.js already each keep their own copy) — feature files stay
   self-contained rather than reaching into each other's internals. */

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

  function numberStepper(input, step) {
    step = step || 1;
    var wrap = el("div", "stepper");
    var minus = el("button", null, "−");
    minus.type = "button";
    var plus = el("button", null, "+");
    plus.type = "button";
    minus.addEventListener("click", function () {
      input.value = Math.max(0, (parseFloat(input.value) || 0) - step);
    });
    plus.addEventListener("click", function () {
      input.value = (parseFloat(input.value) || 0) + step;
    });
    wrap.appendChild(minus);
    wrap.appendChild(input);
    wrap.appendChild(plus);
    return wrap;
  }

  function renderIngredientEditRow(recipeId, ing, reload) {
    var row = el("div", "ing-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = ing.name;
    nameInput.className = "ingredient-name-input";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.inputMode = "decimal";
    qtyInput.value = ing.quantity;
    qtyInput.className = "ingredient-qty-input";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.value = ing.unit || "";
    unitInput.className = "ingredient-unit-input";

    var prepInput = el("input");
    prepInput.type = "text";
    prepInput.value = ing.preparation || "";
    prepInput.className = "ingredient-prep-input";

    var grid = el("div", "ing-grid");
    grid.appendChild(miniField("Name", nameInput));
    grid.appendChild(miniField("Qty", numberStepper(qtyInput)));
    grid.appendChild(miniField("Unit", unitInput));
    row.appendChild(grid);
    row.appendChild(miniField("Preparation", prepInput));
    row.appendChild(global.UnitHints.attach(nameInput, unitInput)); // 2026-09-12, see unit-hints.js

    // Substitution (Phase 3.9 M4) — the swap this recipe uses. Blank clears it.
    var resolvedInput = el("input");
    resolvedInput.type = "text";
    resolvedInput.value = ing.resolved_ingredient || "";
    resolvedInput.className = "settings-name-input";

    var subNoteInput = el("input");
    subNoteInput.type = "text";
    subNoteInput.value = ing.substitution_note || "";
    subNoteInput.className = "settings-notes-input";

    // Substitution quantity/unit transform (Phase 3.9 M8) — the swap's absolute amount when
    // it isn't 1:1 in this recipe's unit ("2 cob" -> "2 can"). Blank = keep this row's own
    // quantity/unit. Only meaningful with a resolved ingredient set.
    var subQtyInput = el("input");
    subQtyInput.type = "number";
    subQtyInput.step = "any";
    subQtyInput.inputMode = "decimal";
    subQtyInput.value = ing.resolved_quantity != null ? ing.resolved_quantity : "";
    subQtyInput.className = "ingredient-qty-input";

    var subUnitInput = el("input");
    subUnitInput.type = "text";
    subUnitInput.value = ing.resolved_unit || "";
    subUnitInput.className = "ingredient-unit-input";

    var swapPanel = el("div", "swap-panel");
    swapPanel.appendChild(el("div", "hdr", "Substitution (optional)"));
    swapPanel.appendChild(miniField("Use instead", resolvedInput));
    var swapGrid = el("div", "ing-grid");
    swapGrid.style.gridTemplateColumns = "1fr 1fr"; // amount/unit only — no third column here
    swapGrid.appendChild(miniField("Swap amount", subQtyInput));
    swapGrid.appendChild(miniField("Swap unit", subUnitInput));
    swapPanel.appendChild(swapGrid);
    swapPanel.appendChild(miniField("Swap note", subNoteInput));
    row.appendChild(swapPanel);

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-sm", "Delete");
    var rowErr = el("span", "form-error");
    var actionsRow = el("div", "log-controls");
    actionsRow.style.marginTop = "8px";
    actionsRow.appendChild(saveBtn);
    actionsRow.appendChild(deleteBtn);
    actionsRow.appendChild(rowErr);
    row.appendChild(actionsRow);

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var swapQty = parseFloat(subQtyInput.value);
      var swapUnit = subUnitInput.value.trim();
      var hasTransform = !isNaN(swapQty) && swapQty > 0 && !!swapUnit;
      api.recipes
        .updateIngredient(recipeId, ing.id, {
          name: nameInput.value.trim(),
          quantity: parseFloat(qtyInput.value),
          unit: unitInput.value.trim() || null,
          preparation: prepInput.value.trim() || null,
          resolved_ingredient: resolvedInput.value.trim() || null,
          substitution_note: subNoteInput.value.trim() || null,
          resolved_quantity: hasTransform ? swapQty : null,
          resolved_unit: hasTransform ? swapUnit : null,
        })
        .then(function () {
          reload();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    // Undo toast, not a confirm() dialog (kickoff decision #2) — reload() is a same-view
    // DOM rebuild, not a navigation, so (unlike the whole-recipe delete in recipe-edit.js)
    // there's no hashchange racing the toast here; showing it is safe immediately after the
    // delete.
    deleteBtn.addEventListener("click", function () {
      deleteBtn.disabled = true;
      var snapshot = {
        name: ing.name,
        quantity: ing.quantity,
        unit: ing.unit,
        preparation: ing.preparation,
        resolved_ingredient: ing.resolved_ingredient,
        substitution_note: ing.substitution_note,
        resolved_quantity: ing.resolved_quantity,
        resolved_unit: ing.resolved_unit,
      };
      api.recipes
        .deleteIngredient(recipeId, ing.id)
        .then(function () {
          global.Toast.show('Deleted "' + snapshot.name + '"', {
            actionLabel: "Undo",
            onAction: function () {
              // deleteIngredient has no undo of its own — re-create the row from the
              // snapshot instead (add, then a follow-up update for the substitution
              // fields addIngredient's own schema doesn't accept).
              api.recipes
                .addIngredient(recipeId, {
                  name: snapshot.name,
                  quantity: snapshot.quantity,
                  unit: snapshot.unit,
                  preparation: snapshot.preparation,
                })
                .then(function (created) {
                  if (!snapshot.resolved_ingredient) return null;
                  return api.recipes.updateIngredient(recipeId, created.id, {
                    name: snapshot.name,
                    quantity: snapshot.quantity,
                    unit: snapshot.unit,
                    preparation: snapshot.preparation,
                    resolved_ingredient: snapshot.resolved_ingredient,
                    substitution_note: snapshot.substitution_note,
                    resolved_quantity: snapshot.resolved_quantity,
                    resolved_unit: snapshot.resolved_unit,
                  });
                })
                .then(reload)
                .catch(function (err) {
                  global.alert("Couldn't undo: " + err.message);
                });
            },
          });
          reload();
        })
        .catch(function (err) {
          deleteBtn.disabled = false;
          rowErr.textContent = err.message;
        });
    });

    return row;
  }

  function renderAddIngredientRow(recipeId, reload) {
    var row = el("div", "ing-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. beef mince";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.inputMode = "decimal";
    qtyInput.placeholder = "e.g. 500";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "e.g. g";

    var prepInput = el("input");
    prepInput.type = "text";
    prepInput.placeholder = "e.g. finely diced";

    var grid = el("div", "ing-grid");
    grid.appendChild(miniField("Name", nameInput));
    grid.appendChild(miniField("Qty", numberStepper(qtyInput)));
    grid.appendChild(miniField("Unit", unitInput));
    row.appendChild(grid);
    row.appendChild(miniField("Preparation", prepInput));
    row.appendChild(global.UnitHints.attach(nameInput, unitInput)); // 2026-09-12, see unit-hints.js

    var addBtn = el("button", "btn-sm primary", "+ Add ingredient");
    var rowErr = el("span", "form-error");
    var actionsRow = el("div", "log-controls");
    actionsRow.style.marginTop = "8px";
    actionsRow.appendChild(addBtn);
    actionsRow.appendChild(rowErr);
    row.appendChild(actionsRow);

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      var qty = parseFloat(qtyInput.value);
      if (!name || isNaN(qty)) {
        rowErr.textContent = "Name and quantity are required.";
        return;
      }
      api.recipes
        .addIngredient(recipeId, {
          name: name,
          quantity: qty,
          unit: unitInput.value.trim() || null,
          preparation: prepInput.value.trim() || null,
        })
        .then(function () {
          reload();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    return row;
  }

  global.RecipeEditIngredients = {
    renderRow: renderIngredientEditRow,
    renderAddRow: renderAddIngredientRow,
  };
})(window);
