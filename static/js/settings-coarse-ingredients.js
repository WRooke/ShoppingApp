/* Settings — "Coarse ingredients" card (2026-09-12). Ingredients that skip quantity/unit
   math entirely at consolidation — e.g. parsley, where "10g + 1 tbsp" across two recipes is
   just "buy a bunch", not a number worth reconciling. See docs/ingredient-handling.md > Ingredient Unit
   Handling > Layer D (bought by the bunch).

   Flat list, same CRUD shape as usuals — no grouping needed, each row is one
   ingredient with its own purchase label and "recipes per pack" divisor.

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

  function renderRow(row, listBody) {
    var wrap = el("div", "settings-group-row");

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.value = row.purchase_label || "";

    var perPackInput = el("input");
    perPackInput.type = "number";
    perPackInput.min = "1";
    perPackInput.step = "1";
    perPackInput.inputMode = "numeric";
    perPackInput.value = row.recipes_per_pack;
    perPackInput.title = "How many recipes needing this one pack is assumed to cover";
    perPackInput.className = "ingredient-qty-input";

    var saveBtn = el("button", "btn-sm primary", "Save changes");
    var deleteBtn = el("button", "btn-link-danger", "Remove");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var perPack = parseInt(perPackInput.value, 10);
      if (isNaN(perPack) || perPack < 1) {
        rowErr.textContent = "One has to cover at least 1 recipe.";
        return;
      }
      api.settings.coarseIngredients
        .update(row.id, {
          purchase_label: labelInput.value.trim() || null,
          recipes_per_pack: perPack,
        })
        .then(function (updated) {
          row.purchase_label = updated.purchase_label;
          row.recipes_per_pack = updated.recipes_per_pack;
          row.notes = updated.notes;
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.name,
      row: wrap,
      onDeleted: function (container) {
        if (!container) return;
        global.SettingsRowActions.tidyAfterDelete(container, {
          listBody: container, rowSel: ".settings-group-row", emptyText: "Nothing bought by the bunch yet — add one below.",
        });
      },
      doDelete: function () {
        return api.settings.coarseIngredients.delete(row.id);
      },
      recreate: function () {
        return api.settings.coarseIngredients.create({
          name: row.name,
          purchase_label: row.purchase_label,
          // Without these an Undo silently reset a tuned "recipes per pack" to the default 3.
          recipes_per_pack: row.recipes_per_pack,
          notes: row.notes,
        });
      },
      onRestored: function (created) {
        listBody.appendChild(renderRow(created, listBody));
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    // The name heads its own row (2026-10-16): when it sat under the boxes it read as a heading
    // for the row below.
    wrap.appendChild(el("div", "settings-group-name-line", row.name));
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "2fr 1fr";
    grid.appendChild(miniField("Sold as (blank = just list the name)", labelInput));
    grid.appendChild(miniField("One covers how many recipes?", perPackInput));
    wrap.appendChild(grid);
    var actions = el("div", "settings-row-actions-line");
    actions.appendChild(deleteBtn);
    actions.appendChild(saveBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderAddRow(listBody) {
    var wrap = el("div", "settings-add-card");
    wrap.appendChild(el("div", "settings-add-title", "Add one"));

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. parsley";
    nameInput.className = "settings-name-input";

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "e.g. bunch";
    labelInput.className = "settings-name-input";

    var perPackInput = el("input");
    perPackInput.type = "number";
    perPackInput.min = "1";
    perPackInput.value = "3";

    var addBtn = el("button", "btn-sm primary", "Add");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      if (!name) {
        rowErr.textContent = "Fill in the ingredient.";
        return;
      }
      var perPack = parseInt(perPackInput.value, 10);
      if (isNaN(perPack) || perPack < 1) {
        rowErr.textContent = "One has to cover at least 1 recipe.";
        return;
      }
      api.settings.coarseIngredients
        .create({ name: name, purchase_label: labelInput.value.trim() || null, recipes_per_pack: perPack })
        .then(function (created) {
          if (listBody.querySelector(".empty-state")) listBody.innerHTML = "";
          listBody.appendChild(renderRow(created, listBody));
          nameInput.value = "";
          labelInput.value = "";
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr";
    grid.appendChild(miniField("Ingredient", nameInput));
    grid.appendChild(miniField("Sold as (blank = just list the name)", labelInput));
    wrap.appendChild(grid);
    wrap.appendChild(miniField("One covers how many recipes?", perPackInput));
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(addBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Bought by the bunch"));
    card.appendChild(
      el(
        "div",
        "muted",
        "For things like parsley, where the amount in a recipe doesn’t matter: your list counts " +
          "how many planned recipes use it. e.g. 1 bunch covers 3 recipes, so 4 recipes = 2 bunches."
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
    card.appendChild(addSlot);
    root.appendChild(card);

    api.settings.coarseIngredients
      .list()
      .then(function (data) {
        listBody.innerHTML = "";
        var items = data.items || [];
        if (items.length === 0) {
          listBody.appendChild(el("div", "empty-state", "Nothing bought by the bunch yet — add one below."));
        } else {
          items.forEach(function (row) {
            listBody.appendChild(renderRow(row, listBody));
          });
        }
        addSlot.appendChild(renderAddRow(listBody));
      })
      .catch(function (err) {
        listBody.innerHTML = "";
        listBody.appendChild(el("div", "error-state", "Couldn't load coarse ingredients: " + err.message));
      });
  }

  global.SettingsCoarseIngredientsView = { renderCard: renderCard };
})(window);
