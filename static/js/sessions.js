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

  // Chunk 6.3 kickoff decision #12 — adding a recipe/leftovers slot suggests the next day
  // not already used in this session, instead of leaving the dropdown blank. Undated slots
  // (day_of_week null) don't count as "using" a day; null itself means "every day is taken"
  // or there simply are no slots yet to avoid conflicting with, either way a reasonable
  // fallback to leave blank rather than force.
  function nextEmptyDay(slots) {
    var used = {};
    (slots || []).forEach(function (s) {
      if (s.day_of_week) used[s.day_of_week] = true;
    });
    for (var d = 1; d <= 7; d++) {
      if (!used[d]) return d;
    }
    return null;
  }

  // Shared Plan -> Review -> Checklist -> Push indicator (Chunk 6.3). The last two stay
  // inactive placeholders here — checklist.js's own matching indicator is Chunk 6.3b's job.
  function stepIndicator(activeLabel) {
    var labels = ["Plan", "Review", "Checklist", "Push"];
    var wrap = el("div", "step-list");
    labels.forEach(function (label, i) {
      wrap.appendChild(el("span", label === activeLabel ? "on" : null, label));
      if (i < labels.length - 1) wrap.appendChild(el("span", "sep", "→"));
    });
    return wrap;
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
    root.appendChild(global.BackLink.render("plan"));
    root.appendChild(stepIndicator("Plan"));

    var card = el("div", "card");
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skelLine.style.height = "60px";
    skel.appendChild(skelLine);
    card.appendChild(skel);
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
    var slotsHeadingRow = el("div", "detail-head-row");
    slotsHeadingRow.style.marginTop = "16px";
    slotsHeadingRow.appendChild(el("h2", null, "Recipes & days"));
    card.appendChild(slotsHeadingRow);

    var slots = session.recipes || [];
    if (slots.length === 0) {
      card.appendChild(el("div", "empty-state", "No recipes added yet."));
    }
    if (slots.length > 1) {
      // Requested 2026-09-10 hand-testing: assigning a day (the dropdown per row, below)
      // doesn't itself move a slot's position — a recipe added last but set to "Mon" still
      // sits at the bottom until reordered by hand with the up/down arrows. This sorts the
      // list to match the assigned days in one action, using the existing slot-order
      // endpoint (no backend change). Undated slots keep their current relative order and
      // sort after every dated one.
      var reorgBtn = el("button", null, "Reorganise by day");
      reorgBtn.addEventListener("click", function () {
        var withIdx = slots.map(function (slot, idx) { return { slot: slot, idx: idx }; });
        withIdx.sort(function (a, b) {
          var da = a.slot.day_of_week || 8; // undated -> after every real day (1-7)
          var db = b.slot.day_of_week || 8;
          return da !== db ? da - db : a.idx - b.idx; // stable: ties keep current order
        });
        var ids = withIdx.map(function (w) { return w.slot.id; });
        api.sessions.reorder(session.id, ids).then(reload).catch(function (err) {
          global.alert("Couldn't reorganise: " + err.message);
        });
      });
      slotsHeadingRow.appendChild(reorgBtn);
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
      global.SessionRecipePicker.render(pickerSlot, session.id, nextEmptyDay(slots), reload);
    });
    addLeftoversBtn.addEventListener("click", function () {
      api.sessions
        .addLeftovers(session.id, { day_of_week: nextEmptyDay(slots) })
        .then(reload)
        .catch(function (err) {
          global.alert("Couldn't add leftovers: " + err.message);
        });
    });

    // --- review --- (sticky — kickoff decision #12, the primary forward action on a
    // screen that can get long once several recipes are slotted in)
    var reviewRow = el("div", "log-controls sticky-actions");
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
    // Chunk 6.3 kickoff decision #9 — a slot's recipe name links to its own page, matching
    // what session-review.js's "which recipe" breakdown already does further down the flow.
    var name = isLeftovers
      ? el("div", "recipe-row-name", "Leftovers")
      : el("a", "recipe-row-name", slot.recipe_name || "Recipe #" + slot.recipe_id);
    if (!isLeftovers) name.href = "#/recipes/" + slot.recipe_id;
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
      removeBtn.disabled = true;
      var snapshot = {
        slot_type: slot.slot_type,
        recipe_id: slot.recipe_id,
        day_of_week: slot.day_of_week,
        scaled_servings: slot.scaled_servings,
      };
      var label = isLeftovers ? "Leftovers" : slot.recipe_name || "Recipe #" + slot.recipe_id;
      api.sessions
        .removeSlot(session.id, slot.id)
        .then(function () {
          global.Toast.show('Removed "' + label + '"', {
            actionLabel: "Undo",
            onAction: function () {
              // removeSlot has no undo of its own — re-add from the snapshot, then a
              // follow-up update for the day/servings addRecipe/addLeftovers' own create
              // payload already covers (day_of_week), or doesn't (scaled_servings on an
              // existing recipe slot needs its own call once the id is known).
              var re =
                snapshot.slot_type === "leftovers"
                  ? api.sessions.addLeftovers(session.id, { day_of_week: snapshot.day_of_week })
                  : api.sessions.addRecipe(session.id, {
                      recipe_id: snapshot.recipe_id,
                      day_of_week: snapshot.day_of_week,
                    });
              re.then(function (created) {
                if (snapshot.slot_type === "leftovers" || !snapshot.scaled_servings) {
                  return null;
                }
                return api.sessions.updateSlot(session.id, created.id, {
                  scaled_servings: snapshot.scaled_servings,
                });
              })
                .then(reload)
                .catch(function (err) {
                  global.alert("Couldn't undo: " + err.message);
                });
            },
          });
          reload();
        })
        .catch(function (err) {
          removeBtn.disabled = false;
          barf(err);
        });
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
