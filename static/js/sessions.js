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

  // Active/Past tabs (Phase 6 Chunk 6.6, kickoff decision #7) — previously this list showed
  // every session regardless of status forever, with no way to tell a finished one from a
  // current one at a glance. "Past" merges pushed+archived (two separate list() calls — the
  // backend's own status filter only takes one value — sorted by updated_at, which a push or
  // an archive both bump) and expands per-row to show its recipes.
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

    var tabs = el("div", "section-tabs");
    var activeTabBtn = el("button", null, "Active");
    var pastTabBtn = el("button", null, "Past");
    tabs.appendChild(activeTabBtn);
    tabs.appendChild(pastTabBtn);
    card.appendChild(tabs);

    var body = el("div");
    card.appendChild(body);
    root.appendChild(card);

    function skeletonLoading() {
      body.innerHTML = "";
      var skel = el("div", "skel-row");
      var skelLine = el("div", "skeleton skel-line");
      skelLine.style.width = "100%";
      skel.appendChild(skelLine);
      body.appendChild(skel);
    }

    function sessionRow(s) {
      var row = el("a", "recipe-row");
      row.href = "#/plan/" + s.id;
      var main = el("div", "recipe-row-main");
      main.appendChild(el("div", "recipe-row-name", s.label || "Session #" + s.id));
      var bits = [
        s.slot_count + (s.slot_count === 1 ? " item" : " items"),
        s.status,
        new Date(s.created_at).toLocaleDateString(),
      ];
      main.appendChild(el("div", "recipe-row-meta muted", bits.join(" · ")));
      row.appendChild(main);
      return row;
    }

    function loadActive() {
      skeletonLoading();
      api.sessions
        .list({ status: "active" })
        .then(function (data) {
          body.innerHTML = "";
          var items = data.items || [];
          if (!items.length) {
            body.appendChild(el("div", "empty-state", "No active sessions — start one above."));
            return;
          }
          items.forEach(function (s) {
            body.appendChild(sessionRow(s));
          });
        })
        .catch(function (err) {
          body.innerHTML = "";
          body.appendChild(el("div", "error-state", "Couldn't load sessions: " + err.message));
        });
    }

    function historyRow(s) {
      var row = el("div", "history-row");
      var headBtn = el("button", "history-head");
      headBtn.type = "button";
      var main = el("div", "main");
      main.appendChild(el("div", "name", s.label || "Session #" + s.id));
      main.appendChild(
        el("div", "meta", new Date(s.updated_at).toLocaleDateString())
      );
      headBtn.appendChild(main);
      headBtn.appendChild(el("span", "status-pill " + s.status, s.status));
      headBtn.appendChild(el("span", "chev", "›"));
      row.appendChild(headBtn);

      var recipesBody = el("div", "history-body");
      row.appendChild(recipesBody);

      var loaded = false;
      headBtn.addEventListener("click", function () {
        row.classList.toggle("open");
        if (!row.classList.contains("open") || loaded) return;
        loaded = true;
        recipesBody.appendChild(el("div", "muted", "Loading…"));
        // The list endpoint only carries slot_count, not the slots themselves — a full
        // GET /sessions/{id} is a cheap, on-demand fetch for the one row actually expanded,
        // rather than fattening every list() response with data most rows never need.
        api.sessions
          .get(s.id)
          .then(function (full) {
            recipesBody.innerHTML = "";
            var recipes = full.recipes || [];
            if (!recipes.length) {
              recipesBody.appendChild(el("div", "muted", "No recipes in this session."));
              return;
            }
            recipes.forEach(function (slot) {
              var line = el("div", "history-recipe");
              var isLeftovers = slot.slot_type === "leftovers";
              var name = isLeftovers
                ? el("span", null, "Leftovers")
                : el("a", null, slot.recipe_name || "Recipe #" + slot.recipe_id);
              if (!isLeftovers) name.href = "#/recipes/" + slot.recipe_id;
              line.appendChild(name);
              var dayBits = [slot.day_of_week ? DAYS[slot.day_of_week] : "—"];
              if (!isLeftovers && slot.scaled_servings) {
                dayBits.push(slot.scaled_servings + (slot.scaled_servings === 1 ? " serving" : " servings"));
              }
              line.appendChild(el("span", "day", dayBits.join(" · ")));
              recipesBody.appendChild(line);
            });
          })
          .catch(function (err) {
            recipesBody.innerHTML = "";
            recipesBody.appendChild(el("div", "error-state", "Couldn't load recipes: " + err.message));
          });
      });
      return row;
    }

    function loadPast() {
      skeletonLoading();
      Promise.all([api.sessions.list({ status: "pushed" }), api.sessions.list({ status: "archived" })])
        .then(function (results) {
          var items = (results[0].items || []).concat(results[1].items || []);
          items.sort(function (a, b) {
            return new Date(b.updated_at) - new Date(a.updated_at);
          });
          body.innerHTML = "";
          if (!items.length) {
            body.appendChild(el("div", "empty-state", "No past sessions yet."));
            return;
          }
          items.forEach(function (s) {
            body.appendChild(historyRow(s));
          });
        })
        .catch(function (err) {
          body.innerHTML = "";
          body.appendChild(el("div", "error-state", "Couldn't load past sessions: " + err.message));
        });
    }

    function setTab(tab) {
      activeTabBtn.setAttribute("aria-pressed", String(tab === "active"));
      pastTabBtn.setAttribute("aria-pressed", String(tab === "past"));
      if (tab === "active") loadActive();
      else loadPast();
    }
    activeTabBtn.addEventListener("click", function () {
      setTab("active");
    });
    pastTabBtn.addEventListener("click", function () {
      setTab("past");
    });

    setTab("active");
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

    // Archive (Phase 6 Chunk 6.6) — the endpoint already existed (Phase 4 Chunk 4.4) but
    // nothing in the UI ever called it, so there was no way to remove a session from the
    // active list at all. Stays on this same screen after archiving (reload() re-renders it
    // showing "Status: archived") rather than navigating away, so the Undo toast doesn't
    // need the deferred-navigate dance recipe deletion uses elsewhere.
    if (session.status !== "archived") {
      var wsActions = el("div", "workspace-actions");
      var archiveBtn = el("button", "btn-sm archive-btn", "Archive");
      archiveBtn.addEventListener("click", function () {
        archiveBtn.disabled = true;
        api.sessions
          .archive(session.id)
          .then(function () {
            global.Toast.show("Session archived", {
              actionLabel: "Undo",
              onAction: function () {
                api.sessions
                  .update(session.id, { status: "active" })
                  .then(reload)
                  .catch(function (err) {
                    global.alert("Couldn't undo: " + err.message);
                  });
              },
            });
            reload();
          })
          .catch(function (err) {
            archiveBtn.disabled = false;
            global.alert("Couldn't archive: " + err.message);
          });
      });
      wsActions.appendChild(archiveBtn);
      head.appendChild(wsActions);
    }
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
