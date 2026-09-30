/* Checklist screen (Phase 5 Chunk 5.5) — #/checklist/<session_id>.

   Walks the consolidated shopping list one item at a time: "do you have this?".
   Items already on AnyList are pre-ticked and shown distinctly. The due "usuals" are their
   own group. Irreconcilable-units lines (Chunk 4.6) get an inline resolve control. Items you
   don't have (or explicitly tick "add") are what Chunk 5.6 pushes to AnyList.

   have_it is BINARY (no 'partial' — see CLAUDE.md > Deferred Decisions), set via two
   independent one-tap toggles ("Have it" / "Need it") — 2026-09-24, replacing an earlier
   single button that cycled unknown -> yes -> no -> unknown (reaching a specific target could
   take up to two taps). Tapping the pressed button reverts to unknown; tapping either button
   reaches its target state in exactly one tap from any starting state. Tapping "Need it" also
   sets add_to_list; anything else clears it. See CLAUDE.md > Checklist Screen Logic.

   Phase 6 Chunk 6.3b: design system applied, shared Back link, step indicator
   continuing from 6.3 (Plan -> Review -> Checklist -> Push), a quiet "checked against
   AnyList" sync note instead of leaving push failures to speak for themselves, and "the
   usuals" reworked from a bare checkbox into the stock-check prompt (kickoff decision
   #8) — "Add to list" or "I'm stocked, skip this time" (the latter calls
   POST /checklist/usuals/{id}/skip, which stamps last_added_at with no AnyList push at
   all). The sticky Push button, its rotating per-item progress label, and the
   discrepancy-warning banner for an unconfirmed push live in checklist-push.js — split
   out once this file passed the file-size guideline. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function qtyText(item) {
    // 2026-09-10 hand-testing: a note on a normally-resolved line (an overage hint, "(+ to
    // taste)", or — new — an Ingredient Aliases conversion note like "from 4 tbsp lemon
    // juice") used to only show up on the session-review screen (now deleted, 2026-09-30,
    // chunk 7.4), never here on the checklist, even though this is the screen right before
    // push. Fixed by matching that screen's own equivalent formatting at the time.
    if (item.needs_review) return item.note || "mixed units";
    var unit = item.display_unit || item.total_unit;
    if (item.display_qty) {
      var s = item.display_qty;
      if (item.total_quantity != null)
        s += " · need ~" + fmtNum(item.total_quantity) + (unit ? " " + unit : "");
      if (item.note) s += " · " + item.note;
      return s;
    }
    if (item.total_quantity == null) return item.note || "";
    var qty = fmtNum(item.total_quantity) + (unit ? " " + unit : "");
    return item.note ? qty + " · " + item.note : qty;
  }

  function fmtNum(n) {
    return n === Math.round(n) ? String(Math.round(n)) : String(Math.round(n * 100) / 100);
  }

  function optionLabel(opt) {
    var unit = opt.display_unit || opt.unit;
    return unit ? fmtNum(opt.quantity) + " " + unit : fmtNum(opt.quantity);
  }

  // "Which recipe is this ingredient from" (CLAUDE.md > scaling-and-consolidation.md) — moved
  // here 2026-09-30 (chunk 7.4) from the now-deleted session-review.js (Review screen), ported
  // verbatim: one row per contributing recipe SLOT, never merged (even two slots of the same
  // recipe show separately). Ephemeral display aid — the data itself is recomputed fresh on
  // every checklist load (checklist.py > load_checklist(), chunk 7.3), never stored.
  function fmtContribution(c) {
    if (c.is_no_scale) return "to taste";
    var n = c.quantity === Math.round(c.quantity) ? String(Math.round(c.quantity)) : String(c.quantity);
    return c.unit ? n + " " + c.unit : n;
  }

  function renderBreakdown(item) {
    var wrap = el("div", "recipe-breakdown");
    (item.recipe_breakdown || []).forEach(function (c) {
      var line = el("div", "recipe-breakdown-row muted");
      var link = el("a", null, c.recipe_label);
      if (c.recipe_id != null) link.href = "#/recipes/" + c.recipe_id;
      line.appendChild(link);
      line.appendChild(document.createTextNode(" — " + fmtContribution(c)));
      wrap.appendChild(line);
    });
    return wrap;
  }

  // Builds a row's name element plus a slot the caller appends to the row itself (flex-basis:
  // 100%, so it wraps beneath the row's other controls, not squeezed). Expandable — the name
  // becomes a real `<button>` (keyboard/screen-reader focusable, matching the now-deleted
  // session-review.js's original) — when there's a recipe breakdown to show, OR `extraBuilder`
  // is given (the ingredient panel, itemsGroup()'s regular rows only — point-of-need
  // guardrail, CLAUDE.md > UI/UX: reviewGroup()'s rows don't get one, matching the plan's
  // decision to scope the panel to regular rows). A plain `<div>` otherwise. Returns
  // { nameEl, slot } — slot is null when there's nothing to expand at all.
  //
  // 2026-09-30 (chunk 7.6) — expansion is driven by the caller's own `isExpanded` state
  // (screen-wide select-exclusive, see mount()'s expandedKey/toggleExpanded) rather than local
  // DOM toggling, so it re-renders correctly from a single source of truth on every Back press
  // (PanelBackGuard.close() calls rerender(), which rebuilds every row from expandedKey).
  // Link clicks inside an expanded slot (recipe-breakdown links, chiefly) are handled globally
  // by panel-back-guard.js's own capturing-phase click listener, not here — see its docstring
  // for why a per-slot listener alone can't cover a nav-bar click too.
  function rowNameParts(item, extraBuilder, isExpanded, onToggle) {
    var text = item.display_name || item.ingredient_name;
    var hasBreakdown = (item.recipe_breakdown || []).length > 0;
    if (!hasBreakdown && !extraBuilder) return { nameEl: el("div", "name", text), slot: null };

    var nameEl = el("button", "name recipe-row-name-btn", text + (isExpanded ? " ▴" : " ▾"));
    nameEl.addEventListener("click", onToggle);
    if (!isExpanded) return { nameEl: nameEl, slot: null };

    var slot = el("div");
    slot.style.flexBasis = "100%";
    if (hasBreakdown) slot.appendChild(renderBreakdown(item));
    if (extraBuilder) {
      var extra = extraBuilder();
      if (extra) slot.appendChild(extra);
    }
    return { nameEl: nameEl, slot: slot };
  }

  // Shared Plan -> Checklist -> Push indicator (own small copy — see sessions.js's identical
  // helper and this file family's self-contained-feature-file precedent). Was
  // Plan -> Review -> Checklist -> Push until 2026-09-30 (chunk 7.4), when the standalone
  // Review screen was deleted and its useful parts (recipe breakdown, above) folded in here.
  // Push happens on this same screen (no separate route), so "Checklist" stays active through
  // both the pre-push and pushing states.
  function stepIndicator(activeLabel) {
    var labels = ["Plan", "Checklist", "Push"];
    var wrap = el("div", "step-list");
    labels.forEach(function (label, i) {
      wrap.appendChild(el("span", label === activeLabel ? "on" : null, label));
      if (i < labels.length - 1) wrap.appendChild(el("span", "sep", "→"));
    });
    return wrap;
  }

  // 2026-09-30 (chunk 7.6) — scroll position across a Back-then-forward round trip. Module
  // level (not inside mount()'s own closure), since it must survive from one mount() call to
  // the next one, across whatever screen was visited in between. Restored once per mount, on
  // the first load() only — a later reload (e.g. after a panel save) shouldn't jump the page.
  var savedScrollY = null;

  function mount(root, sessionId) {
    root.innerHTML = "";
    global.ChecklistPush.unmount(); // clears any push-progress timer from a prior mount
    var restoredScroll = false;
    var pushUsualIds = {}; // id -> true, client-held until push
    // 2026-09-10 hand-testing ("0 items will go on the list" - was wrong): the summary line
    // used to be computed once at render() time and never touched again, so it went stale
    // the moment a tap/checkbox changed have_it, add_to_list, or a usual's selection without
    // a full page reload. Reassigned by summary() below; every state-changing handler calls
    // it so the count stays live. No-op until the first render.
    var refreshSummary = function () {};
    // Set when a push comes back with res.confirmed === false; render() re-shows the banner
    // across the load() this triggers (a plain body rebuild would otherwise wipe it the
    // instant the "confirmed" push response arrives) until a later push confirms cleanly.
    var lastDiscrepancies = null;

    // Fix 3 — "Select to merge" mode (checklist-time merge, CLAUDE.md > Deferred Decisions).
    // Screen-level toggle, not a permanent per-row control — entering it hides the existing
    // have/need toggles and pack-size link on every regular row for the duration. Client-only
    // state, re-rendered from the last-loaded data (no API call) so toggling it or (un)checking
    // a row is instant. mergeSelected is {ingredient_name: item}, not just a name set, so the
    // merge panel can read each selected item's own display_name/total_unit without a re-fetch.
    var mergeMode = false;
    var mergeSelected = {};
    var lastData = null;
    // Ingredient panel's Substitute chip quick-picks (2026-09-30, chunk 7.5) — fetched once
    // per load, same as the now-deleted session-review.js used to, keyed by original_name.
    // A failure here is non-fatal (empty quick-picks, manual entry still works) — never blocks
    // the checklist itself from loading.
    var picksByName = {};
    function rerender() {
      if (lastData) render(lastData);
    }

    // 2026-09-30 (chunk 7.6) — screen-wide select-exclusive row expansion (at most one row's
    // breakdown/panel open at a time), backed by PanelBackGuard so a Back press/gesture closes
    // it before navigating away, rather than skipping straight past it. expandedKey is the
    // expanded row's ingredient_name, or null.
    var expandedKey = null;

    function closeExpandedThen(fn) {
      if (expandedKey === null) {
        fn();
        return;
      }
      global.PanelBackGuard.close(function () {
        expandedKey = null;
        fn();
      });
    }

    function toggleExpanded(key) {
      if (expandedKey === key) {
        closeExpandedThen(rerender);
        return;
      }
      closeExpandedThen(function () {
        expandedKey = key;
        global.PanelBackGuard.open(function () {
          expandedKey = null;
          rerender();
        });
        rerender();
      });
    }

    function onStartMerge(item) {
      closeExpandedThen(function () {
        mergeMode = true;
        mergeSelected[item.ingredient_name] = item;
        rerender();
      });
    }

    root.appendChild(global.BackLink.render("plan"));
    root.appendChild(stepIndicator("Checklist"));

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Shopping checklist"));
    var syncNote = el("div", "sync-note");
    syncNote.appendChild(el("span", "sync-dot"));
    syncNote.appendChild(document.createTextNode("Checking against AnyList…"));
    card.appendChild(syncNote);
    var body = el("div");
    var skel = el("div", "skel-row");
    var skelLine = el("div", "skeleton skel-line");
    skelLine.style.width = "100%";
    skel.appendChild(skelLine);
    body.appendChild(skel);
    card.appendChild(body);
    root.appendChild(card);

    load();

    function load() {
      mergeMode = false;
      mergeSelected = {};
      api.settings.substitutions
        .list()
        .then(function (data) {
          picksByName = {};
          (data.items || []).forEach(function (r) {
            (picksByName[r.original_name] = picksByName[r.original_name] || []).push(r);
          });
        })
        .catch(function () {});
      api.checklist
        .load(sessionId)
        .then(render)
        .catch(function (err) {
          body.innerHTML = "";
          syncNote.textContent = "";
          body.appendChild(el("div", "error-state", "Couldn't load the checklist: " + err.message));
        });
    }

    function patchItem(item, changes, onDone) {
      api.checklist
        .updateItem(sessionId, item.id, changes)
        .then(function (updated) {
          Object.assign(item, updated);
          refreshSummary();
          if (onDone) onDone();
        })
        .catch(function (err) {
          global.alert("Couldn't save: " + err.message);
        });
    }

    function render(data) {
      lastData = data;
      body.innerHTML = "";
      syncNote.className = "sync-note" + (data.anylist_ok ? "" : " stale");
      syncNote.innerHTML = "";
      syncNote.appendChild(el("span", "sync-dot"));
      syncNote.appendChild(
        document.createTextNode(
          data.anylist_ok
            ? "Checked against AnyList as of this page load — items already on the list are pre-ticked."
            : "⚠ Couldn't reach AnyList (" + (data.anylist_detail || "unknown") + ") — nothing pre-ticked."
        )
      );

      if (lastDiscrepancies) body.appendChild(global.ChecklistPush.renderDiscrepancyBanner(lastDiscrepancies));

      var items = data.items || [];
      var usuals = data.usuals || [];
      var review = items.filter(function (i) { return i.needs_review; });
      var regular = items.filter(function (i) { return !i.needs_review; });

      if (review.length) body.appendChild(reviewGroup(review));
      body.appendChild(itemsGroup(regular));
      // 2026-09-10 hand-testing ("Where's the usuals?") — this group used to disappear
      // entirely when nothing was currently due, which is indistinguishable from the feature
      // not existing at all if you've never set any usuals up. Always show it, with a message
      // explaining why it's empty either way, so the checklist is where you'd discover it.
      body.appendChild(usualsGroup(usuals));

      var pushSummary = global.ChecklistPush.renderSummary({
        sessionId: sessionId,
        items: items,
        usuals: usuals,
        pushUsualIds: pushUsualIds,
        onResult: function (res) {
          if (!res.confirmed && res.discrepancies && res.discrepancies.length) {
            lastDiscrepancies = res.discrepancies;
          } else {
            lastDiscrepancies = null;
            var msg =
              "Pushed. Added " + (res.added || []).length + ", updated " + (res.updated || []).length +
              (res.usuals_added && res.usuals_added.length ? ", + " + res.usuals_added.length + " usual(s)" : "") +
              ".";
            global.Toast.show(msg);
          }
        },
        onReload: load,
      });
      refreshSummary = pushSummary.refresh; // reassigned each render(); every state change calls this
      body.appendChild(pushSummary.el);

      // 2026-09-30 (chunk 7.6) — restore scroll position from before the user last left this
      // screen, once per mount only (a later reload, e.g. after a panel save, must not jump
      // the page back to wherever they were before they even arrived this time).
      if (!restoredScroll && savedScrollY != null) {
        restoredScroll = true;
        var restoreTo = savedScrollY;
        savedScrollY = null;
        window.scrollTo(0, restoreTo);
      }
    }

    // --- needs-review ---
    function reviewGroup(review) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Needs review — pick one amount"));
      review.forEach(function (item) {
        var row = el("div", "checklist-row");
        var main = el("div", "main");
        var nameParts = rowNameParts(
          item, null,
          expandedKey === item.ingredient_name,
          function () { toggleExpanded(item.ingredient_name); }
        );
        main.appendChild(nameParts.nameEl);
        main.appendChild(el("div", "meta", item.note || "mixed units"));
        row.appendChild(main);
        if (nameParts.slot) row.appendChild(nameParts.slot);
        wrap.appendChild(row);

        var picks = el("div", "log-controls");
        picks.style.marginBottom = "8px";
        // 2026-09-13 code review — quick-picks now come straight from the structured
        // review_options the backend computed (services/consolidation.py > ReviewOption),
        // not by regex-parsing `item.note` back apart. `note` can carry extra appended text
        // (e.g. an Ingredient Aliases conversion fragment) alongside the review breakdown,
        // which a regex had no reliable way to tell apart from the breakdown itself.
        // 2026-09-27 — optionLabel() reads opt.display_unit when present, so a discrete
        // counting unit pluralises naturally ("use 12 cloves") — see
        // services/checklist_display.py::display_unit. The ingredient's own name is
        // deliberately never repeated here; the card heading above already names it once.
        (item.review_options || []).forEach(function (opt) {
          var btn = el("button", "btn-sm", "use " + optionLabel(opt));
          btn.addEventListener("click", function () {
            api.checklist
              .resolveItem(sessionId, item.id, { total_quantity: opt.quantity, total_unit: opt.unit })
              .then(load)
              .catch(function (err) { global.alert(err.message); });
          });
          picks.appendChild(btn);
        });
        wrap.appendChild(picks);

        var manual = el("div", "ing-grid");
        var mq = el("input"); mq.type = "number"; mq.step = "any"; mq.inputMode = "decimal";
        var mu = el("input"); mu.type = "text";
        manual.appendChild(miniField("Amount", mq));
        manual.appendChild(miniField("Unit", mu));
        var mb = el("button", "btn-sm primary", "use this");
        mb.addEventListener("click", function () {
          var q = parseFloat(mq.value);
          if (isNaN(q) || q <= 0) { global.alert("Enter a positive amount."); return; }
          api.checklist
            .resolveItem(sessionId, item.id, { total_quantity: q, total_unit: mu.value.trim() || null })
            .then(load)
            .catch(function (err) { global.alert(err.message); });
        });
        var manualActions = el("div", "log-controls");
        manualActions.style.marginTop = "6px";
        manualActions.appendChild(mb);
        wrap.appendChild(manual);
        wrap.appendChild(manualActions);
      });
      return wrap;
    }

    function miniField(labelText, inputEl) {
      var wrap = el("div", "mini-field");
      wrap.appendChild(el("label", null, labelText));
      wrap.appendChild(inputEl);
      return wrap;
    }

    // --- regular items ---
    function itemsGroup(regular) {
      var wrap = el("div");
      var heading = el("div", "sub-group-heading");
      heading.appendChild(document.createTextNode("Ingredients"));
      // Fix 3 — "Select to merge" toggle, only worth showing with 2+ rows to actually merge.
      // Screen-level mode, not a permanent per-row control (see the mount()-level comment
      // above) — re-rendered locally via rerender(), no API call just to toggle it.
      if (regular.length >= 2) {
        var toggle = el("button", "btn-link", mergeMode ? "Cancel" : "Select to merge");
        toggle.style.marginLeft = "8px";
        toggle.addEventListener("click", function () {
          closeExpandedThen(function () {
            mergeMode = !mergeMode;
            mergeSelected = {};
            rerender();
          });
        });
        heading.appendChild(toggle);
      }
      wrap.appendChild(heading);
      if (!regular.length) wrap.appendChild(el("div", "muted", "Nothing here."));
      regular.forEach(function (item) {
        var row = el("div", "checklist-row");
        if (item.already_on_anylist) row.classList.add("on-anylist");

        if (mergeMode) {
          var checkbox = el("input");
          checkbox.type = "checkbox";
          checkbox.className = "merge-select-checkbox";
          checkbox.checked = !!mergeSelected[item.ingredient_name];
          checkbox.addEventListener("change", function () {
            if (checkbox.checked) mergeSelected[item.ingredient_name] = item;
            else delete mergeSelected[item.ingredient_name];
            rerender();
          });
          row.appendChild(checkbox);
        }

        var main = el("div", "main");
        // 2026-09-27 — natural-English display form ("chicken thighs", not the matching key
        // "chicken thigh") for this line's own resolved amount — see
        // services/checklist_display.py. Falls back to ingredient_name for safety if an older
        // cached response is ever re-rendered without display_name.
        // 2026-09-30 (chunk 7.4/7.5) — tap-to-expand recipe breakdown + the ingredient panel
        // (pack size / substitute / alias / coarse item / merge), ported from the now-deleted
        // Review screen and the old standalone "+ Add pack size" link respectively. Suppressed
        // in merge-select mode, same as the have/need pair below — one row shouldn't carry two
        // competing sets of controls.
        var nameParts = rowNameParts(
          item,
          mergeMode
            ? null
            : function () {
                return global.ChecklistPanel.build(sessionId, item, {
                  picksByName: picksByName,
                  canMerge: regular.length >= 2,
                  onStartMerge: onStartMerge,
                  onSaved: load,
                });
              },
          expandedKey === item.ingredient_name,
          function () { toggleExpanded(item.ingredient_name); }
        );
        main.appendChild(nameParts.nameEl);
        var metaRow = el("div", "meta-row");
        metaRow.appendChild(el("div", "meta", qtyText(item)));
        main.appendChild(metaRow);
        row.appendChild(main);

        if (!mergeMode) {
          // 2026-09-24 — two independent one-tap toggles, replacing the single button that used
          // to cycle unknown -> yes -> no -> unknown (reaching a specific target state could
          // take up to two taps). Tapping the pressed button reverts to "unknown"; tapping
          // either button reaches its target state in exactly one tap from any starting state.
          // Backend is unchanged — update_item() already accepts have_it/add_to_list
          // independently, with no validation on the transition (see
          // app/services/checklist.py > update_item()).
          var pair = el("div", "have-need-pair");
          var haveBtn = el("button", "have-need-btn have", "Have it");
          var needBtn = el("button", "have-need-btn need", "Need it");
          (function (item, haveBtn, needBtn) {
            function syncPressed() {
              haveBtn.setAttribute("aria-pressed", item.have_it === "yes" ? "true" : "false");
              needBtn.setAttribute("aria-pressed", item.have_it === "no" ? "true" : "false");
            }
            syncPressed();
            haveBtn.addEventListener("click", function () {
              var next = item.have_it === "yes" ? "unknown" : "yes";
              patchItem(item, { have_it: next, add_to_list: false }, syncPressed);
            });
            needBtn.addEventListener("click", function () {
              var next = item.have_it === "no" ? "unknown" : "no";
              patchItem(item, { have_it: next, add_to_list: next === "no" }, syncPressed);
            });
          })(item, haveBtn, needBtn);
          pair.appendChild(haveBtn);
          pair.appendChild(needBtn);
          row.appendChild(pair);
        }
        if (nameParts.slot) row.appendChild(nameParts.slot);
        wrap.appendChild(row);
      });

      if (mergeMode) {
        var selected = Object.keys(mergeSelected).map(function (k) { return mergeSelected[k]; });
        var actions = el("div", "log-controls");
        actions.style.marginTop = "8px";
        if (selected.length >= 2) {
          var mergeBtn = el("button", "btn-sm primary", "Merge (" + selected.length + ")");
          mergeBtn.addEventListener("click", function () {
            mergeBtn.disabled = true;
            wrap.appendChild(
              mergePanel(selected, function () {
                mergeMode = false;
                mergeSelected = {};
                load(); // full reload -- names/totals genuinely changed server-side
              })
            );
          });
          actions.appendChild(mergeBtn);
        } else {
          actions.appendChild(el("span", "muted", "Select 2 or more to merge."));
        }
        wrap.appendChild(actions);
      }
      return wrap;
    }

    // Fix 3 — the merge confirmation panel: canonical-name choice, an optional dormant
    // amount-equivalence field (point-of-need's own guardrail — collapsed by default, matching
    // the common case where a merge needs no ratio at all, e.g. "capsicum"/"red capsicum"),
    // and the existing "remember this?" confirm pattern session-review.js's askRemember()
    // already establishes (a plain browser confirm(), not a custom control).
    function mergePanel(selected, onDone) {
      var wrap = el("div", "pack-size-form"); // same inline-expansion visual treatment
      wrap.appendChild(el("div", "sub-group-heading", "Keep which name?"));
      var canonicalName = selected[0].ingredient_name;
      selected.forEach(function (item, i) {
        var row = el("label", "radio-row");
        var radio = el("input");
        radio.type = "radio";
        radio.name = "merge-canonical";
        radio.value = item.ingredient_name;
        radio.checked = i === 0;
        radio.addEventListener("change", function () {
          canonicalName = item.ingredient_name;
        });
        row.appendChild(radio);
        row.appendChild(document.createTextNode(" " + (item.display_name || item.ingredient_name)));
        wrap.appendChild(row);
      });

      var pairLinkRow = el("div", "meta-row");
      var pairLink = el("button", "btn-link", "Not the same amount? Tap to set the equivalent");
      var pair = null; // { grid, values() } from pairFields(), only when expanded
      pairLinkRow.appendChild(pairLink);
      wrap.appendChild(pairLinkRow);
      // `actions` (declared further below, `var`-hoisted) is only ever read here once the
      // user actually clicks this link, by which point mergePanel()'s own setup below —
      // including `actions`'s assignment — has already finished running.
      pairLink.addEventListener("click", function () {
        if (pair) {
          pair.grid.remove();
          pair = null;
          pairLink.textContent = "Not the same amount? Tap to set the equivalent";
          return;
        }
        pair = pairFields();
        wrap.insertBefore(pair.grid, actions);
        pairLink.textContent = "Hide the amount equivalence";
      });

      var err = el("span", "form-error");
      var confirmBtn = el("button", "btn-sm primary", "Merge");
      confirmBtn.addEventListener("click", function () {
        err.textContent = "";
        var values = pair ? pair.values() : {};
        if (pair && (values.alias_qty == null || values.canonical_qty == null)) {
          err.textContent = "Enter both amounts, or collapse the equivalence field to skip it.";
          return;
        }
        var remember = global.confirm(
          "Always treat these as the same ingredient? This will apply to every future recipe " +
            "using these names, not just this session."
        );
        confirmBtn.disabled = true;
        api.checklist
          .merge(sessionId, {
            item_names: selected.map(function (i) { return i.ingredient_name; }),
            canonical_name: canonicalName,
            remember: remember,
            alias_qty: values.alias_qty != null ? values.alias_qty : null,
            alias_unit: values.alias_unit || null,
            canonical_qty: values.canonical_qty != null ? values.canonical_qty : null,
            canonical_unit: values.canonical_unit || null,
          })
          .then(function () {
            global.Toast.show("Merged.");
            onDone();
          })
          .catch(function (e) {
            confirmBtn.disabled = false;
            // Merge is pre-push only — same reactive-409 handling as the Push button's own
            // "already pushed" case (checklist-push.js), rather than fetching session status
            // just to hide this control proactively.
            err.textContent =
              e.code === "SESSION_ALREADY_PUSHED"
                ? "This session has already been pushed — merging isn't available after push."
                : e.message;
          });
      });
      var actions = el("div", "log-controls");
      actions.appendChild(confirmBtn);
      actions.appendChild(err);
      wrap.appendChild(actions);
      return wrap;
    }

    // Fix 3's own small local copy of the same four-field amount/unit grid shape
    // settings-ingredient-aliases.js / settings-substitutions.js already establish — this
    // codebase's own deliberate, established convention for this exact class of UI helper
    // (already duplicated in those two files; miniField() itself is duplicated in eleven files
    // across this app), not something to extract into a shared module.
    function pairFields() {
      function num() {
        var n = el("input");
        n.type = "number";
        n.step = "any";
        n.inputMode = "decimal";
        return n;
      }
      function txt() {
        var t = el("input");
        t.type = "text";
        return t;
      }
      var mqty = num();
      var munit = txt();
      var cqty = num();
      var cunit = txt();
      var grid = el("div", "ing-grid");
      grid.style.gridTemplateColumns = "1fr 1fr 1fr 1fr";
      grid.appendChild(miniField("This amount", mqty));
      grid.appendChild(miniField("Unit", munit));
      grid.appendChild(miniField("= Kept amount", cqty));
      grid.appendChild(miniField("Unit (blank = count)", cunit));
      return {
        grid: grid,
        values: function () {
          var mq = parseFloat(mqty.value);
          var cq = parseFloat(cqty.value);
          return {
            alias_qty: isNaN(mq) ? null : mq,
            alias_unit: munit.value.trim() || null,
            canonical_qty: isNaN(cq) ? null : cq,
            canonical_unit: cunit.value.trim() || null,
          };
        },
      };
    }

    // packSizeForm()/reconsolidateAndReload() removed 2026-09-30 (chunk 7.5) — the standalone
    // "+ Add pack size" link they powered is gone; pack size is now the ingredient panel's own
    // Pack size chip (checklist-panel.js > packSizePanel()), which calls the new
    // POST .../pack-size endpoint directly and reloads via the panel's own onSaved callback.

    // --- the usuals: a stock-check prompt, not a bare checkbox (kickoff decision #8) ---
    function usualsGroup(usuals) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "The usuals — due now"));
      if (!usuals.length) {
        wrap.appendChild(
          el(
            "div",
            "muted",
            "Nothing due right now. Recurring items you add in Settings → The usuals show up here when they're due."
          )
        );
        return wrap;
      }
      usuals.forEach(function (u) {
        var card = el("div", "usual-card");
        card.appendChild(el("div", "q", u.name + " — due, every " + u.cadence_days + " days"));
        card.appendChild(
          el(
            "div",
            "cadence",
            "Add it, or do you have enough to last another " + u.cadence_days + " days?"
          )
        );
        var skippedNote = el("div", "skipped-note", "Skipped — you'll be asked again in " + u.cadence_days + " days.");
        var actions = el("div", "actions");

        var addBtn = el("button", "primary", "Add to list");
        addBtn.addEventListener("click", function () {
          pushUsualIds[u.id] = true;
          card.classList.add("skipped"); // reuse the same "resolved, out of the way" styling
          skippedNote.textContent = "Added to this session's push.";
          refreshSummary();
        });

        var skipBtn = el("button", null, "I'm stocked, skip this time");
        skipBtn.addEventListener("click", function () {
          skipBtn.disabled = true;
          api.checklist
            .skipUsual(u.id)
            .then(function () {
              delete pushUsualIds[u.id];
              card.classList.add("skipped");
              refreshSummary();
            })
            .catch(function (err) {
              skipBtn.disabled = false;
              global.alert("Couldn't skip: " + err.message);
            });
        });

        actions.appendChild(addBtn);
        actions.appendChild(skipBtn);
        card.appendChild(actions);
        card.appendChild(skippedNote);
        wrap.appendChild(card);
      });
      return wrap;
    }
  }

  function unmount() {
    global.ChecklistPush.unmount();
    savedScrollY = window.scrollY; // restored by the next mount() — see its own comment
  }

  global.ChecklistView = { mount: mount, unmount: unmount };
})(window);
