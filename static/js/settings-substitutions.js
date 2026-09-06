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

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      api.settings.substitutions
        .update(row.id, {
          substitute_name: subInput.value.trim(),
          note: noteInput.value.trim() || null,
        })
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
    [subInput, noteInput, saveBtn, deleteBtn, rowErr].forEach(function (n) {
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
      api.settings.substitutions
        .create({
          original_name: original,
          substitute_name: substitute,
          note: noteInput.value.trim() || null,
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

    [origInput, el("span", "muted", "→"), subInput, noteInput, addBtn, rowErr].forEach(function (n) {
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
