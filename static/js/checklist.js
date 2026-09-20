/* Checklist screen (Phase 5 Chunk 5.5) — #/checklist/<session_id>.

   Walks the consolidated shopping list one item at a time: "do you have this?".
   Items already on AnyList are pre-ticked and shown distinctly. Staples and the due
   "usuals" are their own groups. Irreconcilable-units lines (Chunk 4.6) get an inline
   resolve control. Items you don't have (or explicitly tick "add") are what Chunk 5.6
   pushes to AnyList.

   have_it tap cycle is BINARY: unknown -> yes -> no -> unknown (no 'partial' — see
   CLAUDE.md > Deferred Decisions). Tapping to 'no' also sets add_to_list; back to
   yes/unknown clears it. See CLAUDE.md > Checklist Screen Logic.

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

  var HAVE_NEXT = { unknown: "yes", yes: "no", no: "unknown" };
  var HAVE_LABEL = { unknown: "?", yes: "have it", no: "need it" };

  function qtyText(item) {
    // 2026-09-10 hand-testing: a note on a normally-resolved line (an overage hint, "(+ to
    // taste)", or — new — an Ingredient Aliases conversion note like "from 4 tbsp lemon
    // juice") used to only show up on the session-review screen, never here on the
    // checklist, even though this is the screen right before push. Matched to
    // session-review.js's renderItemRow so both screens show the same information.
    if (item.needs_review) return item.note || "mixed units";
    if (item.display_qty) {
      var s = item.display_qty;
      if (item.total_quantity != null)
        s += " · need ~" + fmtNum(item.total_quantity) + (item.total_unit ? " " + item.total_unit : "");
      if (item.note) s += " · " + item.note;
      return s;
    }
    if (item.total_quantity == null) return item.note || "";
    var qty = fmtNum(item.total_quantity) + (item.total_unit ? " " + item.total_unit : "");
    return item.note ? qty + " · " + item.note : qty;
  }

  function fmtNum(n) {
    return n === Math.round(n) ? String(Math.round(n)) : String(Math.round(n * 100) / 100);
  }

  function optionLabel(opt) {
    return opt.unit ? fmtNum(opt.quantity) + " " + opt.unit : fmtNum(opt.quantity);
  }

  // Shared Plan -> Review -> Checklist -> Push indicator (own small copy — see
  // session-review.js/sessions.js's identical helper and this file family's
  // self-contained-feature-file precedent). Push happens on this same screen (no separate
  // route), so "Checklist" stays active through both the pre-push and pushing states.
  function stepIndicator(activeLabel) {
    var labels = ["Plan", "Review", "Checklist", "Push"];
    var wrap = el("div", "step-list");
    labels.forEach(function (label, i) {
      wrap.appendChild(el("span", label === activeLabel ? "on" : null, label));
      if (i < labels.length - 1) wrap.appendChild(el("span", "sep", "→"));
    });
    return wrap;
  }

  function mount(root, sessionId) {
    root.innerHTML = "";
    global.ChecklistPush.unmount(); // clears any push-progress timer from a prior mount
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
      var staples = items.filter(function (i) { return i.is_staple && !i.needs_review; });
      var regular = items.filter(function (i) { return !i.is_staple && !i.needs_review; });

      if (review.length) body.appendChild(reviewGroup(review));
      body.appendChild(itemsGroup(regular));
      if (staples.length) body.appendChild(staplesGroup(staples));
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
    }

    // --- needs-review ---
    function reviewGroup(review) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Needs review — pick one amount"));
      review.forEach(function (item) {
        var row = el("div", "checklist-row");
        var main = el("div", "main");
        main.appendChild(el("div", "name", item.ingredient_name));
        main.appendChild(el("div", "meta", item.note || "mixed units"));
        row.appendChild(main);
        wrap.appendChild(row);

        var picks = el("div", "log-controls");
        picks.style.marginBottom = "8px";
        // 2026-09-13 code review — quick-picks now come straight from the structured
        // review_options the backend computed (services/consolidation.py > ReviewOption),
        // not by regex-parsing `item.note` back apart. `note` can carry extra appended text
        // (e.g. an Ingredient Aliases conversion fragment) alongside the review breakdown,
        // which a regex had no reliable way to tell apart from the breakdown itself.
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
      wrap.appendChild(el("div", "sub-group-heading", "Ingredients"));
      if (!regular.length) wrap.appendChild(el("div", "muted", "Nothing here."));
      regular.forEach(function (item) {
        var row = el("div", "checklist-row");
        if (item.already_on_anylist) row.classList.add("on-anylist");

        var main = el("div", "main");
        main.appendChild(el("div", "name", item.ingredient_name));
        main.appendChild(el("div", "meta", qtyText(item)));
        row.appendChild(main);

        var tap = el("button", "have-toggle have-" + item.have_it, HAVE_LABEL[item.have_it]);
        tap.addEventListener("click", function () {
          var next = HAVE_NEXT[item.have_it] || "unknown";
          patchItem(item, { have_it: next, add_to_list: next === "no" }, function () {
            tap.textContent = HAVE_LABEL[item.have_it];
            tap.className = "have-toggle have-" + item.have_it;
          });
        });
        row.appendChild(tap);
        wrap.appendChild(row);
      });
      return wrap;
    }

    // --- staples ---
    function staplesGroup(staples) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Staples used this session"));
      staples.forEach(function (item) {
        var row = el("div", "checklist-row");
        var label = el("label", "ing-swap-remember");
        var cb = el("input"); cb.type = "checkbox"; cb.checked = !!item.add_to_list;
        cb.addEventListener("change", function () {
          patchItem(item, { add_to_list: cb.checked });
        });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(" " + item.ingredient_name + " — add to list"));
        row.appendChild(label);
        if (item.already_on_anylist) row.appendChild(el("span", "muted", " (already on AnyList)"));
        wrap.appendChild(row);
      });
      return wrap;
    }

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
  }

  global.ChecklistView = { mount: mount, unmount: unmount };
})(window);
