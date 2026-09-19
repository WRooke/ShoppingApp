/* Manual "new recipe from scratch" entry form — no capture involved (that's
   Phase 3). Split out from recipes.js per CLAUDE.md > Code Architecture &
   Maintainability > file size discipline. Builds a local ingredient list and
   submits the whole recipe in one POST (RecipeCreate accepts nested
   ingredients), unlike editing an existing recipe where each ingredient is
   its own row in the database already. */

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

  // Chunk 6.2 — the smaller labelled-field pattern for dense ingredient rows.
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

  function mount(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("recipes"));

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Add a recipe"));

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. Spaghetti Bolognese";
    card.appendChild(labeledField("Name", nameInput));

    // Live "you might already have this" hint (Phase 4) — best-effort, on name blur.
    var dupHint = el("div", "dup-hint");
    card.appendChild(dupHint);

    var servingsInput = el("input");
    servingsInput.type = "number";
    servingsInput.min = "1";
    servingsInput.inputMode = "numeric";
    servingsInput.value = "4";
    card.appendChild(labeledField("Base servings", servingsInput));

    var cuisineInput = el("input");
    cuisineInput.type = "text";
    card.appendChild(labeledField("Cuisine (optional)", cuisineInput));

    var proteinInput = el("input");
    proteinInput.type = "text";
    card.appendChild(labeledField("Protein (optional)", proteinInput));

    // Source provenance (Chunk 3.7) — all optional.
    var sourceUrlInput = el("input");
    sourceUrlInput.type = "text";
    card.appendChild(labeledField("Recipe URL (optional)", sourceUrlInput));

    var sourceBookInput = el("input");
    sourceBookInput.type = "text";
    card.appendChild(labeledField("Cookbook name (optional)", sourceBookInput));

    var sourcePageInput = el("input");
    sourcePageInput.type = "text";
    card.appendChild(labeledField("Page (optional)", sourcePageInput));

    var notesInput = el("textarea");
    notesInput.rows = 3;
    card.appendChild(labeledField("Notes (optional)", notesInput));

    // Draft autosave (Chunk 6.2 kickoff decision #12) — recipe-level fields only, not the
    // dynamic ingredient list below (see draft-autosave.js's own header comment for why).
    var draft = global.DraftAutosave.attach("recipe-new", {
      name: nameInput,
      servings: servingsInput,
      cuisine: cuisineInput,
      protein: proteinInput,
      sourceUrl: sourceUrlInput,
      sourceBook: sourceBookInput,
      sourcePage: sourcePageInput,
      notes: notesInput,
    });
    if (draft.restore()) {
      var draftNote = el("div", "draft-note");
      draftNote.appendChild(el("span", "draft-dot"));
      draftNote.appendChild(document.createTextNode("Restored an unsaved draft"));
      card.insertBefore(draftNote, card.firstChild.nextSibling);
    }

    var ingHeading = el("h2", null, "Ingredients");
    ingHeading.style.marginTop = "16px";
    card.appendChild(ingHeading);

    var ingList = el("div", "ingredient-edit-list");
    card.appendChild(ingList);

    var rows = []; // { nameInput, qtyInput, unitInput, prepInput, rowEl }

    function addIngredientRow() {
      var nameI = el("input");
      nameI.type = "text";
      nameI.placeholder = "e.g. beef mince";

      var qtyI = el("input");
      qtyI.type = "number";
      qtyI.step = "any";
      qtyI.inputMode = "decimal";
      qtyI.placeholder = "e.g. 500";

      var unitI = el("input");
      unitI.type = "text";
      unitI.placeholder = "e.g. g";

      var prepI = el("input");
      prepI.type = "text";
      prepI.placeholder = "e.g. finely diced";

      var removeBtn = el("button", "btn-sm", "Remove");
      var rowEl = el("div", "ing-row");
      var grid = el("div", "ing-grid");
      grid.appendChild(miniField("Name", nameI));
      grid.appendChild(miniField("Qty", numberStepper(qtyI)));
      grid.appendChild(miniField("Unit", unitI));
      rowEl.appendChild(grid);
      rowEl.appendChild(miniField("Preparation", prepI));
      rowEl.appendChild(global.UnitHints.attach(nameI, unitI)); // 2026-09-12, see unit-hints.js
      var removeRow = el("div", "log-controls");
      removeRow.style.marginTop = "8px";
      removeRow.appendChild(removeBtn);
      rowEl.appendChild(removeRow);
      ingList.appendChild(rowEl);

      var record = { nameInput: nameI, qtyInput: qtyI, unitInput: unitI, prepInput: prepI, rowEl: rowEl };
      rows.push(record);

      removeBtn.addEventListener("click", function () {
        rows = rows.filter(function (r) {
          return r !== record;
        });
        ingList.removeChild(rowEl);
      });
    }

    // Start with one empty ingredient row so the form isn't intimidatingly bare.
    addIngredientRow();

    var addRowBtn = el("button", null, "+ Add another ingredient");
    addRowBtn.addEventListener("click", addIngredientRow);
    card.appendChild(addRowBtn);

    var formErr = el("div", "form-error");
    card.appendChild(formErr);

    var dupPanel = el("div"); // holds the 409 warn-with-override panel, if shown
    card.appendChild(dupPanel);

    var actionsRow = el("div", "log-controls sticky-actions");
    var saveBtn = el("button", "primary", "Save recipe");
    actionsRow.appendChild(saveBtn);
    card.appendChild(actionsRow);

    global.DupWarn.liveCheck(nameInput, dupHint, function () {
      return {
        source_url: sourceUrlInput.value.trim(),
        source_book: sourceBookInput.value.trim(),
        source_page: sourcePageInput.value.trim(),
      };
    });

    function collectPayload() {
      var name = nameInput.value.trim();
      if (!name) {
        formErr.textContent = "Name is required.";
        return null;
      }
      var ingredients = [];
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var ingName = r.nameInput.value.trim();
        var qtyRaw = r.qtyInput.value.trim();
        if (!ingName && !qtyRaw) continue; // skip fully-empty rows
        var qty = parseFloat(qtyRaw);
        if (!ingName || isNaN(qty)) {
          formErr.textContent = "Each ingredient needs a name and a numeric quantity.";
          return null;
        }
        ingredients.push({
          name: ingName,
          quantity: qty,
          unit: r.unitInput.value.trim() || null,
          preparation: r.prepInput.value.trim() || null,
        });
      }
      return {
        name: name,
        source_type: "manual",
        base_servings: parseInt(servingsInput.value, 10) || 1,
        cuisine: cuisineInput.value.trim() || null,
        protein: proteinInput.value.trim() || null,
        source_url: sourceUrlInput.value.trim() || null,
        source_book: sourceBookInput.value.trim() || null,
        source_page: sourcePageInput.value.trim() || null,
        notes: notesInput.value.trim() || null,
        ingredients: ingredients,
      };
    }

    function submit(allowDuplicate) {
      formErr.textContent = "";
      dupPanel.innerHTML = "";
      var payload = collectPayload();
      if (!payload) return;
      payload.allow_duplicate = !!allowDuplicate;

      saveBtn.disabled = true;
      api.recipes
        .create(payload)
        .then(function (created) {
          draft.clear();
          global.Router.navigate("recipes", created.id);
        })
        .catch(function (err) {
          saveBtn.disabled = false;
          if (err.code === "POSSIBLE_DUPLICATE_RECIPE" && Array.isArray(err.detail)) {
            dupPanel.appendChild(
              global.DupWarn.panel(err.detail, {
                onSaveAnyway: function () {
                  submit(true);
                },
                onRestore: function (id) {
                  api.recipes
                    .restore(id)
                    .then(function () {
                      global.Router.navigate("recipes", id);
                    })
                    .catch(function (e) {
                      formErr.textContent = "Couldn't restore: " + e.message;
                    });
                },
              })
            );
            return;
          }
          formErr.textContent = "Couldn't save: " + err.message;
        });
    }

    saveBtn.addEventListener("click", function () {
      submit(false);
    });

    root.appendChild(card);
  }

  function unmount() {}

  global.RecipeFormView = { mount: mount, unmount: unmount };
})(window);
