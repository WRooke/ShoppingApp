/* Settings — "Coarse ingredients" card (2026-09-12). Ingredients that skip quantity/unit
   math entirely at consolidation — e.g. parsley, where "10g + 1 tbsp" across two recipes is
   just "buy a bunch", not a number worth reconciling. See CLAUDE.md > Ingredient Unit
   Handling > Layer D.

   Flat list, same CRUD shape as staples/usuals — no grouping needed, each row is one
   ingredient with its own purchase label and "recipes per pack" divisor. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderRow(row, onChanged) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.name));

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "purchase label, e.g. bunch";
    labelInput.value = row.purchase_label || "";
    labelInput.className = "settings-name-input";

    var perPackInput = el("input");
    perPackInput.type = "number";
    perPackInput.min = "1";
    perPackInput.step = "1";
    perPackInput.value = row.recipes_per_pack;
    perPackInput.title = "How many recipes needing this one pack is assumed to cover";
    perPackInput.className = "ingredient-qty-input";

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var perPack = parseInt(perPackInput.value, 10);
      if (isNaN(perPack) || perPack < 1) {
        rowErr.textContent = "Recipes per pack must be at least 1.";
        return;
      }
      api.settings.coarseIngredients
        .update(row.id, {
          purchase_label: labelInput.value.trim() || null,
          recipes_per_pack: perPack,
        })
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Stop treating "' + row.name + '" as a coarse ingredient?')) return;
      api.settings.coarseIngredients
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [labelInput, el("span", "muted", "per"), perPackInput, el("span", "muted", "recipe(s)"), saveBtn, deleteBtn, rowErr]
      .forEach(function (n) {
        wrap.appendChild(n);
      });
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "ingredient name, e.g. parsley";
    nameInput.className = "settings-name-input";

    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "purchase label, e.g. bunch (optional)";
    labelInput.className = "settings-name-input";

    var addBtn = el("button", "primary", "Add");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      if (!name) {
        rowErr.textContent = "A name is required.";
        return;
      }
      api.settings.coarseIngredients
        .create({ name: name, purchase_label: labelInput.value.trim() || null })
        .then(function () {
          nameInput.value = "";
          labelInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, labelInput, addBtn, rowErr].forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Coarse ingredients"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Ingredients where precise quantities aren't worth tracking — any recipe needing " +
          "one resolves straight to a purchase count (e.g. “2 × bunch”), scaled by how many " +
          "recipes use it, not by the amount each one calls for. Recipes per pack is a rough " +
          "guess you can tune per ingredient."
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
      api.settings.coarseIngredients
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var items = data.items || [];
          if (items.length === 0) {
            listBody.appendChild(el("div", "muted", "No coarse ingredients yet — add one below."));
          } else {
            items.forEach(function (row) {
              listBody.appendChild(renderRow(row, load));
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load coarse ingredients: " + err.message;
        });
    }

    load();
  }

  global.SettingsCoarseIngredientsView = { renderCard: renderCard };
})(window);
