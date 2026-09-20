/* Session workspace — the 7-day grid + tap-to-assign (Phase 6 Chunk 6.5). Split out of
   sessions.js per CLAUDE.md > Code Architecture & Maintainability > file size discipline,
   matching this file family's existing self-contained-feature-file precedent
   (session-recipe-picker.js, checklist-push.js).

   A strict 7-column grid didn't fit at phone width (~400px, per this chunk's own mockup
   pass), so this is a vertically-stacked "day sections" layout instead — one of the
   fallbacks CLAUDE.md's own chunk description explicitly allowed. Tap-to-assign (kickoff
   decision #10 — drag-and-drop rejected as unreliable under touch at this width): tap a
   slot's move button, then tap a day section to move it there. The whole highlighted day
   card is the tap target, not just its header (2026-09-20 mockup feedback — the highlight
   has to match what's actually tappable, or tapping the highlighted area does nothing and
   reads as broken). day_of_week itself is unchanged (Phase 4 Chunk 4.4) — this is a visual
   layer only, no data-model change. */

(function (global) {
  "use strict";

  var DAYS = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
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

  // container: an empty element to render into. session: the full session object (needs
  // .id and .recipes). reload: sessions.js's own reload() — re-fetches and re-renders the
  // whole workspace card, which this module relies on after every mutation rather than
  // patching its own DOM in place (a move/add/remove already needs a fresh slot list from
  // the server, so there's no cheaper correct option here).
  function render(container, session, reload) {
    var slots = session.recipes || [];

    // Tap-to-assign state. null = not currently moving anything. Reset on every render()
    // call — reload() always rebuilds the whole workspace card from scratch, so this never
    // survives a server round-trip mid-move, which is fine: a move IS a server round-trip.
    var movingId = null;

    var moveBanner = el("div", "move-banner");
    moveBanner.hidden = true;
    container.appendChild(moveBanner);

    var weekWrap = el("div", "week");
    container.appendChild(weekWrap);

    function startMove(slot) {
      movingId = slot.id;
      var label = slot.slot_type === "leftovers" ? "Leftovers" : (slot.recipe_name || "Recipe #" + slot.recipe_id);
      moveBanner.innerHTML = "";
      moveBanner.hidden = false;
      moveBanner.appendChild(el("span", "lbl", "Moving “" + label + "” — tap a day"));
      var cancelBtn = el("button", null, "Cancel");
      cancelBtn.addEventListener("click", cancelMove);
      moveBanner.appendChild(cancelBtn);
      renderWeek();
    }

    function cancelMove() {
      movingId = null;
      moveBanner.hidden = true;
      renderWeek();
    }

    function finishMove(dayOfWeek) {
      var slotId = movingId;
      movingId = null;
      moveBanner.hidden = true;
      api.sessions
        .updateSlot(session.id, slotId, { day_of_week: dayOfWeek })
        .then(reload)
        .catch(function (err) {
          global.alert("Couldn't move: " + err.message);
          renderWeek();
        });
    }

    function renderWeek() {
      weekWrap.innerHTML = "";
      weekWrap.classList.toggle("moving", !!movingId);
      var unassigned = slots.filter(function (s) { return !s.day_of_week; });
      // Shown whenever it's non-empty, the session has no slots at all, OR a move is in
      // progress — a move needs Unassigned available as a target even when every slot
      // currently has a day (otherwise there'd be no way to un-schedule one at all). Found
      // via tests/frontend's own day-clear regression test failing against this exact gap.
      if (unassigned.length || slots.length === 0 || movingId) {
        weekWrap.appendChild(daySection(null, "Unassigned", unassigned, true));
      }
      for (var d = 1; d <= 7; d++) {
        var daySlots = slots.filter(function (s) { return s.day_of_week === d; });
        weekWrap.appendChild(daySection(d, DAYS[d], daySlots, false));
      }
    }

    function daySection(dayNum, dayLabel, daySlots, isUnassigned) {
      var isSource = !!movingId && daySlots.some(function (s) { return s.id === movingId; });
      var sec = el("div", "day-section" + (isUnassigned ? " unassigned" : "") + (isSource ? " picking-source" : ""));

      var headEl = el("div", "day-head");
      var left = el("span");
      if (isUnassigned) left.textContent = "Unassigned";
      else left.appendChild(el("span", "dow", dayLabel));
      headEl.appendChild(left);
      headEl.appendChild(
        el("span", "count", daySlots.length ? daySlots.length + " item" + (daySlots.length === 1 ? "" : "s") : "")
      );
      sec.appendChild(headEl);

      if (movingId && !isSource) {
        sec.addEventListener("click", function () {
          finishMove(isUnassigned ? null : dayNum);
        });
      }

      if (!daySlots.length) {
        sec.appendChild(el("div", "day-empty", isUnassigned ? "Nothing unassigned." : "Nothing yet."));
      } else {
        var body = el("div", "day-slots");
        daySlots.forEach(function (slot) {
          body.appendChild(slotRow(slot));
        });
        sec.appendChild(body);
      }
      return sec;
    }

    // Two-line row (2026-09-20 mockup feedback: the full recipe name was getting
    // ellipsis-truncated crammed alongside servings/move/remove on one line at phone width).
    // Line 1 is the name alone; line 2 is every control.
    function slotRow(slot) {
      var row = el("div", "slot-row" + (movingId === slot.id ? " picked" : ""));
      var isLeftovers = slot.slot_type === "leftovers";
      // Chunk 6.3 kickoff decision #9 — a slot's recipe name links to its own page.
      var name = isLeftovers
        ? el("span", "name plain", "Leftovers")
        : el("a", "name", slot.recipe_name || "Recipe #" + slot.recipe_id);
      if (!isLeftovers) name.href = "#/recipes/" + slot.recipe_id;
      row.appendChild(name);

      var controls = el("div", "controls");
      if (!isLeftovers) {
        controls.appendChild(
          servingsSelect(slot.scaled_servings, function (n) {
            api.sessions.updateSlot(session.id, slot.id, { scaled_servings: n }).catch(barf);
          })
        );
      }

      var moveBtn = el("button", "move-btn", "📅");
      moveBtn.type = "button";
      moveBtn.setAttribute(
        "aria-label",
        "Move " + (isLeftovers ? "Leftovers" : slot.recipe_name || "this recipe") + " to a different day"
      );
      moveBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        startMove(slot);
      });
      controls.appendChild(moveBtn);

      var removeBtn = el("button", "remove-btn btn-sm", "Remove");
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
      controls.appendChild(removeBtn);

      row.appendChild(controls);
      return row;

      function barf(err) {
        global.alert("Couldn't update: " + err.message);
      }
    }

    renderWeek();
  }

  global.SessionWeek = { render: render };
})(window);
