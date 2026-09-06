/* Recipe capture — review + confirm screen. Takes whatever capture.js's extraction
   endpoints returned (a CaptureResult: cuisine/protein/ingredients, each ingredient
   carrying an AI-suggested_section) and renders it as one shared, fully editable form —
   same inline-edit pattern as recipe-form.js/recipe-edit.js. No "can't find X, try Y"
   substitution UI here (resolved 2026-09-05 — see CLAUDE.md > Security decision dialogues
   and > Build Phases > Phase 3 > Chunk 3.4): this is a plain review, not a suggestion
   engine. On confirm, POSTs to /capture/confirm, which also writes product_sections rows
   for any ingredient still carrying a suggested_section — see CLAUDE.md > Recipe Capture. */

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

  function sectionSelect(sections, selected) {
    var select = el("select", "ingredient-section-select");
    var noneOpt = el("option", null, "No section");
    noneOpt.value = "";
    select.appendChild(noneOpt);
    (sections || []).forEach(function (section) {
      var opt = el("option", null, section);
      opt.value = section;
      if (section === selected) opt.selected = true;
      select.appendChild(opt);
    });
    return select;
  }

  function mount(root, captureResult) {
    root.innerHTML = "";

    var back = el("a", "btn", "← Start over");
    back.href = "#/recipes";
    root.appendChild(back);

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Review extracted recipe"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Check the ingredients below — edit anything that's wrong, then save. Nothing is kept until you save."
      )
    );

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. Weeknight Beef Tacos";
    card.appendChild(labeledField("Recipe name", nameInput));

    var servingsInput = el("input");
    servingsInput.type = "number";
    servingsInput.min = "1";
    servingsInput.value = "4";
    card.appendChild(labeledField("Base servings", servingsInput));

    var cuisineInput = el("input");
    cuisineInput.type = "text";
    cuisineInput.value = captureResult.cuisine || "";
    card.appendChild(labeledField("Cuisine (optional)", cuisineInput));

    var proteinInput = el("input");
    proteinInput.type = "text";
    proteinInput.value = captureResult.protein || "";
    card.appendChild(labeledField("Protein (optional)", proteinInput));

    // Source provenance (Chunk 3.7). A URL capture already carries source_url through
    // captureResult, so only the by-hand cookbook name/page are collected here — most
    // relevant for a photographed cookbook page. See CLAUDE.md > Recipe Capture >
    // Source provenance on the review screen.
    var sourceBookInput = el("input");
    sourceBookInput.type = "text";
    card.appendChild(labeledField("Cookbook name (optional)", sourceBookInput));

    var sourcePageInput = el("input");
    sourcePageInput.type = "text";
    card.appendChild(labeledField("Page (optional)", sourcePageInput));

    var notesInput = el("textarea");
    notesInput.rows = 3;
    card.appendChild(labeledField("Notes (optional)", notesInput));

    var ingHeading = el("h2", null, "Ingredients");
    ingHeading.style.marginTop = "16px";
    card.appendChild(ingHeading);

    var ingList = el("div", "ingredient-edit-list");
    var loadingSections = el("div", "muted", "Loading section list...");
    ingList.appendChild(loadingSections);
    card.appendChild(ingList);

    var addRowBtn = el("button", null, "+ Add another ingredient");
    card.appendChild(addRowBtn);

    var formErr = el("div", "form-error");
    card.appendChild(formErr);

    var actionsRow = el("div", "log-controls");
    var saveBtn = el("button", "primary", "Save recipe");
    actionsRow.appendChild(saveBtn);
    card.appendChild(actionsRow);

    root.appendChild(card);

    var rows = []; // { nameInput, qtyInput, unitInput, prepInput, sectionSelect, rowEl }

    // Fetch the section vocabulary once, then build the (already-extracted) ingredient
    // rows — every row needs the same option list, so this gates rendering rather than
    // fetching it per-row.
    api.settings
      .sectionVocabulary()
      .then(function (data) {
        var sections = data.sections || [];
        ingList.removeChild(loadingSections);

        function addIngredientRow(ing) {
          ing = ing || {};
          var nameI = el("input", "ingredient-name-input");
          nameI.type = "text";
          nameI.placeholder = "ingredient name";
          nameI.value = ing.name || "";

          var qtyI = el("input", "ingredient-qty-input");
          qtyI.type = "number";
          qtyI.step = "any";
          qtyI.placeholder = "qty";
          if (ing.quantity != null) qtyI.value = ing.quantity;

          var unitI = el("input", "ingredient-unit-input");
          unitI.type = "text";
          unitI.placeholder = "unit";
          unitI.value = ing.unit || "";

          var prepI = el("input", "ingredient-prep-input");
          prepI.type = "text";
          prepI.placeholder = "preparation";
          prepI.value = ing.preparation || "";

          var sectionI = sectionSelect(sections, ing.suggested_section || "");

          var removeBtn = el("button", null, "Remove");
          var rowEl = el("div", "ingredient-edit-row");
          [nameI, qtyI, unitI, prepI, sectionI, removeBtn].forEach(function (n) {
            rowEl.appendChild(n);
          });
          ingList.appendChild(rowEl);

          var record = {
            nameInput: nameI,
            qtyInput: qtyI,
            unitInput: unitI,
            prepInput: prepI,
            sectionSelect: sectionI,
            rowEl: rowEl,
          };
          rows.push(record);

          removeBtn.addEventListener("click", function () {
            rows = rows.filter(function (r) {
              return r !== record;
            });
            ingList.removeChild(rowEl);
          });
        }

        var extracted = captureResult.ingredients || [];
        if (extracted.length === 0) {
          addIngredientRow(); // nothing extracted — still give the user a row to fill in
        } else {
          extracted.forEach(addIngredientRow);
        }

        addRowBtn.addEventListener("click", function () {
          addIngredientRow();
        });
      })
      .catch(function (err) {
        loadingSections.textContent =
          "Couldn't load the section list (" + err.message + ") — sections can be added later in Settings.";
      });

    saveBtn.addEventListener("click", function () {
      formErr.textContent = "";

      var name = nameInput.value.trim();
      if (!name) {
        formErr.textContent = "Name is required.";
        return;
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
          return;
        }
        ingredients.push({
          name: ingName,
          quantity: qty,
          unit: r.unitInput.value.trim() || null,
          preparation: r.prepInput.value.trim() || null,
          suggested_section: r.sectionSelect.value || null,
        });
      }

      saveBtn.disabled = true;
      api.recipes
        .confirmCapture({
          name: name,
          source_type: captureResult.source_type,
          source_url: captureResult.source_url || null,
          source_image_path: captureResult.source_image_path || null,
          base_servings: parseInt(servingsInput.value, 10) || 1,
          cuisine: cuisineInput.value.trim() || null,
          protein: proteinInput.value.trim() || null,
          source_book: sourceBookInput.value.trim() || null,
          source_page: sourcePageInput.value.trim() || null,
          notes: notesInput.value.trim() || null,
          ingredients: ingredients,
        })
        .then(function (saved) {
          global.Router.navigate("recipes", saved.id);
        })
        .catch(function (err) {
          saveBtn.disabled = false;
          formErr.textContent = "Couldn't save: " + err.message;
        });
    });
  }

  global.CaptureReviewView = { mount: mount };
})(window);
