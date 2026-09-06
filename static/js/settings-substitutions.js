/* Settings — "Ingredient substitutions" card (Phase 4, Chunk 4.5). Split from
   settings.js per CLAUDE.md > Code Architecture & Maintainability > file size
   discipline (own sub-feature, own file). Management only: rules are *created*
   from the planning flow (Chunk 4.7); here they're viewed, re-defaulted, edited
   and removed. See CLAUDE.md > Ingredient Substitution. */

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

    var defaultBox = el("input");
    defaultBox.type = "checkbox";
    defaultBox.checked = !!row.is_default;
    defaultBox.title = "Auto-apply this substitute";

    var subInput = el("input");
    subInput.type = "text";
    subInput.value = row.substitute_name;
    subInput.className = "settings-name-input";

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    defaultBox.addEventListener("change", function () {
      rowErr.textContent = "";
      api.settings.substitutions
        .update(row.id, { is_default: defaultBox.checked })
        .then(onChanged)
        .catch(function (err) {
          defaultBox.checked = !!row.is_default;
          rowErr.textContent = err.message;
        });
    });

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      api.settings.substitutions
        .update(row.id, { substitute_name: subInput.value.trim() })
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Remove "' + row.original_name + '" → "' + row.substitute_name + '"?')) {
        return;
      }
      api.settings.substitutions
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    wrap.appendChild(el("span", "muted", "use"));
    [defaultBox, subInput, saveBtn, deleteBtn, rowErr].forEach(function (n) {
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

    var defaultBox = el("input");
    defaultBox.type = "checkbox";
    defaultBox.title = "Auto-apply (first rule for an ingredient is always the default)";

    var addBtn = el("button", "primary", "Add");
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
          is_default: defaultBox.checked,
        })
        .then(function () {
          origInput.value = "";
          subInput.value = "";
          defaultBox.checked = false;
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [origInput, el("span", "muted", "→"), subInput, defaultBox, addBtn, rowErr].forEach(function (n) {
      wrap.appendChild(n);
    });
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Ingredient substitutions"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Swap a hard-to-find ingredient for one you can actually buy. A ticked substitute is applied automatically when planning; untick to keep it as a quick pick only."
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
              el("div", "muted", "No substitution rules yet — make one while planning a session.")
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
          listBody.textContent = "Couldn't load substitutions: " + err.message;
        });
    }

    load();
  }

  global.SettingsSubstitutionsView = { renderCard: renderCard };
})(window);
