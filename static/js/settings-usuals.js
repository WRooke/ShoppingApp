/* Settings — "The usuals" card (Phase 5 Chunk 5.4). Recurring non-recipe household items
   (laundry powder, dish soap) with a day-based cadence — no recipe link, surface on the
   checklist only when due. Managed here; seeded empty.
   See CLAUDE.md > Checklist Screen Logic > "The usuals".

   Phase 6 Chunk 6.4: labelled fields (was bare placeholders), the shared Undo toast on
   delete instead of confirm(), and in-place DOM updates instead of a full list rebuild on
   every Save/Add/Delete (the scroll-position bug). */

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

  function renderRow(row, listBody) {
    var wrap = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = row.name;
    nameInput.className = "settings-name-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = row.notes || "";
    notesInput.className = "settings-notes-input";

    var cadenceInput = el("input");
    cadenceInput.type = "number";
    cadenceInput.min = "1";
    cadenceInput.inputMode = "numeric";
    cadenceInput.value = row.cadence_days;
    cadenceInput.className = "ingredient-qty-input";

    var dueTag = el(
      "span",
      row.is_due ? "sub-group-heading" : "muted",
      row.is_due ? "due now" : "not due"
    );

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-sm", "Delete");
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
        .then(function (updated) {
          row.name = updated.name;
          row.notes = updated.notes;
          row.cadence_days = updated.cadence_days;
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: row.name,
      row: wrap,
      doDelete: function () {
        return api.settings.usuals.delete(row.id);
      },
      recreate: function () {
        return api.settings.usuals.create({
          name: row.name,
          notes: row.notes,
          cadence_days: row.cadence_days,
        });
      },
      onRestored: function (created) {
        listBody.appendChild(renderRow(created, listBody));
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    var grid = el("div", "ing-grid");
    grid.appendChild(miniField("Item name", nameInput));
    grid.appendChild(miniField("Every N days", cadenceInput));
    grid.appendChild(miniField("Notes", notesInput));
    wrap.appendChild(grid);
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(dueTag);
    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(rowErr);
    wrap.appendChild(actions);
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
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    listBody.appendChild(skel);
    card.appendChild(listBody);

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. laundry powder";
    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "optional";
    var cadenceInput = el("input");
    cadenceInput.type = "number";
    cadenceInput.min = "1";
    cadenceInput.inputMode = "numeric";
    cadenceInput.placeholder = "e.g. 21";
    var addBtn = el("button", "btn-sm primary", "Add usual");
    var addErr = el("span", "form-error");

    var addWrap = el("div");
    addWrap.style.marginTop = "12px";
    var addGrid = el("div", "ing-grid");
    addGrid.appendChild(miniField("Item name", nameInput));
    addGrid.appendChild(miniField("Every N days", cadenceInput));
    addGrid.appendChild(miniField("Notes", notesInput));
    addWrap.appendChild(addGrid);
    var addActions = el("div", "log-controls");
    addActions.style.marginTop = "6px";
    addActions.appendChild(addBtn);
    addActions.appendChild(addErr);
    addWrap.appendChild(addActions);
    card.appendChild(addWrap);
    root.appendChild(card);

    addBtn.addEventListener("click", function () {
      addErr.textContent = "";
      var name = nameInput.value.trim();
      var cadence = parseInt(cadenceInput.value, 10);
      if (!name || isNaN(cadence) || cadence < 1) {
        addErr.textContent = "Name and a cadence in days (1 or more) are required.";
        return;
      }
      api.settings.usuals
        .create({ name: name, notes: notesInput.value.trim() || null, cadence_days: cadence })
        .then(function (created) {
          if (listBody.querySelector(".empty-state")) listBody.innerHTML = "";
          listBody.appendChild(renderRow(created, listBody));
          nameInput.value = "";
          notesInput.value = "";
          cadenceInput.value = "";
        })
        .catch(function (err) {
          addErr.textContent = err.message;
        });
    });

    api.settings.usuals
      .list()
      .then(function (data) {
        listBody.innerHTML = "";
        var items = data.items || [];
        if (items.length === 0) {
          listBody.appendChild(el("div", "empty-state", "No usuals yet — add one below."));
        } else {
          items.forEach(function (row) {
            listBody.appendChild(renderRow(row, listBody));
          });
        }
      })
      .catch(function (err) {
        listBody.innerHTML = "";
        listBody.appendChild(el("div", "error-state", "Couldn't load the usuals: " + err.message));
      });
  }

  global.SettingsUsualsView = { renderCard: renderCard };
})(window);
