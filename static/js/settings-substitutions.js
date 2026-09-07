/* Settings — "Saved ingredient swaps" card (Phase 3.9 M4). Was a card of global
   auto-applying rules with a default toggle; now it's a pure quick-pick library —
   a saved swap NEVER applies itself, it only pre-fills the per-recipe confirm UI
   (capture review, recipe editor). See CLAUDE.md > AI Provider Migration >
   Ingredient Substitution Flagging. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  /* M8 — the optional "N unit ≈ M unit" equivalence pair on a saved swap (CLAUDE.md > AI
     Provider Migration > Ingredient Substitution Flagging > Quantity/unit transform). Four
     small inputs; values() returns all four as numbers/strings-or-null (blank -> null), so a
     row can be cleared by emptying them and saving. The server enforces all-or-none. */
  function pairInputs(row) {
    row = row || {};
    function num(v) {
      var n = el("input");
      n.type = "number";
      n.step = "any";
      n.className = "ingredient-qty-input";
      n.value = v != null ? v : "";
      return n;
    }
    function txt(v, ph) {
      var t = el("input");
      t.type = "text";
      t.className = "ingredient-unit-input";
      t.placeholder = ph;
      t.value = v || "";
      return t;
    }
    var oqty = num(row.original_qty);
    oqty.placeholder = "amt";
    var ounit = txt(row.original_unit, "unit");
    var sqty = num(row.substitute_qty);
    sqty.placeholder = "amt";
    var sunit = txt(row.substitute_unit, "unit");
    return {
      nodes: [oqty, ounit, el("span", "muted", "≈"), sqty, sunit],
      values: function () {
        var oq = parseFloat(oqty.value);
        var sq = parseFloat(sqty.value);
        return {
          original_qty: isNaN(oq) ? null : oq,
          original_unit: ounit.value.trim() || null,
          substitute_qty: isNaN(sq) ? null : sq,
          substitute_unit: sunit.value.trim() || null,
        };
      },
    };
  }

  function groupByOriginal(items) {
    var groups = {};
    var order = [];
    (items || []).forEach(function (row) {
      if (!groups[row.original_name]) {
        groups[row.original_name] = [];
        order.push(row.original_name);
      }
      groups[row.original_name].push(row);
    });
    return order.map(function (name) {
      return { original_name: name, rows: groups[name] };
    });
  }

  function renderSubRow(row, onChanged) {
    var wrap = el("div", "settings-row");

    var subInput = el("input");
    subInput.type = "text";
    subInput.value = row.substitute_name;
    subInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.value = row.note || "";
    noteInput.placeholder = "note (why / how)";
    noteInput.className = "settings-notes-input";

    var pair = pairInputs(row);

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var payload = {
        substitute_name: subInput.value.trim(),
        note: noteInput.value.trim() || null,
      };
      var p = pair.values();
      payload.original_qty = p.original_qty;
      payload.original_unit = p.original_unit;
      payload.substitute_qty = p.substitute_qty;
      payload.substitute_unit = p.substitute_unit;
      api.settings.substitutions
        .update(row.id, payload)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Forget the swap "' + row.original_name + '" → "' + row.substitute_name + '"?')) {
        return;
      }
      api.settings.substitutions
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(el("span", "muted", "→"));
    [subInput, noteInput].concat(pair.nodes).concat([saveBtn, deleteBtn, rowErr]).forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var origInput = el("input");
    origInput.type = "text";
    origInput.placeholder = "hard-to-find ingredient";
    origInput.className = "settings-name-input";

    var subInput = el("input");
    subInput.type = "text";
    subInput.placeholder = "buy this instead";
    subInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "note (optional)";
    noteInput.className = "settings-notes-input";

    var pair = pairInputs();
    var addBtn = el("button", "primary", "Save swap");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var original = origInput.value.trim();
      var substitute = subInput.value.trim();
      if (!original || !substitute) {
        rowErr.textContent = "Both ingredient names are required.";
        return;
      }
      var p = pair.values();
      api.settings.substitutions
        .create({
          original_name: original,
          substitute_name: substitute,
          note: noteInput.value.trim() || null,
          original_qty: p.original_qty,
          original_unit: p.original_unit,
          substitute_qty: p.substitute_qty,
          substitute_unit: p.substitute_unit,
        })
        .then(function () {
          origInput.value = "";
          subInput.value = "";
          noteInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [origInput, el("span", "muted", "→"), subInput, noteInput]
      .concat(pair.nodes)
      .concat([addBtn, rowErr])
      .forEach(function (n) {
        wrap.appendChild(n);
      });
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Saved ingredient swaps"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Swaps you've saved for hard-to-find ingredients. These never apply on their own — they're offered as a quick pick when you review a recipe that uses that ingredient."
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
      api.settings.substitutions
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByOriginal(data.items);
          if (groups.length === 0) {
            listBody.appendChild(
              el("div", "muted", "No saved swaps yet — save one while reviewing a recipe.")
            );
          } else {
            groups.forEach(function (group) {
              listBody.appendChild(el("div", "sub-group-heading", group.original_name));
              group.rows.forEach(function (row) {
                listBody.appendChild(renderSubRow(row, load));
              });
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load saved swaps: " + err.message;
        });
    }

    load();
  }

  global.SettingsSubstitutionsView = { renderCard: renderCard };
})(window);
