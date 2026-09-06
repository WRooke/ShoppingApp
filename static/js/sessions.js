/* Planning sessions view (#/plan) — session list + a session workspace where
   recipes are added, scaled and slotted into days. The ingredient-review /
   ad-hoc-swap / consolidated-summary screen lives in session-review.js (split
   per CLAUDE.md > Code Architecture & Maintainability > file size discipline).
   See CLAUDE.md > Build Phases > Phase 4 > Chunk 4.7. */

(function (global) {
  "use strict";

  var DAYS = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function daySelect(value, onChange) {
    var sel = el("select");
    for (var d = 0; d <= 7; d++) {
      var opt = el("option", null, d === 0 ? "— day —" : DAYS[d]);
      opt.value = d === 0 ? "" : String(d);
      if (String(value || "") === opt.value) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () {
      onChange(sel.value ? parseInt(sel.value, 10) : null);
    });
    return sel;
  }

  function servingsSelect(value, onChange) {
    var sel = el("select");
    for (var n = 1; n <= 12; n++) {
      var opt = el("option", null, n + (n === 1 ? " serving" : " servings"));
      opt.value = String(n);
      if (n === value) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () {
      onChange(parseInt(sel.value, 10));
    });
    return sel;
  }

  // --- session list --------------------------------------------------

  function renderList(root) {
    root.innerHTML = "";

    var actions = el("div", "log-controls");
    actions.style.marginBottom = "16px";
    var newBtn = el("button", "primary", "New session");
    newBtn.addEventListener("click", function () {
      api.sessions
        .create({})
        .then(function (s) {
          global.Router.navigate("plan", s.id);
        })
        .catch(function (err) {
          global.alert("Couldn't start a session: " + err.message);
        });
    });
    actions.appendChild(newBtn);
    root.appendChild(actions);

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Planning sessions"));
    var body = el("div");
    body.textContent = "Loading...";
    card.appendChild(body);
    root.appendChild(card);

    api.sessions
      .list()
      .then(function (data) {
        body.innerHTML = "";
        if (!data.items || data.items.length === 0) {
          body.appendChild(el("div", "muted", "No sessions yet — start one above."));
          return;
        }
        data.items.forEach(function (s) {
          var row = el("a", "recipe-row");
          row.href = "#/plan/" + s.id;
          var main = el("div", "recipe-row-main");
          main.appendChild(
            el("div", "recipe-row-name", s.label || "Session #" + s.id)
          );
          var bits = [
            s.slot_count + (s.slot_count === 1 ? " item" : " items"),
            s.status,
            new Date(s.created_at).toLocaleDateString(),
          ];
          main.appendChild(el("div", "recipe-row-meta muted", bits.join(" · ")));
          row.appendChild(main);
          body.appendChild(row);
        });
      })
      .catch(function (err) {
        body.textContent = "Couldn't load sessions: " + err.message;
      });
  }

  // --- session workspace -------------------------------------------

  function renderWorkspace(root, sessionId) {
    root.innerHTML = "";

    var back = el("a", "btn", "← All sessions");
    back.href = "#/plan";
    root.appendChild(back);

    var card = el("div", "card");
    card.textContent = "Loading...";
    root.appendChild(card);

    function load() {
      api.sessions
        .get(sessionId)
        .then(function (s) {
          renderWorkspaceCard(card, s, load);
        })
        .catch(function (err) {
          card.innerHTML = "";
          card.appendChild(
            el("div", "muted", "Couldn't load this session: " + err.message)
          );
        });
    }
    load();
  }

  function renderWorkspaceCard(card, session, reload) {
    card.innerHTML = "";

    var head = el("div", "detail-head-row");
    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.value = session.label || "";
    labelInput.placeholder = "Session name, e.g. Week of 14 Jul";
    labelInput.addEventListener("blur", function () {
      if (labelInput.value.trim() === (session.label || "")) return;
      api.sessions
        .update(session.id, { label: labelInput.value.trim() || null })
        .catch(function (err) {
          global.alert("Couldn't rename: " + err.message);
        });
    });
    head.appendChild(labelInput);
    card.appendChild(head);
    card.appendChild(el("div", "muted", "Status: " + session.status));

    // --- slots ---
    var slotsHeading = el("h2", null, "Recipes & days");
    slotsHeading.style.marginTop = "16px";
    card.appendChild(slotsHeading);

    var slots = session.recipes || [];
    if (slots.length === 0) {
      card.appendChild(el("div", "muted", "No recipes added yet."));
    }
    var slotList = el("div");
    card.appendChild(slotList);
    slots.forEach(function (slot, idx) {
      slotList.appendChild(renderSlotRow(session, slot, idx, slots.length, reload));
    });

    // --- add recipe / leftovers ---
    var addRow = el("div", "log-controls");
    addRow.style.marginTop = "12px";
    var addRecipeBtn = el("button", null, "+ Add recipe");
    var addLeftoversBtn = el("button", null, "+ Add leftovers day");
    addRow.appendChild(addRecipeBtn);
    addRow.appendChild(addLeftoversBtn);
    card.appendChild(addRow);

    var pickerSlot = el("div");
    card.appendChild(pickerSlot);

    addRecipeBtn.addEventListener("click", function () {
      renderRecipePicker(pickerSlot, session.id, reload);
    });
    addLeftoversBtn.addEventListener("click", function () {
      api.sessions
        .addLeftovers(session.id, {})
        .then(reload)
        .catch(function (err) {
          global.alert("Couldn't add leftovers: " + err.message);
        });
    });

    // --- review ---
    var reviewRow = el("div", "log-controls");
    reviewRow.style.marginTop = "20px";
    var reviewBtn = el("button", "primary", "Review ingredients & shopping list →");
    reviewBtn.disabled = slots.length === 0;
    reviewBtn.addEventListener("click", function () {
      var root = card.parentNode;
      global.SessionReviewView.mount(root, session.id);
    });
    reviewRow.appendChild(reviewBtn);
    card.appendChild(reviewRow);
  }

  function renderSlotRow(session, slot, idx, count, reload) {
    var row = el("div", "settings-row");

    var isLeftovers = slot.slot_type === "leftovers";
    var name = el("div", "recipe-row-name", isLeftovers ? "Leftovers" : slot.recipe_name || "Recipe #" + slot.recipe_id);
    name.style.flex = "2 1 140px";
    row.appendChild(name);

    if (!isLeftovers) {
      row.appendChild(
        servingsSelect(slot.scaled_servings, function (n) {
          api.sessions.updateSlot(session.id, slot.id, { scaled_servings: n }).catch(barf);
        })
      );
    }

    row.appendChild(
      daySelect(slot.day_of_week, function (d) {
        api.sessions.updateSlot(session.id, slot.id, { day_of_week: d }).catch(barf);
      })
    );

    var upBtn = el("button", null, "↑");
    upBtn.disabled = idx === 0;
    var downBtn = el("button", null, "↓");
    downBtn.disabled = idx === count - 1;
    upBtn.addEventListener("click", function () {
      reorderMove(session, idx, idx - 1, reload);
    });
    downBtn.addEventListener("click", function () {
      reorderMove(session, idx, idx + 1, reload);
    });
    row.appendChild(upBtn);
    row.appendChild(downBtn);

    var removeBtn = el("button", null, "Remove");
    removeBtn.addEventListener("click", function () {
      api.sessions.removeSlot(session.id, slot.id).then(reload).catch(barf);
    });
    row.appendChild(removeBtn);

    return row;

    function barf(err) {
      global.alert("Couldn't update: " + err.message);
    }
  }

  function reorderMove(session, from, to, reload) {
    var ids = (session.recipes || []).map(function (s) {
      return s.id;
    });
    if (to < 0 || to >= ids.length) return;
    var moved = ids.splice(from, 1)[0];
    ids.splice(to, 0, moved);
    api.sessions.reorder(session.id, ids).then(reload).catch(function (err) {
      global.alert("Couldn't reorder: " + err.message);
    });
  }

  function renderRecipePicker(slot, sessionId, reload) {
    slot.innerHTML = "";
    var box = el("div", "card");
    box.appendChild(el("h2", null, "Add a recipe"));
    var search = el("input");
    search.type = "text";
    search.placeholder = "Search the library...";
    box.appendChild(search);
    var results = el("div");
    results.style.marginTop = "8px";
    box.appendChild(results);
    slot.appendChild(box);

    function load() {
      api.recipes
        .list({ search: search.value, limit: 50 })
        .then(function (data) {
          results.innerHTML = "";
          if (!data.items.length) {
            results.appendChild(el("div", "muted", "No matches."));
            return;
          }
          data.items.forEach(function (r) {
            var b = el("button", null, r.name + "  (" + r.base_servings + " serv)");
            b.style.display = "block";
            b.style.marginBottom = "4px";
            b.addEventListener("click", function () {
              api.sessions
                .addRecipe(sessionId, { recipe_id: r.id })
                .then(function () {
                  slot.innerHTML = "";
                  reload();
                })
                .catch(function (err) {
                  global.alert("Couldn't add: " + err.message);
                });
            });
            results.appendChild(b);
          });
        })
        .catch(function (err) {
          results.textContent = "Couldn't search: " + err.message;
        });
    }
    var t = null;
    search.addEventListener("input", function () {
      if (t) global.clearTimeout(t);
      t = global.setTimeout(load, 200);
    });
    load();
  }

  // --- entry point -----------------------------------------------

  function mount(root, param) {
    if (param === "new") {
      root.innerHTML = "";
      root.appendChild(el("div", "muted", "Starting a session..."));
      api.sessions
        .create({})
        .then(function (s) {
          global.Router.navigate("plan", s.id);
        })
        .catch(function (err) {
          root.innerHTML = "";
          root.appendChild(el("div", "muted", "Couldn't start a session: " + err.message));
        });
    } else if (param) {
      renderWorkspace(root, param);
    } else {
      renderList(root);
    }
  }

  function unmount() {}

  global.SessionsView = { mount: mount, unmount: unmount };
})(window);
