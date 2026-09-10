/* Checklist screen (Phase 5 Chunk 5.5) — #/checklist/<session_id>.

   Walks the consolidated shopping list one item at a time: "do you have this?".
   Items already on AnyList are pre-ticked and shown distinctly. Staples and the due
   "usuals" are their own groups. Irreconcilable-units lines (Chunk 4.6) get an inline
   resolve control. Items you don't have (or explicitly tick "add") are what Chunk 5.6
   pushes to AnyList.

   have_it tap cycle is BINARY: unknown -> yes -> no -> unknown (no 'partial' — see
   CLAUDE.md > Deferred Decisions). Tapping to 'no' also sets add_to_list; back to
   yes/unknown clears it. See CLAUDE.md > Checklist Screen Logic. */

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
    if (item.needs_review) return item.note || "mixed units";
    if (item.display_qty) {
      var s = item.display_qty;
      if (item.total_quantity != null)
        s += " · need ~" + fmtNum(item.total_quantity) + (item.total_unit ? " " + item.total_unit : "");
      return s;
    }
    if (item.total_quantity == null) return item.note || "";
    return fmtNum(item.total_quantity) + (item.total_unit ? " " + item.total_unit : "");
  }

  function fmtNum(n) {
    return n === Math.round(n) ? String(Math.round(n)) : String(Math.round(n * 100) / 100);
  }

  function parseNoteParts(note) {
    // "100 g + 200 ml" -> [{label:"100 g", qty:100, unit:"g"}, ...]
    return (note || "")
      .split(" + ")
      .map(function (p) {
        var m = p.trim().match(/^([0-9]*\.?[0-9]+)\s*(.*)$/);
        if (!m) return null;
        return { label: p.trim(), qty: parseFloat(m[1]), unit: m[2].trim() || null };
      })
      .filter(Boolean);
  }

  function mount(root, sessionId) {
    root.innerHTML = "";
    var pushUsualIds = {}; // id -> true, client-held until Chunk 5.6 push
    // 2026-09-10 hand-testing ("0 items will go on the list" - was wrong): the summary line
    // used to be computed once at render() time and never touched again, so it went stale
    // the moment a tap/checkbox changed have_it, add_to_list, or a usual's selection without
    // a full page reload. Reassigned by summary() below; every state-changing handler calls
    // it so the count stays live. No-op until the first render.
    var refreshSummary = function () {};

    var back = el("a", "btn", "← Back to session");
    back.href = "#/plan/" + sessionId;
    root.appendChild(back);

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Shopping checklist"));
    var statusLine = el("div", "muted", "Loading…");
    card.appendChild(statusLine);
    var body = el("div");
    card.appendChild(body);
    root.appendChild(card);

    load();

    function load() {
      body.textContent = "Loading…";
      api.checklist
        .load(sessionId)
        .then(render)
        .catch(function (err) {
          body.textContent = "";
          statusLine.textContent = "";
          body.appendChild(el("div", "form-error", "Couldn't load the checklist: " + err.message));
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
      statusLine.textContent = data.anylist_ok
        ? "Checked against AnyList — items already on the list are pre-ticked."
        : "⚠ Couldn't reach AnyList (" + (data.anylist_detail || "unknown") + ") — nothing pre-ticked.";

      var items = data.items || [];
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
      body.appendChild(usualsGroup(data.usuals || []));

      body.appendChild(summary(items, data.usuals || []));
    }

    // --- needs-review ---
    function reviewGroup(review) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Needs review — pick one amount"));
      review.forEach(function (item) {
        var row = el("div", "settings-row");
        row.appendChild(el("div", "recipe-row-name", item.ingredient_name));
        row.appendChild(el("div", "recipe-row-meta muted", item.note || "mixed units"));
        parseNoteParts(item.note).forEach(function (part) {
          var btn = el("button", null, "use " + part.label);
          btn.addEventListener("click", function () {
            api.checklist
              .resolveItem(sessionId, item.id, { total_quantity: part.qty, total_unit: part.unit })
              .then(load)
              .catch(function (err) { global.alert(err.message); });
          });
          row.appendChild(btn);
        });
        var mq = el("input"); mq.type = "number"; mq.step = "any"; mq.placeholder = "amount"; mq.className = "ingredient-qty-input";
        var mu = el("input"); mu.type = "text"; mu.placeholder = "unit"; mu.className = "ingredient-unit-input";
        var mb = el("button", "primary", "use this");
        mb.addEventListener("click", function () {
          var q = parseFloat(mq.value);
          if (isNaN(q) || q <= 0) { global.alert("Enter a positive amount."); return; }
          api.checklist
            .resolveItem(sessionId, item.id, { total_quantity: q, total_unit: mu.value.trim() || null })
            .then(load)
            .catch(function (err) { global.alert(err.message); });
        });
        [mq, mu, mb].forEach(function (n) { row.appendChild(n); });
        wrap.appendChild(row);
      });
      return wrap;
    }

    // --- regular items ---
    function itemsGroup(regular) {
      var wrap = el("div");
      wrap.appendChild(el("div", "sub-group-heading", "Ingredients"));
      if (!regular.length) wrap.appendChild(el("div", "muted", "Nothing here."));
      regular.forEach(function (item) {
        var row = el("div", "settings-row");
        if (item.already_on_anylist) row.classList.add("on-anylist");

        var main = el("div");
        main.style.flex = "3 1 200px";
        main.appendChild(el("div", "recipe-row-name", item.ingredient_name));
        main.appendChild(el("div", "recipe-row-meta muted", qtyText(item)));
        if (item.already_on_anylist) main.appendChild(el("div", "recipe-row-meta muted", "already on AnyList"));
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
        var row = el("div", "settings-row");
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

    // --- the usuals ---
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
        var row = el("div", "settings-row");
        var label = el("label", "ing-swap-remember");
        var cb = el("input"); cb.type = "checkbox"; cb.checked = !!pushUsualIds[u.id];
        cb.addEventListener("change", function () {
          if (cb.checked) pushUsualIds[u.id] = true;
          else delete pushUsualIds[u.id];
          refreshSummary(); // client-held state — no server round-trip, so patchItem won't do it
        });
        label.appendChild(cb);
        label.appendChild(
          document.createTextNode(" " + u.name + " (every " + u.cadence_days + " days)")
        );
        row.appendChild(label);
        wrap.appendChild(row);
      });
      return wrap;
    }

    function summary(items, usuals) {
      var wrap = el("div");
      wrap.style.marginTop = "12px";
      var line = el("div", "muted");
      wrap.appendChild(line);
      var pushBtn = el("button", "primary", "Push to AnyList");
      pushBtn.addEventListener("click", function () {
        doPush(false, pushBtn);
      });
      wrap.appendChild(pushBtn);

      function update() {
        var toAdd = items.filter(function (i) { return i.add_to_list || i.have_it === "no"; }).length;
        var usualCount = Object.keys(pushUsualIds).length;
        line.textContent =
          toAdd +
          " ingredient(s)" +
          (usuals.length ? " + " + usualCount + " of " + usuals.length + " usual(s) selected" : "") +
          " will go on the list.";
      }
      refreshSummary = update; // reassigned each render(); every state change calls this
      update();
      return wrap;
    }

    function doPush(force, pushBtn) {
      pushBtn.disabled = true;
      api.checklist
        .push(sessionId, { force: force, usualIds: Object.keys(pushUsualIds).map(Number) })
        .then(function (res) {
          var msg =
            "Pushed. Added " + (res.added || []).length + ", updated " + (res.updated || []).length +
            (res.usuals_added && res.usuals_added.length ? ", + " + res.usuals_added.length + " usual(s)" : "") +
            (res.confirmed ? "." : " — NOT fully confirmed: " + (res.discrepancies || []).join("; "));
          global.alert(msg);
          load();
        })
        .catch(function (err) {
          pushBtn.disabled = false;
          if (err.code === "SESSION_ALREADY_PUSHED") {
            // "It will re-add items" read as "this will duplicate everything" (2026-09-10
            // hand-testing) — in the common case it won't: anything AnyList still recognises
            // just gets its quantity updated in place. The real risk is narrower (an item
            // AnyList can no longer match, e.g. renamed/removed by hand since the last push)
            // and worth naming specifically instead of a blanket "re-add".
            if (
              global.confirm(
                "This session was already pushed. Push again? Items AnyList still recognises " +
                  "will just have their quantity updated — anything it can no longer match " +
                  "will be added as a new line, which could be a duplicate."
              )
            )
              doPush(true, pushBtn);
          } else {
            global.alert("Push failed: " + err.message);
          }
        });
    }
  }

  global.ChecklistView = { mount: mount };
})(window);
