/* Settings — "Saved ingredient swaps" card (Phase 3.9 M4). Was a card of global
   auto-applying rules with a default toggle; now it's a pure quick-pick library —
   a saved swap NEVER applies itself, it only pre-fills the per-recipe confirm UI
   (capture review, recipe editor). See CLAUDE.md > AI Provider Migration >
   Ingredient Substitution Flagging.

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM removal on delete instead of a full list
   rebuild (the scroll-position bug). Adding a new swap still rebuilds the whole list —
   correctly inserting a new group heading in the right place is enough more machinery that
   it wasn't worth it for an action that happens at the bottom of the page anyway, where a
   rebuild doesn't move your scroll position away from what you were looking at. */

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

  /* M8 — the optional "N unit ≈ M unit" equivalence pair on a saved swap (CLAUDE.md > AI
     Provider Migration > Ingredient Substitution Flagging > Quantity/unit transform). Four
     small labelled inputs; values() returns all four as numbers/strings-or-null (blank ->
     null), so a row can be cleared by emptying them and saving. The server enforces
     all-or-none. */
  function pairFields(row) {
    row = row || {};
    function num(v) {
      var n = el("input");
      n.type = "number";
      n.step = "any";
      n.inputMode = "decimal";
      n.className = "ingredient-qty-input";
      n.value = v != null ? v : "";
      return n;
    }
    function txt(v) {
      var t = el("input");
      t.type = "text";
      t.className = "ingredient-unit-input";
      t.value = v || "";
      return t;
    }
    var oqty = num(row.original_qty);
    var ounit = txt(row.original_unit);
    var sqty = num(row.substitute_qty);
    var sunit = txt(row.substitute_unit);
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr 1fr 1fr";
    grid.appendChild(miniField("Original amount", oqty));
    grid.appendChild(miniField("Original unit", ounit));
    grid.appendChild(miniField("Substitute amount", sqty));
    grid.appendChild(miniField("Substitute unit", sunit));
    return {
      grid: grid,
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

  function renderSubRow(row, reload) {
    var wrap = el("div", "settings-row");

    var subInput = el("input");
    subInput.type = "text";
    subInput.value = row.substitute_name;
    subInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.value = row.note || "";
    noteInput.className = "settings-notes-input";

    var pair = pairFields(row);

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-sm", "Delete");
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
        .then(function (updated) {
          row.substitute_name = updated.substitute_name;
          row.note = updated.note;
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.original_name + " → " + row.substitute_name,
      row: wrap,
      doDelete: function () {
        return api.settings.substitutions.delete(row.id);
      },
      recreate: function () {
        return api.settings.substitutions.create({
          original_name: row.original_name,
          substitute_name: row.substitute_name,
          note: row.note,
          original_qty: row.original_qty,
          original_unit: row.original_unit,
          substitute_qty: row.substitute_qty,
          substitute_unit: row.substitute_unit,
        });
      },
      // A restored swap's group may no longer exist in the DOM (its last row could have
      // been deleted alongside it in the same session) — simplest correct fix is to redraw
      // the whole card, same as Add already does, rather than duplicate group-placement
      // logic here for what's a rare (undo-of-the-last-row-in-a-group) case.
      onRestored: function () {
        reload();
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    wrap.appendChild(el("span", "muted", "→"));
    wrap.appendChild(miniField("Buy instead", subInput));
    wrap.appendChild(pair.grid);
    wrap.appendChild(miniField("Note", noteInput));
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var origInput = el("input");
    origInput.type = "text";
    origInput.placeholder = "e.g. bulgarian feta";
    origInput.className = "settings-name-input";

    var subInput = el("input");
    subInput.type = "text";
    subInput.placeholder = "e.g. regular feta";
    subInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "optional";
    noteInput.className = "settings-notes-input";

    var pair = pairFields();
    var addBtn = el("button", "btn-sm primary", "Save swap");
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
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(miniField("Hard-to-find ingredient", origInput));
    wrap.appendChild(el("span", "muted", "→"));
    wrap.appendChild(miniField("Buy instead", subInput));
    wrap.appendChild(pair.grid);
    wrap.appendChild(miniField("Note", noteInput));
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(addBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
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
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    listBody.appendChild(skel);
    card.appendChild(listBody);
    var addSlot = el("div");
    addSlot.style.marginTop = "12px";
    card.appendChild(addSlot);
    root.appendChild(card);

    function load() {
      api.settings.substitutions
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var groups = groupByOriginal(data.items);
          if (groups.length === 0) {
            listBody.appendChild(
              el("div", "empty-state", "No saved swaps yet — save one while reviewing a recipe.")
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
          listBody.innerHTML = "";
          listBody.appendChild(el("div", "error-state", "Couldn't load saved swaps: " + err.message));
        });
    }

    load();
  }

  global.SettingsSubstitutionsView = { renderCard: renderCard };
})(window);
