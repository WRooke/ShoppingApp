/* Settings — "The usuals" card (Phase 5 Chunk 5.4). Recurring non-recipe household items
   (laundry powder, dish soap) with a day-based cadence. Distinct from staples: these have no
   recipe link and surface on the checklist only when due. Managed here; seeded empty.
   See CLAUDE.md > Checklist Screen Logic > "The usuals". */

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

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = row.name;
    nameInput.className = "settings-name-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = row.notes || "";
    notesInput.placeholder = "note (optional)";
    notesInput.className = "settings-notes-input";

    var cadenceInput = el("input");
    cadenceInput.type = "number";
    cadenceInput.min = "1";
    cadenceInput.value = row.cadence_days;
    cadenceInput.className = "ingredient-qty-input";
    cadenceInput.title = "buy roughly every N days";

    var cadenceLabel = el("span", "muted", " days");
    var dueTag = el(
      "span",
      row.is_due ? "sub-group-heading" : "muted",
      row.is_due ? "due now" : "not due"
    );

    var saveBtn = el("button", null, "Save");
    var deleteBtn = el("button", null, "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var cadence = parseInt(cadenceInput.value, 10);
      if (isNaN(cadence) || cadence < 1) {
        rowErr.textContent = "Cadence must be a whole number of days (1 or more).";
        return;
      }
      api.settings.usuals
        .update(row.id, {
          name: nameInput.value.trim(),
          notes: notesInput.value.trim() || null,
          cadence_days: cadence,
        })
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    deleteBtn.addEventListener("click", function () {
      if (!global.confirm('Remove "' + row.name + '" from the usuals?')) return;
      api.settings.usuals
        .delete(row.id)
        .then(onChanged)
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, notesInput, cadenceInput, cadenceLabel, dueTag, saveBtn, deleteBtn, rowErr].forEach(
      function (n) {
        wrap.appendChild(n);
      }
    );
    return wrap;
  }

  function renderAddRow(onAdded) {
    var wrap = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "recurring item, e.g. laundry powder";
    nameInput.className = "settings-name-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "note (optional)";
    notesInput.className = "settings-notes-input";

    var cadenceInput = el("input");
    cadenceInput.type = "number";
    cadenceInput.min = "1";
    cadenceInput.placeholder = "days";
    cadenceInput.className = "ingredient-qty-input";

    var addBtn = el("button", "primary", "Add usual");
    var rowErr = el("span", "form-error");

    addBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      var name = nameInput.value.trim();
      var cadence = parseInt(cadenceInput.value, 10);
      if (!name || isNaN(cadence) || cadence < 1) {
        rowErr.textContent = "Name and a cadence in days (1 or more) are required.";
        return;
      }
      api.settings.usuals
        .create({ name: name, notes: notesInput.value.trim() || null, cadence_days: cadence })
        .then(function () {
          nameInput.value = "";
          notesInput.value = "";
          cadenceInput.value = "";
          onAdded();
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    [nameInput, notesInput, cadenceInput, el("span", "muted", " days"), addBtn, rowErr].forEach(
      function (n) {
        wrap.appendChild(n);
      }
    );
    return wrap;
  }

  function renderCard(root) {
    var card = el("div", "card");
    card.appendChild(el("h2", null, "The usuals"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Household items you buy on a schedule regardless of what you're cooking. They appear on the checklist as their own group only when they're due."
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
      api.settings.usuals
        .list()
        .then(function (data) {
          listBody.innerHTML = "";
          addSlot.innerHTML = "";
          var items = data.items || [];
          if (items.length === 0) {
            listBody.appendChild(el("div", "muted", "No usuals yet — add one below."));
          } else {
            items.forEach(function (row) {
              listBody.appendChild(renderRow(row, load));
            });
          }
          addSlot.appendChild(renderAddRow(load));
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load the usuals: " + err.message;
        });
    }

    load();
  }

  global.SettingsUsualsView = { renderCard: renderCard };
})(window);
