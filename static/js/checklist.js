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
    if (item.needs_review) return item.note || "Mixed units";
    var unit = item.display_unit || item.total_unit;
    if (item.display_qty) {
      // "Buy 2 × 500g tub (need 800 g)": what to buy first, then the exact amount the recipes need
      // (was "2 × 500g tub · need ~800 g" — the "~" read as a guess, and "need" as the buy amount).
      var s = "Buy " + item.display_qty;
      if (item.total_quantity != null)
        s += " (need " + fmtNum(item.total_quantity) + (unit ? " " + unit : "") + ")";
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
    var labels = ["Plan", "Checklist", "Send"];
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
  // Keyed by session id so opening a different checklist never restores another one's scroll.
  var savedScroll = null; // {sessionId, y}
  // Bumped on every mount and unmount: a response that arrives after the user left (or after the
  // screen was re-mounted) must not draw into the new screen (docs/ui-ux.md > UI state must not
  // silently vanish).
  var mountToken = 0;
  var currentSessionId = null;

  function mount(root, sessionId) {
    var myMount = ++mountToken;
    currentSessionId = sessionId;
    var loadSeq = 0; // newest load() wins: a slower, older response is dropped
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
    // The last push's response (2026-10-06, Chunk 6.7). A push triggers a load() that rebuilds the
    // whole body, which would wipe its result the instant it arrives; render() hands this back to
    // ChecklistPush, which shows it as the result card (counts, per-item Details, or "N items need
    // attention") until the user leaves the screen or pushes again.
    var lastPush = null;

    // Fix 3 — "Select to merge" mode (checklist-time merge, CLAUDE.md > Deferred Decisions).
    // Screen-level toggle, not a permanent per-row control — entering it hides the existing
    // have/need toggles and pack-size link on every regular row for the duration. Client-only
    // state, re-rendered from the last-loaded data (no API call) so toggling it or (un)checking
    // a row is instant. mergeSelected is {ingredient_name: item}, not just a name set, so the
    // merge panel can read each selected item's own display_name/total_unit without a re-fetch.
    var mergeMode = false;
    var mergeSelected = {};
    // While the merge panel is open its checkboxes are locked: ticking one re-rendered the whole
    // list and silently destroyed the panel and anything typed into it.
    var mergePanelOpen = false;
    // Typed-but-unsaved "use this" amount on a needs-review row, keyed by ingredient name, so an
    // unrelated re-render (expanding another row) doesn't wipe it.
    var reviewDraft = {};
    // The usuals: id -> "added" (will be sent on push) | "skipped" (stamped as stocked). Held here,
    // not only on the card's DOM, so a re-render doesn't show a decided card as undecided while
    // the push line still counts it.
    var usualState = {};
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
    // What the two buttons do, and what an untouched row means, stated once where it is used
    // (2026-10-11, Chunk 6.7: nothing on screen said untouched rows are not sent).
    card.appendChild(
      el(
        "div",
        "muted checklist-help",
        "Need it = sent · Have it = skipped · untouched = not sent"
      )
    );
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
      mergePanelOpen = false;
      var mySeq = ++loadSeq;
      api.settings.substitutions
        .list()
        .then(function (data) {
          picksByName = {};
          (data.items || []).forEach(function (r) {
            (picksByName[r.original_name] = picksByName[r.original_name] || []).push(r);
          });
        })
        .catch(function (e) {
          if (global.ErrorReport) global.ErrorReport.reportCaught("checklist quick-picks", e);
        });
      return api.checklist
        .load(sessionId)
        .then(function (data) {
          if (myMount !== mountToken || mySeq !== loadSeq) return; // left the screen / superseded
          render(data);
        })
        .catch(function (err) {
          if (myMount !== mountToken || mySeq !== loadSeq) return;
          body.innerHTML = "";
          syncNote.textContent = "";
          body.appendChild(el("div", "error-state", "Couldn't load the checklist: " + err.message));
        });
    }

    // `errSlot` (the row's own feedback line) gets "Couldn't save" if the PATCH fails, in place — no
    // native alert() (docs/ui-ux.md > No native dialogs). The pressed state is only updated on
    // success, so a failed tap visibly did not happen.
    var savingItems = {}; // item id -> true while its PATCH is in flight (a fast second tap raced it)

    function patchItem(item, changes, onDone, errSlot) {
      if (savingItems[item.id]) return;
      savingItems[item.id] = true;
      if (errSlot) global.Feedback.clear(errSlot);
      api.checklist
        .updateItem(sessionId, item.id, changes)
        .then(function (updated) {
          // `recipe_breakdown` only ever comes from the load response; a single-row edit must
          // never overwrite it (the server omits it, this is the belt to that brace).
          var breakdown = item.recipe_breakdown;
          Object.assign(item, updated);
          if (!updated || !updated.recipe_breakdown || !updated.recipe_breakdown.length) {
            item.recipe_breakdown = breakdown;
          }
          delete savingItems[item.id];
          refreshSummary();
          if (onDone) onDone();
        })
        .catch(function (err) {
          delete savingItems[item.id];
          global.Feedback.error(errSlot, "Couldn't save — " + global.Feedback.messageOf(err) + ". Tap again to retry.");
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
            ? "Checked against AnyList at page open. Items on it are “Have it”."
            : "⚠ Couldn't reach AnyList (" + (data.anylist_detail || "unknown") + ") — nothing could be checked."
        )
      );

      var items = data.items || [];
      var usuals = data.usuals || [];
      // A panel save/merge/alias can rename or fold the open row away; an `expandedKey` that no
      // longer matches any row would leave the back-guard "open" with nothing visibly open.
      if (
        expandedKey !== null &&
        !items.some(function (i) { return i.ingredient_name === expandedKey; })
      ) {
        expandedKey = null;
        if (global.PanelBackGuard.isOpen()) global.PanelBackGuard.close(function () {});
      }
      // Usuals that were skipped are stamped server-side and will not come back; forget stale picks.
      Object.keys(usualState).forEach(function (id) {
        if (!usuals.some(function (u) { return String(u.id) === id; })) {
          delete usualState[id];
          delete pushUsualIds[id];
        }
      });
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
        lastPush: lastPush,
        onResult: function (res) {
          lastPush = res;
          if (global.NavBadges) global.NavBadges.refresh(); // a sent plan is no longer "in progress"
        },
        onReload: load,
      });
      refreshSummary = pushSummary.refresh; // reassigned each render(); every state change calls this
      body.appendChild(pushSummary.el);

      // 2026-09-30 (chunk 7.6) — restore scroll position from before the user last left this
      // screen, once per mount only (a later reload, e.g. after a panel save, must not jump
      // the page back to wherever they were before they even arrived this time).
      if (!restoredScroll && savedScroll && savedScroll.sessionId === sessionId) {
        restoredScroll = true;
        var restoreTo = savedScroll.y;
        savedScroll = null;
        window.scrollTo(0, restoreTo);
      }
    }

    // --- needs-review ---
    function reviewGroup(review) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Mixed units"));
      review.forEach(function (item) {
        var row = el("div", "checklist-row");
        var main = el("div", "main");
        var nameParts = rowNameParts(
          item, null,
          expandedKey === item.ingredient_name,
          function () { toggleExpanded(item.ingredient_name); }
        );
        main.appendChild(nameParts.nameEl);
        main.appendChild(el("div", "meta", item.note || "Mixed units"));
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
          var btn = el("button", "btn-sm", "Use " + optionLabel(opt));
          btn.addEventListener("click", function () {
            global.Feedback.clear(picks);
            api.checklist
              .resolveItem(sessionId, item.id, { total_quantity: opt.quantity, total_unit: opt.unit })
              .then(load)
              .catch(function (err) { global.Feedback.error(picks, global.Feedback.messageOf(err)); });
          });
          picks.appendChild(btn);
        });
        wrap.appendChild(picks);

        // The third choice, as a labelled box: the household resolves the combination in their
        // head and types the total (2026-10-11 review - "why isn't there a third option?").
        var own = el("div", "pair-box");
        own.appendChild(el("div", "settings-sub-head", "Or enter your own total"));
        var mq = el("input"); mq.type = "number"; mq.step = "any"; mq.inputMode = "decimal"; mq.placeholder = "250";
        var mu = el("input"); mu.type = "text"; mu.placeholder = "ml";
        var draft = reviewDraft[item.ingredient_name] || (reviewDraft[item.ingredient_name] = { q: "", u: "" });
        mq.value = draft.q;
        mu.value = draft.u;
        mq.addEventListener("input", function () { draft.q = mq.value; });
        mu.addEventListener("input", function () { draft.u = mu.value; });
        var ownRow = el("div", "pair-row");
        ownRow.appendChild(mq);
        ownRow.appendChild(mu);
        var mb = el("button", "btn-sm primary", "Use this total");
        var manualActions = el("div", "log-controls");
        mb.addEventListener("click", function () {
          var q = parseFloat(mq.value);
          global.Feedback.clear(manualActions);
          if (isNaN(q) || q <= 0) { global.Feedback.error(manualActions, "Enter an amount greater than 0."); return; }
          api.checklist
            .resolveItem(sessionId, item.id, { total_quantity: q, total_unit: mu.value.trim() || null })
            .then(load)
            .catch(function (err) { global.Feedback.error(manualActions, global.Feedback.messageOf(err)); });
        });
        ownRow.appendChild(mb);
        own.appendChild(ownRow);
        own.appendChild(el("div", "muted", "Blank unit = whole items."));
        own.appendChild(manualActions);
        wrap.appendChild(own);
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
        var toggle = el("button", "btn-link", mergeMode ? "Done" : "Combine rows");
        toggle.style.marginLeft = "8px";
        toggle.addEventListener("click", function () {
          closeExpandedThen(function () {
            mergeMode = !mergeMode;
            mergeSelected = {};
            mergePanelOpen = false;
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
          checkbox.disabled = mergePanelOpen;
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
        var rowFeedback = el("div"); // "Couldn't save" appears here, on the row that failed
        main.appendChild(rowFeedback);
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
          (function (item, haveBtn, needBtn, rowFeedback) {
            function syncPressed() {
              haveBtn.setAttribute("aria-pressed", item.have_it === "yes" ? "true" : "false");
              needBtn.setAttribute("aria-pressed", item.have_it === "no" ? "true" : "false");
            }
            syncPressed();
            haveBtn.addEventListener("click", function () {
              var next = item.have_it === "yes" ? "unknown" : "yes";
              patchItem(item, { have_it: next, add_to_list: false }, syncPressed, rowFeedback);
            });
            needBtn.addEventListener("click", function () {
              var next = item.have_it === "no" ? "unknown" : "no";
              patchItem(item, { have_it: next, add_to_list: next === "no" }, syncPressed, rowFeedback);
            });
          })(item, haveBtn, needBtn, rowFeedback);
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
          var mergeBtn = el("button", "btn-sm primary", "Combine (" + selected.length + ")");
          mergeBtn.addEventListener("click", function () {
            mergeBtn.disabled = true;
            mergePanelOpen = true;
            wrap.querySelectorAll(".merge-select-checkbox").forEach(function (cb) { cb.disabled = true; });
            wrap.appendChild(
              mergePanel(selected, function () {
                mergeMode = false;
                mergeSelected = {};
                load(); // full reload -- names/totals genuinely changed server-side
              }, function () {
                mergePanelOpen = false;
                rerender();
              })
            );
          });
          actions.appendChild(mergeBtn);
        } else {
          actions.appendChild(el("span", "muted", "Tick 2 or more rows to combine."));
        }
        wrap.appendChild(actions);
      }
      return wrap;
    }

    // Fix 3 — the merge panel. Rewritten 2026-10-06 (Chunk 6.7) to the approved mockup
    // (docs/mockups/chunk-6.7/popups.html): the old flow asked "Always treat these as the same
    // ingredient?" in a native confirm() that named nothing. Now the panel says what will happen —
    // "parmesans + parmesan -> parmesan" — and the choice IS the two buttons: merge for this shopping
    // list only, or merge every time (all future recipes, said plainly, with where to undo it). Either
    // way a toast offers Undo. Keeps the optional, collapsed amount-equivalence field (point-of-need's
    // own guardrail — the common case, e.g. "capsicum"/"red capsicum", needs no ratio).
    function shownName(item) { return item.display_name || item.ingredient_name; }

    function mergePanel(selected, onDone, onCancel) {
      var wrap = el("div", "inline-card");
      wrap.appendChild(el("div", "title", "Combine rows"));

      var canonicalName = selected[0].ingredient_name;
      var summary = el("div", "merge-summary");
      wrap.appendChild(summary);
      function paintSummary() {
        summary.innerHTML = "";
        var members = selected.filter(function (i) { return i.ingredient_name !== canonicalName; });
        var kept = selected.filter(function (i) { return i.ingredient_name === canonicalName; })[0];
        members.forEach(function (m, i) {
          if (i > 0) summary.appendChild(document.createTextNode(" + "));
          summary.appendChild(el("span", "name-chip", shownName(m)));
        });
        summary.appendChild(document.createTextNode(" + "));
        summary.appendChild(el("span", "name-chip", shownName(kept)));
        summary.appendChild(document.createTextNode(" → "));
        summary.appendChild(el("span", "name-chip keep", shownName(kept)));
      }
      // "a + b -> c" reads best as "members + kept -> kept"; the kept name appears on both sides
      // so it is clear nothing is lost, only the other names fold into it.
      wrap.appendChild(el("div", "merge-pick", "Show the combined row as:"));
      selected.forEach(function (item, i) {
        var row = el("label", "radio-row");
        var radio = el("input");
        radio.type = "radio";
        radio.name = "merge-canonical";
        radio.value = item.ingredient_name;
        radio.checked = i === 0;
        radio.addEventListener("change", function () {
          canonicalName = item.ingredient_name;
          paintSummary();
        });
        row.appendChild(radio);
        row.appendChild(document.createTextNode(shownName(item)));
        wrap.appendChild(row);
      });
      paintSummary();

      var pairLinkRow = el("div", "meta-row");
      var pairLink = el("button", "btn-link", "Different measures?");
      pairLink.type = "button";
      var pair = null; // { grid, values() } from pairFields(), only when expanded
      pairLinkRow.appendChild(pairLink);
      wrap.appendChild(pairLinkRow);
      pairLink.addEventListener("click", function () {
        if (pair) {
          pair.grid.remove();
          pair = null;
          pairLink.textContent = "Different measures?";
          return;
        }
        pair = pairFields();
        wrap.insertBefore(pair.grid, actions);
        pairLink.textContent = "Skip the conversion";
      });

      var errSlot = el("div");
      var thisListBtn = el("button", "primary", "Combine for this plan");
      thisListBtn.type = "button";
      var everyTimeBtn = el("button", null, "Always combine");
      everyTimeBtn.type = "button";
      var fine = el("div", "fine");
      var cancelBtn = el("button", "btn-sm", "Cancel");
      cancelBtn.type = "button";
      var actions = el("div", "actions");
      actions.appendChild(thisListBtn);
      actions.appendChild(everyTimeBtn);
      wrap.appendChild(actions);
      wrap.appendChild(fine);
      var cancelRow = el("div", "actions row");
      cancelRow.style.marginTop = "var(--sp-2)";
      cancelRow.appendChild(cancelBtn);
      wrap.appendChild(cancelRow);
      wrap.appendChild(errSlot);

      function paintFine() {
        var members = selected.filter(function (i) { return i.ingredient_name !== canonicalName; });
        var kept = shownName(selected.filter(function (i) { return i.ingredient_name === canonicalName; })[0]);
        fine.textContent =
          "Always: " + members.map(function (m) { return "“" + shownName(m) + "”"; }).join(" or ") +
          " in any recipe shows as “" + kept + "”. Saved in Settings → Same item, different names.";
      }
      paintFine();
      wrap.addEventListener("change", paintFine); // keep the fine print in step with the radio choice

      cancelBtn.addEventListener("click", function () { if (onCancel) onCancel(); });

      function doMerge(remember) {
        global.Feedback.clear(errSlot);
        var values = pair ? pair.values() : {};
        if (pair && (values.alias_qty == null || values.canonical_qty == null)) {
          global.Feedback.error(errSlot, "Fill in both amounts, or tap “Skip the conversion”.");
          return;
        }
        var keptKey = canonicalName;
        var memberKeys = selected
          .map(function (i) { return i.ingredient_name; })
          .filter(function (n) { return n !== keptKey; });
        var keptShown = shownName(selected.filter(function (i) { return i.ingredient_name === keptKey; })[0]);
        thisListBtn.disabled = everyTimeBtn.disabled = true;
        api.checklist
          .merge(sessionId, {
            item_names: selected.map(function (i) { return i.ingredient_name; }),
            canonical_name: keptKey,
            remember: remember,
            alias_qty: values.alias_qty != null ? values.alias_qty : null,
            alias_unit: values.alias_unit || null,
            canonical_qty: values.canonical_qty != null ? values.canonical_qty : null,
            canonical_unit: values.canonical_unit || null,
          })
          .then(function (res) {
            offerUndo(keptKey, memberKeys, keptShown, remember, (res && res.alias_ids) || [], (res && res.unconverted) || [], values.alias_unit);
            onDone();
          })
          .catch(function (e) {
            thisListBtn.disabled = everyTimeBtn.disabled = false;
            // Merge is pre-push only — same reactive-409 handling as the Push button's own
            // "already pushed" case (checklist-push.js), rather than fetching session status
            // just to hide this control proactively.
            global.Feedback.error(
              errSlot,
              e.code === "SESSION_ALREADY_PUSHED"
                ? "This plan has already been sent — rows can't be combined after sending."
                : e.code === "DUPLICATE_INGREDIENT_ALIAS"
                ? "One of these names is already set to show as another item (Settings → Same item, different names). Pick a different name to show, or combine for this plan only."
                : global.Feedback.messageOf(e)
            );
          });
      }
      thisListBtn.addEventListener("click", function () { doMerge(false); });
      everyTimeBtn.addEventListener("click", function () { doMerge(true); });
      return wrap;
    }

    // The "Merged into …" toast with Undo. Undo reverses exactly what this merge did (the
    // this-list-only merge rows and/or the saved groups it created) and hands the merged line's
    // Need it / Have it back to the restored lines (POST /checklist/{id}/undo-merge).
    function offerUndo(keptKey, memberKeys, keptShown, remember, aliasIds, unconverted, pairUnit) {
      function undo() {
        api.checklist
          .undoMerge(sessionId, { canonical_name: keptKey, member_names: memberKeys, alias_ids: aliasIds })
          .then(function () {
            global.Toast.show("Combine undone.");
            load();
          })
          .catch(function (err) {
            global.Toast.show("Couldn't undo the combine — " + global.Feedback.messageOf(err), {
              tone: "error", actionLabel: "Retry", onAction: undo,
            });
          });
      }
      var mergedMsg = "Combined into “" + keptShown + "” — " + (remember ? "always" : "this plan only");
      if (unconverted && unconverted.length) {
        // The amount ratio only applies to a line measured in the unit typed for it; say which
        // lines it skipped instead of letting their amounts look converted.
        mergedMsg +=
          ". The conversion wasn't applied to " + unconverted.join(", ") +
          " (not in " + (pairUnit || "whole items") + "); their amounts are added as they are.";
      }
      global.Toast.show(mergedMsg, { actionLabel: "Undo", onAction: undo });
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
      var grid = el("div", "pair-box");
      var r1 = el("div", "pair-row");
      r1.appendChild(el("span", null, "Each other row ="));
      r1.appendChild(mqty);
      r1.appendChild(munit);
      var r2 = el("div", "pair-row");
      r2.appendChild(el("span", null, "of the combined row"));
      r2.appendChild(cqty);
      r2.appendChild(cunit);
      grid.appendChild(r1);
      grid.appendChild(r2);
      grid.appendChild(el("div", "muted", "Only rows measured in the unit you typed are converted; the rest are added as they are. Blank unit = whole items."));
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
      wrap.appendChild(el("div", "sub-group-heading", "The usuals"));
      if (!usuals.length) {
        wrap.appendChild(
          el(
            "div",
            "muted",
            "Nothing due. Items you add in Settings → The usuals show up here when it's time."
          )
        );
        return wrap;
      }
      usuals.forEach(function (u) {
        var card = el("div", "usual-card");
        card.appendChild(el("div", "q", u.name + " — every " + u.cadence_days + " days"));
        card.appendChild(
          el(
            "div",
            "cadence",
            "Buy it, or have enough for another " + u.cadence_days + " days?"
          )
        );
        var skippedNote = el("div", "skipped-note", "Skipped. Asked again in " + u.cadence_days + " days.");
        var actions = el("div", "actions");

        var addBtn = el("button", "primary", "Add to AnyList");
        addBtn.addEventListener("click", function () {
          pushUsualIds[u.id] = true;
          usualState[u.id] = "added";
          rerender();
          refreshSummary();
        });

        var skipBtn = el("button", null, "I have enough");
        skipBtn.addEventListener("click", function () {
          skipBtn.disabled = true;
          api.checklist
            .skipUsual(u.id)
            .then(function () {
              delete pushUsualIds[u.id];
              usualState[u.id] = "skipped";
              rerender();
              refreshSummary();
            })
            .catch(function (err) {
              skipBtn.disabled = false;
              global.Feedback.error(card, "Couldn't skip — " + global.Feedback.messageOf(err));
            });
        });

        actions.appendChild(addBtn);
        actions.appendChild(skipBtn);
        card.appendChild(actions);
        card.appendChild(skippedNote);
        // Re-apply a decision made before this re-render.
        if (usualState[u.id] === "added") {
          card.classList.add("skipped"); // reuse the same "resolved, out of the way" styling
          skippedNote.textContent = "Will be sent. ";
          var undoAdd = el("button", "btn-link", "Undo");
          undoAdd.addEventListener("click", function () {
            delete pushUsualIds[u.id];
            delete usualState[u.id];
            rerender();
            refreshSummary();
          });
          skippedNote.appendChild(undoAdd);
        } else if (usualState[u.id] === "skipped") {
          card.classList.add("skipped");
        }
        wrap.appendChild(card);
      });
      return wrap;
    }
  }

  function unmount() {
    global.ChecklistPush.unmount();
    savedScroll = { sessionId: currentSessionId, y: window.scrollY }; // restored by the next mount() of this session
    mountToken++; // any response still in flight belongs to a screen that is gone
    global.PanelBackGuard.reset();
  }

  global.ChecklistView = { mount: mount, unmount: unmount };
})(window);
