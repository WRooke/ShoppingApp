/* Recipe library view: browse list (search by name) + recipe detail, with
   inline editing of recipe-level fields and ingredients. Manual "new recipe
   from scratch" entry lives in recipe-form.js (see CLAUDE.md > Code
   Architecture & Maintainability > file size discipline — split by
   sub-feature rather than growing one file past ~400 lines). */

(function (global) {
  "use strict";

  var state = {
    search: "",
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtServings(n) {
    return n + (n === 1 ? " serving" : " servings");
  }

  function ratingLabel(rating) {
    if (rating === "up") return "👍";
    if (rating === "down") return "👎";
    return null;
  }

  // --- list view -----------------------------------------------------

  function renderList(root) {
    root.innerHTML = "";

    var searchCard = el("div", "card");
    var searchRow = el("div", "log-controls");
    var input = el("input");
    input.type = "text";
    input.placeholder = "Search recipes by name...";
    input.value = state.search;
    input.setAttribute("aria-label", "Search recipes by name");
    searchRow.appendChild(input);
    searchCard.appendChild(searchRow);
    root.appendChild(searchCard);

    var newLink = el("a", "btn primary", "+ Add recipe");
    newLink.href = "#/recipes/new";
    newLink.style.display = "inline-block";
    newLink.style.marginBottom = "16px";
    root.appendChild(newLink);

    var listCard = el("div", "card");
    listCard.appendChild(el("h2", null, "Recipes"));
    var listBody = el("div");
    listBody.id = "recipe-list-body";
    listBody.textContent = "Loading...";
    listCard.appendChild(listBody);
    root.appendChild(listCard);

    function load() {
      listBody.textContent = "Loading...";
      api.recipes
        .list({ search: state.search, limit: 200 })
        .then(function (data) {
          renderListBody(listBody, data.items);
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load recipes: " + err.message;
        });
    }

    var debounceTimer = null;
    input.addEventListener("input", function () {
      state.search = input.value;
      if (debounceTimer) global.clearTimeout(debounceTimer);
      debounceTimer = global.setTimeout(load, 250);
    });

    load();
  }

  function renderListBody(container, items) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
      container.appendChild(el("div", "muted", "No recipes found."));
      return;
    }
    items.forEach(function (r) {
      var row = el("a", "recipe-row");
      row.href = "#/recipes/" + r.id;

      var main = el("div", "recipe-row-main");
      main.appendChild(el("div", "recipe-row-name", r.name));
      var metaBits = [fmtServings(r.base_servings)];
      if (r.cuisine) metaBits.push(r.cuisine);
      if (r.protein) metaBits.push(r.protein);
      main.appendChild(el("div", "recipe-row-meta muted", metaBits.join(" · ")));
      row.appendChild(main);

      var rating = ratingLabel(r.rating);
      if (rating) row.appendChild(el("div", "recipe-row-rating", rating));

      container.appendChild(row);
    });
  }

  // --- detail view (view mode) -----------------------------------------

  function renderDetail(root, id) {
    root.innerHTML = "";

    var back = el("a", "btn", "← Back to recipes");
    back.href = "#/recipes";
    root.appendChild(back);

    var card = el("div", "card");
    card.textContent = "Loading...";
    root.appendChild(card);

    function load() {
      api.recipes
        .get(id)
        .then(function (r) {
          renderDetailView(card, r, load);
        })
        .catch(function (err) {
          card.innerHTML = "";
          if (err.code === "RECIPE_NOT_FOUND") {
            card.appendChild(
              el("div", "muted", "This recipe couldn't be found. It may have been deleted.")
            );
          } else {
            card.appendChild(el("div", "muted", "Couldn't load this recipe: " + err.message));
          }
        });
    }

    load();
  }

  function renderDetailView(card, r, reload) {
    card.innerHTML = "";

    var headRow = el("div", "detail-head-row");
    headRow.appendChild(el("h2", null, r.name));
    var editBtn = el("button", null, "Edit");
    editBtn.addEventListener("click", function () {
      renderDetailEdit(card, r, reload);
    });
    headRow.appendChild(editBtn);
    card.appendChild(headRow);

    var metaBits = [fmtServings(r.base_servings)];
    if (r.cuisine) metaBits.push(r.cuisine);
    if (r.protein) metaBits.push(r.protein);
    var rating = ratingLabel(r.rating);
    if (rating) metaBits.push(rating);
    card.appendChild(el("div", "muted", metaBits.join(" · ")));

    if (r.archived_at) {
      card.appendChild(el("div", "muted", "Archived"));
    }

    var ingHeading = el("h2", null, "Ingredients");
    ingHeading.style.marginTop = "16px";
    card.appendChild(ingHeading);

    if (!r.ingredients || r.ingredients.length === 0) {
      card.appendChild(el("div", "muted", "No ingredients recorded."));
    } else {
      var list = el("ul", "ingredient-list");
      r.ingredients.forEach(function (ing) {
        var parts = [];
        parts.push(ing.quantity + (ing.unit ? " " + ing.unit : ""));
        parts.push(ing.name);
        if (ing.preparation) parts.push("(" + ing.preparation + ")");
        list.appendChild(el("li", null, parts.join(" ")));
      });
      card.appendChild(list);
    }

    if (r.notes) {
      var notesHeading = el("h2", null, "Notes");
      notesHeading.style.marginTop = "16px";
      card.appendChild(notesHeading);
      card.appendChild(el("div", null, r.notes));
    }
  }

  // --- detail view (edit mode) -----------------------------------------

  function labeledField(labelText, inputEl) {
    var wrap = el("div", "field");
    wrap.appendChild(el("label", null, labelText));
    wrap.appendChild(inputEl);
    return wrap;
  }

  function renderDetailEdit(card, r, reload) {
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
      renderDetailView(card, r, reload);
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
          reload();
        })
        .catch(function (err) {
          saveErr.textContent = "Couldn't save: " + err.message;
        });
    });

    // --- ingredients ---------------------------------------------------
    // Adding/editing/deleting an ingredient re-fetches and stays in edit mode
    // (refreshEdit) rather than dropping back to view mode (reload) — building
    // out a recipe usually means adding several ingredients in a row.

    function refreshEdit() {
      api.recipes
        .get(r.id)
        .then(function (freshR) {
          renderDetailEdit(card, freshR, reload);
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
          global.location.hash = "#/recipes";
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

  // --- entry point -----------------------------------------------------

  function mount(root, param) {
    if (param === "new") {
      global.RecipeFormView.mount(root);
    } else if (param) {
      renderDetail(root, param);
    } else {
      renderList(root);
    }
  }

  function unmount() {
    // Nothing to tear down yet — no timers/intervals in this view.
  }

  global.RecipesView = { mount: mount, unmount: unmount };
})(window);
