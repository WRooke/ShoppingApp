/* Settings — "Staples" card (see CLAUDE.md > Build Phases > Phase 2 > Chunk 2.5). Split out
   of settings.js per CLAUDE.md > Code Architecture & Maintainability > file size discipline
   — settings.js was pushing well past 400 lines once the Chunk 6.4 index/Appearance/staples/
   product-units all landed in one file.

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

  function renderStapleRow(staple, listBody) {
    var row = el("div", "settings-row");

    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.value = staple.name;
    nameInput.className = "settings-name-input";

    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.value = staple.notes || "";
    notesInput.className = "settings-notes-input";

    var saveBtn = el("button", "btn-sm primary", "Save");
    var deleteBtn = el("button", "btn-sm", "Delete");
    var rowErr = el("span", "form-error");

    saveBtn.addEventListener("click", function () {
      rowErr.textContent = "";
      api.settings.staples
        .update(staple.id, {
          name: nameInput.value.trim(),
          notes: notesInput.value.trim() || null,
        })
        .then(function (updated) {
          staple.name = updated.name;
          staple.notes = updated.notes;
          // No rebuild needed — the inputs already show what was just saved.
        })
        .catch(function (err) {
          rowErr.textContent = err.message;
        });
    });

    global.SettingsRowActions.wireDelete(deleteBtn, {
      label: staple.name,
      row: row,
      doDelete: function () {
        return api.settings.staples.delete(staple.id);
      },
      recreate: function () {
        return api.settings.staples.create({ name: staple.name, notes: staple.notes });
      },
      onRestored: function (created) {
        listBody.appendChild(renderStapleRow(created, listBody));
      },
      onError: function (err) {
        rowErr.textContent = err.message;
      },
    });

    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr";
    grid.appendChild(miniField("Name", nameInput));
    grid.appendChild(miniField("Notes", notesInput));
    row.appendChild(grid);
    var actions = el("div", "log-controls");
    actions.style.marginTop = "6px";
    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(rowErr);
    row.appendChild(actions);
    return row;
  }

  function renderCard(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("settings"));
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Staples"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Assumed to already be on hand — only shown on the checklist when a recipe in the session needs them."
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
    nameInput.placeholder = "e.g. garlic";
    var notesInput = el("input");
    notesInput.type = "text";
    notesInput.placeholder = "optional";
    var addBtn = el("button", "btn-sm primary", "Add");
    var addErr = el("span", "form-error");
    var addGrid = el("div", "ing-grid");
    addGrid.style.gridTemplateColumns = "1fr 1fr";
    addGrid.appendChild(miniField("New staple name", nameInput));
    addGrid.appendChild(miniField("Notes", notesInput));
    var addWrap = el("div");
    addWrap.style.marginTop = "12px";
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
      if (!name) {
        addErr.textContent = "Name is required.";
        return;
      }
      api.settings.staples
        .create({ name: name, notes: notesInput.value.trim() || null })
        .then(function (created) {
          if (listBody.querySelector(".empty-state")) listBody.innerHTML = "";
          listBody.appendChild(renderStapleRow(created, listBody));
          nameInput.value = "";
          notesInput.value = "";
        })
        .catch(function (err) {
          addErr.textContent = err.message;
        });
    });

    api.settings.staples
      .list()
      .then(function (data) {
        listBody.innerHTML = "";
        var items = data.items || [];
        if (items.length === 0) {
          listBody.appendChild(el("div", "empty-state", "No staples yet."));
        } else {
          items.forEach(function (s) {
            listBody.appendChild(renderStapleRow(s, listBody));
          });
        }
      })
      .catch(function (err) {
        listBody.innerHTML = "";
        listBody.appendChild(el("div", "error-state", "Couldn't load staples: " + err.message));
      });
  }

  global.SettingsStaplesView = { renderCard: renderCard };
})(window);
