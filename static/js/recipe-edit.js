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

  // (The labelled mini-field + numeric-stepper helpers used to live here too, but only the
  // ingredient rows ever used them — moved to recipe-edit-ingredients.js with the rows
  // themselves when that file was split out for size, see CLAUDE.md > Code Architecture.)

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
    servingsInput.inputMode = "numeric";
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

    // Source provenance (Chunk 3.7) — all optional. Recipe URL, cookbook name, page.
    var sourceUrlInput = el("input");
    sourceUrlInput.type = "text";
    sourceUrlInput.value = r.source_url || "";
    card.appendChild(labeledField("Recipe URL", sourceUrlInput));

    var sourceBookInput = el("input");
    sourceBookInput.type = "text";
    sourceBookInput.value = r.source_book || "";
    card.appendChild(labeledField("Cookbook name", sourceBookInput));

    var sourcePageInput = el("input");
    sourcePageInput.type = "text";
    sourcePageInput.value = r.source_page || "";
    card.appendChild(labeledField("Page", sourcePageInput));

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

    // Draft autosave (Chunk 6.2 kickoff decision #12) — keyed per-recipe so editing #5 never
    // restores into #7's form. Recipe-level fields only, not the ingredient list below.
    var draft = global.DraftAutosave.attach("recipe-edit-" + r.id, {
      name: nameInput,
      servings: servingsInput,
      cuisine: cuisineInput,
      protein: proteinInput,
      sourceUrl: sourceUrlInput,
      sourceBook: sourceBookInput,
      sourcePage: sourcePageInput,
      notes: notesInput,
    });
    draft.restore(); // silent here — re-opening edit mode with the same unsaved text you
                      // left is expected, not a surprise worth calling out like a fresh form

    var saveErr = el("div", "form-error");
    card.appendChild(saveErr);

    var actionsRow = el("div", "log-controls sticky-actions");
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
        source_url: sourceUrlInput.value.trim() || null,
        source_book: sourceBookInput.value.trim() || null,
        source_page: sourcePageInput.value.trim() || null,
        rating: ratingSelect.value || null,
        notes: notesInput.value.trim() || null,
      };
      api.recipes
        .update(r.id, payload)
        .then(function () {
          draft.clear();
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
      ingList.appendChild(global.RecipeEditIngredients.renderRow(r.id, ing, refreshEdit));
    });

    card.appendChild(global.RecipeEditIngredients.renderAddRow(r.id, refreshEdit));

    // --- archive ---------------------------------------------------

    var dangerRow = el("div", "danger-zone");
    var archiveBtn = el("button", null, "Delete recipe");
    archiveBtn.addEventListener("click", function () {
      // Undo toast, not a confirm() dialog (Chunk 6.1 kickoff decision #2) — archive is
      // already reversible (recipes.archive() is a soft-delete, api.recipes.restore()
      // already existed for the duplicate-detection flow), so a blocking "are you sure?"
      // has nothing left to protect against.
      archiveBtn.disabled = true;
      api.recipes
        .archive(r.id)
        .then(function () {
          card.innerHTML = "";
          card.appendChild(el("div", "muted", "Recipe deleted."));
          // Navigating away (onDeleted -> Router.navigate) fires a hashchange, and the
          // shared toast deliberately dies on navigation (kickoff decision #12) — so the
          // navigate is deferred until just past the toast's own lifetime, rather than
          // racing it. Undo cancels the deferred navigate and re-renders in place instead.
          var leaveTimer = global.setTimeout(onDeleted, 5300);
          global.Toast.show('Deleted "' + r.name + '"', {
            actionLabel: "Undo",
            onAction: function () {
              global.clearTimeout(leaveTimer);
              api.recipes
                .restore(r.id)
                .then(function () {
                  render(card, r, onCancel, onDeleted);
                })
                .catch(function (err) {
                  global.alert("Couldn't undo: " + err.message);
                });
            },
          });
        })
        .catch(function (err) {
          archiveBtn.disabled = false;
          saveErr.textContent = "Couldn't delete: " + err.message;
        });
    });
    dangerRow.appendChild(archiveBtn);
    card.appendChild(dangerRow);
  }

  global.RecipeEditView = { mount: mount };
})(window);
