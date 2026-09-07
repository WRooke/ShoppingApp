/* Recipe capture — review + confirm screen. Takes capture.js's CaptureResult
   (title/servings/cuisine/protein/ingredients + per-ingredient suggested_section + recipe-level
   substitution_flags) and renders one fully editable form. Each ingredient row carries a
   per-ingredient swap control (ingredient-swap.js): the AI's flagged substitution and any
   saved swaps are offered, the user confirms per ingredient, and on confirm the chosen
   resolved_ingredient / substitution_note go in the payload (a "save this swap" tick also
   POSTs a remembered_substitutions row). See CLAUDE.md > AI Provider Migration >
   Ingredient Substitution Flagging. */

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
    // AI-prefilled title (Capture-Fixes-Staged.md issue 1, 2026-09-07) — still fully
    // editable, same "review before saving" treatment as every other extracted field.
    nameInput.value = captureResult.title || "";
    card.appendChild(labeledField("Recipe name", nameInput));

    // Live "you might already have this" hint (Phase 4) — best-effort, on name blur.
    var dupHint = el("div", "dup-hint");
    card.appendChild(dupHint);

    var servingsInput = el("input");
    servingsInput.type = "number";
    servingsInput.min = "1";
    // AI-prefilled servings (Capture-Fixes-Staged.md issue 2) — falls back to the same "4"
    // default as before when the AI didn't return one.
    servingsInput.value = captureResult.servings || 4;
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

    var dupPanel = el("div"); // holds the 409 warn-with-override panel, if shown
    card.appendChild(dupPanel);

    var actionsRow = el("div", "log-controls");
    var saveBtn = el("button", "primary", "Save recipe");
    actionsRow.appendChild(saveBtn);
    card.appendChild(actionsRow);

    global.DupWarn.liveCheck(nameInput, dupHint, function () {
      return {
        source_url: captureResult.source_url || "",
        source_book: sourceBookInput.value.trim(),
        source_page: sourcePageInput.value.trim(),
      };
    });

    root.appendChild(card);

    var rows = []; // { nameInput, qtyInput, unitInput, prepInput, sectionSelect, swap, rowEl }

    // Index the AI's per-recipe substitution flags by the ingredient name they apply to.
    var flagsByName = {};
    (captureResult.substitution_flags || []).forEach(function (f) {
      flagsByName[(f.original || "").toLowerCase()] = f;
    });

    // Fetch the section vocabulary + saved swaps once, then build the ingredient rows.
    Promise.all([
      api.settings.sectionVocabulary(),
      api.settings.substitutions.list().catch(function () {
        return { items: [] };
      }),
    ])
      .then(function (results) {
        var sections = results[0].sections || [];
        var picksByName = {};
        (results[1].items || []).forEach(function (r) {
          (picksByName[r.original_name] = picksByName[r.original_name] || []).push(r);
        });
        ingList.removeChild(loadingSections);

        function addIngredientRow(ing) {
          ing = ing || {};
          var lname = (ing.name || "").toLowerCase();
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
          var swap = global.IngredientSwap.create(
            flagsByName[lname] || null,
            picksByName[lname] || []
          );

          var rowEl = el("div", "ingredient-edit-row");
          [nameI, qtyI, unitI, prepI, sectionI, removeBtn].forEach(function (n) {
            rowEl.appendChild(n);
          });
          var wrapEl = el("div", "ingredient-edit-wrap");
          wrapEl.appendChild(rowEl);
          wrapEl.appendChild(swap.el);
          ingList.appendChild(wrapEl);

          var record = {
            nameInput: nameI,
            qtyInput: qtyI,
            unitInput: unitI,
            prepInput: prepI,
            sectionSelect: sectionI,
            swap: swap,
            rowEl: wrapEl,
          };
          rows.push(record);

          removeBtn.addEventListener("click", function () {
            rows = rows.filter(function (r) {
              return r !== record;
            });
            ingList.removeChild(wrapEl);
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

    var swapsToRemember = []; // filled by collectPayload(), POSTed after a successful save

    function collectPayload() {
      var name = nameInput.value.trim();
      if (!name) {
        formErr.textContent = "Name is required.";
        return null;
      }
      var ingredients = [];
      swapsToRemember = [];
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
        var sw = r.swap.getState();
        if (sw.remember && sw.resolved_ingredient) {
          swapsToRemember.push({
            original_name: ingName,
            substitute_name: sw.resolved_ingredient,
            note: sw.substitution_note,
          });
        }
        ingredients.push({
          name: ingName,
          quantity: qty,
          unit: r.unitInput.value.trim() || null,
          preparation: r.prepInput.value.trim() || null,
          suggested_section: r.sectionSelect.value || null,
          resolved_ingredient: sw.resolved_ingredient,
          substitution_note: sw.substitution_note,
        });
      }
      return {
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
      };
    }

    function submit(allowDuplicate) {
      formErr.textContent = "";
      dupPanel.innerHTML = "";
      var payload = collectPayload();
      if (!payload) return;
      payload.allow_duplicate = !!allowDuplicate;

      saveBtn.disabled = true;
      var remembered = swapsToRemember.slice();
      api.recipes
        .confirmCapture(payload)
        .then(function (saved) {
          // fire-and-forget the "save this swap" ticks — a duplicate is fine
          remembered.forEach(function (s) {
            api.settings.substitutions.create(s).catch(function () {});
          });
          global.Router.navigate("recipes", saved.id);
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
  }

  global.CaptureReviewView = { mount: mount };
})(window);
