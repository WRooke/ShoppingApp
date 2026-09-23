/* Checklist screen — the "push to AnyList" summary line, sticky button, real per-item
   progress list, and discrepancy banner. Split out of checklist.js per CLAUDE.md > Code
   Architecture & Maintainability > file size discipline (checklist.js passed ~400 lines once
   Chunk 6.3b's design-system pass + the stock-check/push-progress/discrepancy additions all
   landed in one file).

   Phase 6 Chunk 6.3b built a "Pushing…" state that cycled through the actual item names via
   a client-side timer — an honest-looking simulation, not real backend signal. 2026-09-23:
   replaced with real per-item progress, polled from GET /checklist/push/progress/{token}
   (app/services/progress_tracker.py, written to by anylist_client.py's on_item callback as
   it actually works through the batch) — the same real-step approach capture.js's
   startProgress() uses for the AI capture calls. Also a discrepancy warning banner when a
   push comes back with confirmed: false — see checklist.js's own header comment for why that
   banner has to survive the load() a push triggers. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function makeToken() {
    if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
    return "t-" + Date.now() + "-" + Math.random().toString(36).slice(2);
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
    var stepsSlot = el("div");
    wrap.appendChild(stepsSlot);

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
      var token = makeToken();

      pushBtn.innerHTML = "";
      pushBtn.appendChild(el("span", "spinner"));
      pushBtn.appendChild(document.createTextNode(" Pushing…"));

      var rows = {};
      stepsSlot.innerHTML = "";
      if (names.length) {
        var stepsWrap = el("div", "step-list-vertical");
        names.forEach(function (name) {
          var row = el("div", "step-row");
          var icon = el("div", "step-icon pending");
          var label = el("div", "step-label pending", "Adding " + name + "…");
          row.appendChild(icon);
          row.appendChild(label);
          stepsWrap.appendChild(row);
          rows[name] = { icon: icon, label: label, name: name };
        });
        stepsSlot.appendChild(stepsWrap);
        pushNote.hidden = false;
        pushNote.textContent = "0 of " + names.length + " confirmed";
      }

      function applyProgress(steps) {
        var doneCount = 0;
        (steps || []).forEach(function (s) {
          var row = rows[s.name];
          if (!row) return;
          row.icon.className = "step-icon " + s.status;
          row.icon.textContent = s.status === "done" ? "✓" : s.status === "failed" ? "✕" : "";
          row.label.className = "step-label " + s.status;
          row.label.textContent =
            (s.status === "done" ? "Added " : s.status === "failed" ? "Couldn't add " : "Adding ") +
            s.name +
            (s.status === "done" || s.status === "failed" ? "" : "…");
          if (s.status === "done") doneCount++;
        });
        if (names.length) pushNote.textContent = doneCount + " of " + names.length + " confirmed";
        return steps;
      }

      activePushTimer = names.length
        ? global.setInterval(function () {
            api.checklist
              .pushProgress(token)
              .then(function (res) {
                applyProgress(res.steps);
              })
              .catch(function () {
                // 404 until the backend's first on_item("active") call actually lands —
                // expected right at the very start, just keep polling.
              });
          }, 500)
        : null;

      function stopProgress() {
        if (activePushTimer) {
          global.clearInterval(activePushTimer);
          activePushTimer = null;
        }
        pushNote.hidden = true;
      }

      api.checklist
        .push(opts.sessionId, {
          force: force,
          usualIds: Object.keys(opts.pushUsualIds).map(Number),
          progressToken: token,
        })
        .then(function (res) {
          stopProgress();
          stepsSlot.innerHTML = "";
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
            stepsSlot.innerHTML = "";
            if (
              global.confirm(
                "This session was already pushed. Push again? Items AnyList still recognises " +
                  "will just have their quantity updated — anything it can no longer match " +
                  "will be added as a new line, which could be a duplicate."
              )
            )
              doPush(true);
            return;
          }
          // Which item was actually in flight when the whole push died (CLAUDE.md > UI/UX >
          // Real progress indicators — "the UI must show which specific stage failed"): one
          // last progress fetch, then mark whichever row never reached "done" as the culprit
          // — anylist_client.py's on_item callback only ever reports "active"/"done" (see its
          // docstring), so a row stuck on "active" here is exactly the one mid-flight when
          // the surrounding request raised.
          if (names.length) {
            api.checklist
              .pushProgress(token)
              .then(function (res) {
                var steps = applyProgress(res.steps);
                var stuck = (steps || []).find(function (s) { return s.status === "active"; });
                if (stuck) {
                  var row = rows[stuck.name];
                  row.icon.className = "step-icon failed";
                  row.icon.textContent = "✕";
                  row.label.className = "step-label failed";
                  row.label.textContent = "Couldn't add " + stuck.name;
                }
              })
              .catch(function () {})
              .then(function () {
                global.alert("Push failed: " + err.message);
              });
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
