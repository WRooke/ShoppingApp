/* Checklist screen — the "push to AnyList" summary line, sticky button, rotating
   per-item progress label, and discrepancy banner. Split out of checklist.js per CLAUDE.md
   > Code Architecture & Maintainability > file size discipline (checklist.js passed ~400
   lines once Chunk 6.3b's design-system pass + the stock-check/push-progress/discrepancy
   additions all landed in one file).

   Phase 6 Chunk 6.3b: a "Pushing…" state that cycles through the actual item names being
   pushed (mockup sign-off, 2026-09-20 — a static spinner "doesn't fill me with confidence
   anything's happening"), grounded in the real push list rather than invented phase labels,
   the same "one HTTP request, no real per-step signal" situation capture.js's
   startProgress() already solves for the AI capture calls. Also a discrepancy warning
   banner when a push comes back with confirmed: false — see checklist.js's own header
   comment for why that banner has to survive the load() a push triggers. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // Module-level, not per-render — checklist.js's unmount() calls ChecklistPush.unmount() to
  // tear down whichever instance is currently mounted; a timer declared inside renderSummary's
  // own closure would be unreachable from there.
  var activePushTimer = null;

  function unmount() {
    if (activePushTimer) {
      global.clearInterval(activePushTimer);
      activePushTimer = null;
    }
  }

  function renderDiscrepancyBanner(discrepancies) {
    var box = el("div", "push-discrepancy");
    box.appendChild(el("span", "ico", "⚠️"));
    var b = el("div", "body");
    b.appendChild(el("div", "title", "Pushed, but not fully confirmed"));
    b.appendChild(
      document.createTextNode(
        "AnyList didn't recognise these after the push — check the app in case they were added as new lines:"
      )
    );
    var ul = el("ul");
    discrepancies.forEach(function (d) { ul.appendChild(el("li", null, String(d))); });
    b.appendChild(ul);
    box.appendChild(b);
    return box;
  }

  function pushItemNames(pushUsualIds, items, usuals) {
    var names = items
      .filter(function (i) { return i.add_to_list || i.have_it === "no"; })
      .map(function (i) { return i.ingredient_name; });
    usuals
      .filter(function (u) { return pushUsualIds[u.id]; })
      .forEach(function (u) { names.push(u.name); });
    return names;
  }

  // opts: { sessionId, items, usuals, pushUsualIds, onResult(res), onReload() }
  // onResult receives the raw push response so the caller can decide whether to stash
  // discrepancies for the next render(); onReload is called after every settled push
  // (success or a confirmed discrepancy) to refresh the checklist from the server.
  function renderSummary(opts) {
    var wrap = el("div");
    wrap.style.marginTop = "12px";
    var line = el("div", "muted");
    wrap.appendChild(line);
    var actions = el("div", "sticky-actions");
    var pushBtn = el("button", "primary btn-block", "Push to AnyList");
    var pushNote = el("div", "push-progress-note muted");
    pushNote.hidden = true;
    pushBtn.addEventListener("click", function () {
      doPush(false);
    });
    actions.appendChild(pushBtn);
    actions.appendChild(pushNote);
    wrap.appendChild(actions);

    function update() {
      var toAdd = opts.items.filter(function (i) { return i.add_to_list || i.have_it === "no"; }).length;
      var usualCount = Object.keys(opts.pushUsualIds).length;
      line.textContent =
        toAdd +
        " ingredient(s)" +
        (opts.usuals.length ? " + " + usualCount + " of " + opts.usuals.length + " usual(s) selected" : "") +
        " will go on the list.";
    }
    update();

    function doPush(force) {
      pushBtn.disabled = true;
      var names = pushItemNames(opts.pushUsualIds, opts.items, opts.usuals);

      // Present continuous ("Adding X…"), never past tense — this doesn't claim X has
      // actually landed on AnyList yet, only that it's part of the in-flight batch.
      pushBtn.innerHTML = "";
      pushBtn.appendChild(el("span", "spinner"));
      if (names.length) {
        var i = 0;
        var label = el("span", null, "Adding " + names[0] + "…");
        pushBtn.appendChild(label);
        pushNote.hidden = false;
        pushNote.textContent = "Item 1 of " + names.length;
        activePushTimer = global.setInterval(function () {
          i = (i + 1) % names.length;
          label.textContent = "Adding " + names[i] + "…";
          pushNote.textContent = "Item " + (i + 1) + " of " + names.length;
        }, 1100);
      } else {
        pushBtn.appendChild(document.createTextNode(" Pushing…"));
      }

      function stopProgress() {
        if (activePushTimer) {
          global.clearInterval(activePushTimer);
          activePushTimer = null;
        }
        pushNote.hidden = true;
      }

      api.checklist
        .push(opts.sessionId, { force: force, usualIds: Object.keys(opts.pushUsualIds).map(Number) })
        .then(function (res) {
          stopProgress();
          opts.onResult(res);
          opts.onReload();
        })
        .catch(function (err) {
          stopProgress();
          pushBtn.disabled = false;
          pushBtn.innerHTML = "";
          pushBtn.textContent = "Push to AnyList";
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
              doPush(true);
          } else {
            global.alert("Push failed: " + err.message);
          }
        });
    }

    return { el: wrap, refresh: update };
  }

  global.ChecklistPush = {
    renderSummary: renderSummary,
    renderDiscrepancyBanner: renderDiscrepancyBanner,
    unmount: unmount,
  };
})(window);
