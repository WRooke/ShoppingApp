/* Settings — "Ingredient groups" card (2026-09-10). "Same shopping item" aliases — e.g.
   "canola oil" and "oil spray" both folded into "vegetable oil" on the shopping list.

   Deliberately NOT the same feature as "Saved ingredient swaps" (settings-substitutions.js)
   even though the two cards look superficially similar (both group rows and offer a
   free-text pair). A substitution is "I don't want to buy X, buy Y instead" — a genuinely
   different product, confirmed per recipe, never silent. An alias is "X and Y are the same
   thing to my household" — no swap, no confirmation, no per-recipe record; it's applied
   silently, uniformly, and immediately to every recipe (past and future) at shopping-list
   time. See CLAUDE.md > Ingredient Aliases. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function groupByCanonical(items) {
    var groups = {};
    var order = [];
    (items || []).forEach(function (row) {
      if (!groups[row.canonical_name]) {
        groups[row.canonical_name] = [];
        order.push(row.canonical_name);
      }
      groups[row.canonical_name].push(row);
    });
    return order.map(function (name) {
      return { canonical_name: name, rows: groups[name] };
    });
  }

  function renderAliasRow(row, onChanged) {
    var wrap = el("div", "settings-row");
    wrap.appendChild(el("span", "muted", row.alias_name));

    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Stop grouping "' + row.alias_name + '" with "' + row.canonical_name + '"?')) {
        return;
      }
      api.settings.ingredientAliases
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(deleteBtn);
    wrap.appendChild(rowErr);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var aliasInput = el("input");
    aliasInput.type = "text";
    aliasInput.placeholder = "ingredient name, e.g. canola oil";
    aliasInput.className = "settings-name-input";

    var canonicalInput = el("input");
    canonicalInput.type = "text";
    canonicalInput.placeholder = "same shopping item as, e.g. vegetable oil";
    canonicalInput.className = "settings-name-input";

    var addBtn = el("button", "primary", "Group these");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var alias = aliasInput.value.trim();
      var canonical = canonicalInput.value.trim();
      if (!alias || !canonical) {
        rowErr.textContent = "Both names are required.";
        return;
      }
      api.settings.ingredientAliases
        .create({ alias_name: alias, canonical_name: canonical })
        .then(function () {
          aliasInput.value = "";
          canonicalInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [aliasInput, el("span", "muted", "="), canonicalInput, addBtn, rowErr].forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Ingredient groups"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Ingredients that are the same thing to you, shown as one line on the shopping list " +
          "— e.g. “canola oil” and “oil spray” grouped under “vegetable oil”. " +
          "This never changes a recipe's own ingredient list, and adding a group applies to " +
          "every existing recipe immediately, not just future ones."
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
      api.settings.ingredientAliases
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByCanonical(data.items);
          if (groups.length === 0) {
            listBody.appendChild(el("div", "muted", "No groups yet — add one below."));
          } else {
            groups.forEach(function (group) {
              listBody.appendChild(el("div", "sub-group-heading", group.canonical_name));
              group.rows.forEach(function (row) {
                listBody.appendChild(renderAliasRow(row, load));
              });
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load ingredient groups: " + err.message;
        });
    }

    load();
  }

  global.SettingsIngredientAliasesView = { renderCard: renderCard };
})(window);
