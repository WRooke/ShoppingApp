/* Planning sessions view (#/plan) — session list + a session workspace where
   recipes are added, scaled and slotted into days. The ingredient-review /
   ad-hoc-swap / consolidated-summary screen lives in session-review.js (split
   per CLAUDE.md > Code Architecture & Maintainability > file size discipline).
   See CLAUDE.md > Build Phases > Phase 4 > Chunk 4.7. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
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

    // --- slots: a 7-day grid, not a flat list (Phase 6 Chunk 6.5 — see session-week.js) ---
    var slotsHeadingRow = el("div", "detail-head-row");
    slotsHeadingRow.style.marginTop = "16px";
    slotsHeadingRow.appendChild(el("h2", null, "Recipes & days"));
    card.appendChild(slotsHeadingRow);

    var slots = session.recipes || [];
    if (slots.length === 0) {
      card.appendChild(el("div", "empty-state", "No recipes added yet."));
    }

    var weekSection = el("div");
    card.appendChild(weekSection);
    global.SessionWeek.render(weekSection, session, reload);

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
