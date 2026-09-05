/* Recipe detail edit mode: editing recipe-level fields and inline
   ingredient CRUD for an *existing* recipe. Split out from recipes.js per
   CLAUDE.md > Code Architecture & Maintainability > file size discipline
   (recipes.js was pushing past the ~400-line guideline once list view,
   view-mode detail, edit-mode detail, and ingredient row rendering were all
   in one file). Small DOM helpers are duplicated rather than imported from
   recipes.js, matching the existing recipe-form.js precedent — feature files
   stay self-contained rather than reaching into each other's internals. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function labeledField(labelText, inputEl) {
    var wrap = el("div", "field");
    wrap.appendChild(el("label", null, labelText));
    wrap.appendChild(inputEl);
    return wrap;
  }

  // card: the detail card element to render into (replaces its contents)
  // r: the recipe, as returned by the API
  // onCancel: called (with no reload) to drop back to view mode
  // onDeleted: called after the recipe is archived, to navigate away
  function mount(card, r, onCancel, onDeleted) {
    render(card, r, onCancel, onDeleted);
  }

  function render(card, r, onCancel, onDeleted) {
    card.innerHTML = "";
    card.appendChild(el("h2", null, "Edit recipe"));

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = r.name;
    card.appendChild(labeledField("Name", nameInput));

    var servingsInput = el("input");
    servingsInput.type = "number";
    servingsInput.min = "1";
    servingsInput.value = r.base_servings;
    card.appendChild(labeledField("Base servings", servingsInput));

    var cuisineInput = el("input");
    cuisineInput.type = "text";
    cuisineInput.value = r.cuisine || "";
    card.appendChild(labeledField("Cuisine", cuisineInput));

    var proteinInput = el("input");
    proteinInput.type = "text";
    proteinInput.value = r.protein || "";
    card.appendChild(labeledField("Protein", proteinInput));

    var ratingSelect = el("select");
    [
      { value: "", label: "Unrated" },
      { value: "up", label: "👍 Good" },
      { value: "down", label: "👎 Not again" },
    ].forEach(function (opt) {
      var o = el("option", null, opt.label);
      o.value = opt.value;
      ratingSelect.appendChild(o);
    });
    ratingSelect.value = r.rating || "";
    card.appendChild(labeledField("Rating", ratingSelect));

    var notesInput = el("textarea");
    notesInput.rows = 3;
    notesInput.value = r.notes || "";
    card.appendChild(labeledField("Notes", notesInput));

    var saveErr = el("div", "form-error");
    card.appendChild(saveErr);

    var actionsRow = el("div", "log-controls");
    var saveBtn = el("button", "primary", "Save");
    var cancelBtn = el("button", null, "Cancel");
    actionsRow.appendChild(saveBtn);
    actionsRow.appendChild(cancelBtn);
    card.appendChild(actionsRow);

    cancelBtn.addEventListener("click", function () {
      onCancel();
    });

    saveBtn.addEventListener("click", function () {
      saveErr.textContent = "";
      var payload = {
        name: nameInput.value.trim(),
        base_servings: parseInt(servingsInput.value, 10) || 1,
        cuisine: cuisineInput.value.trim() || null,
        protein: proteinInput.value.trim() || null,
        rating: ratingSelect.value || null,
        notes: notesInput.value.trim() || null,
      };
      api.recipes
        .update(r.id, payload)
        .then(function () {
          onCancel(); // back to (now-updated) view mode, same as Cancel
        })
        .catch(function (err) {
          saveErr.textContent = "Couldn't save: " + err.message;
        });
    });

    // --- ingredients ---------------------------------------------------
    // Adding/editing/deleting an ingredient re-fetches and stays in edit mode
    // (refreshEdit) rather than dropping back to view mode — building out a
    // recipe usually means adding several ingredients in a row.

    function refreshEdit() {
      api.recipes
        .get(r.id)
        .then(function (freshR) {
          render(card, freshR, onCancel, onDeleted);
        })
        .catch(function (err) {
          saveErr.textContent = "Couldn't refresh: " + err.message;
        });
    }

    var ingHeading = el("h2", null, "Ingredients");
    ingHeading.style.marginTop = "16px";
    card.appendChild(ingHeading);

    var ingList = el("div", "ingredient-edit-list");
    card.appendChild(ingList);

    (r.ingredients || []).forEach(function (ing) {
      ingList.appendChild(renderIngredientEditRow(r.id, ing, refreshEdit));
    });

    card.appendChild(renderAddIngredientRow(r.id, refreshEdit));

    // --- archive ---------------------------------------------------

    var dangerRow = el("div", "danger-zone");
    var archiveBtn = el("button", null, "Delete recipe");
    archiveBtn.addEventListener("click", function () {
      if (!global.confirm("Delete \"" + r.name + "\"? It can still be found via history later.")) {
        return;
      }
      api.recipes
        .archive(r.id)
        .then(function () {
          onDeleted();
        })
        .catch(function (err) {
          saveErr.textContent = "Couldn't delete: " + err.message;
        });
    });
    dangerRow.appendChild(archiveBtn);
    card.appendChild(dangerRow);
  }

  function renderIngredientEditRow(recipeId, ing, reload) {
    var row = el("div", "ingredient-edit-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = ing.name;
    nameInput.className = "ingredient-name-input";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.value = ing.quantity;
    qtyInput.className = "ingredient-qty-input";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.value = ing.unit || "";
    unitInput.placeholder = "unit";
    unitInput.className = "ingredient-unit-input";

    var prepInput = el("input");
    prepInput.type = "text";
    prepInput.value = ing.preparation || "";
    prepInput.placeholder = "preparation";
    prepInput.className = "ingredient-prep-input";

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      api.recipes
        .updateIngredient(recipeId, ing.id, {
          name: nameInput.value.trim(),
          quantity: parseFloat(qtyInput.value),
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

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm("Remove this ingredient?")) return;
      api.recipes
        .deleteIngredient(recipeId, ing.id)
        .then(function () {
          reload();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, qtyInput, unitInput, prepInput, saveBtn, deleteBtn, rowErr].forEach(function (n) {
      row.appendChild(n);
    });
    return row;
  }

  function renderAddIngredientRow(recipeId, reload) {
    var row = el("div", "ingredient-edit-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "New ingredient name";

    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.placeholder = "qty";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "unit";

    var prepInput = el("input");
    prepInput.type = "text";
    prepInput.placeholder = "preparation";

    var addBtn = el("button", "primary", "Add");
    var rowErr = el("span", "form-error");

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

    [nameInput, qtyInput, unitInput, prepInput, addBtn, rowErr].forEach(function (n) {
      row.appendChild(n);
    });
    return row;
  }

  global.RecipeEditView = { mount: mount };
})(window);
