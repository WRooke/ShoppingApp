/* Checklist screen — the "push to AnyList" summary line, sticky button, progress tracker and
   result. Split out of checklist.js per CLAUDE.md > Code Architecture & Maintainability > file
   size discipline.

   Rewritten 2026-10-06 (Chunk 6.7) to the approved mockups (docs/mockups/chunk-6.7/push.html);
   behaviour and verification: docs/anylist-push.md. What you see, in order:

     idle      "N ingredient(s) will go on the list." + the Push button
     pushing   four stages — Reading your list -> Sending (n of N) -> Confirming -> Done — and one
               row per line, addressed by checklist-row key (the server reports "item:<id>"/
               "usual:<id>" with the display name as `label`; matching by display name never lined
               up). "Confirming" is the real read-back of the AnyList list; a line only counts as on
               the list after it passes.
     done      a result card that stays until you leave the screen: "N on your list", counts, and a
               Details list of what happened to each item (added / updated / un-crossed / already
               there). Replaces the 5-second toast.
     problems  "N items need attention": failed items by name with the plain reason, a Try again
               that retries only those (the session isn't marked pushed after a failure, so no
               "already pushed" prompt), never a green tick.
     no AnyList  if the list couldn't even be read, nothing was changed and it says so (error box +
               Try again).

   The "already pushed" question is an inline card (Feedback.card), not a native confirm(). */

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

  // The lines about to be pushed, as {key, label}. `key` is the SAME row key the server uses for
  // its progress steps ("item:<row id>" / "usual:<id>"); `label` is only what is shown.
  function pushLines(pushUsualIds, items, usuals) {
    var lines = items
      .filter(function (i) { return i.add_to_list || i.have_it === "no"; })
      .map(function (i) { return { key: "item:" + i.id, label: i.display_name || i.ingredient_name }; });
    usuals
      .filter(function (u) { return pushUsualIds[u.id]; })
      .forEach(function (u) { lines.push({ key: "usual:" + u.id, label: u.name }); });
    return lines;
  }

  // ---- stages ----

  var STAGE_NAMES = ["Reading your list", "Sending", "Confirming", "Done"];

  function stageStates(stage) {
    switch (stage) {
      case "sending": return ["done", "active", "", ""];
      case "confirming": return ["done", "done", "active", ""];
      case "done": return ["done", "done", "done", "done"];
      case "needs-attention": return ["done", "done", "done", "failed"];
      default: return ["active", "", "", ""]; // "reading", or not known yet
    }
  }

  function renderStages(list, stage, sentCount, total) {
    var states = stageStates(stage);
    list.innerHTML = "";
    STAGE_NAMES.forEach(function (name, i) {
      var li = el("li", states[i]);
      li.appendChild(document.createTextNode(name));
      if (i === 1 && stage === "sending" && total) {
        li.appendChild(document.createTextNode(" "));
        li.appendChild(el("span", "count", sentCount + " of " + total));
      }
      list.appendChild(li);
    });
  }

  // ---- result ----

  var OUTCOME_LABEL = {
    "added": "added", "updated": "updated", "un-crossed": "un-crossed",
    "already-active": "already there", "failed": "failed",
  };
  var OUTCOME_CLASS = {
    "added": "added", "updated": "updated", "un-crossed": "uncrossed",
    "already-active": "", "failed": "failed",
  };

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function resultList(items, onlyFailed) {
    var ul = el("ul", "result-list");
    items.forEach(function (it) {
      if (onlyFailed && it.outcome !== "failed") return;
      var li = el("li");
      li.appendChild(el("span", null, it.name));
      li.appendChild(el("span", "chip-out " + (OUTCOME_CLASS[it.outcome] || ""), OUTCOME_LABEL[it.outcome] || it.outcome));
      if (it.reason) li.appendChild(el("span", "why", it.reason));
      ul.appendChild(li);
    });
    return ul;
  }

  function counts(res) {
    var c = { added: 0, updated: 0, uncrossed: 0, already: 0, failed: 0 };
    (res.items || []).forEach(function (it) {
      if (it.outcome === "added") c.added++;
      else if (it.outcome === "updated") c.updated++;
      else if (it.outcome === "un-crossed") { c.updated++; c.uncrossed++; }
      else if (it.outcome === "already-active") c.already++;
      else if (it.outcome === "failed") c.failed++;
    });
    return c;
  }

  // The result card for a settled push (res = the POST /push response).
  function renderResult(res, onRetry) {
    var items = res.items || [];
    var c = counts(res);
    var total = items.length;
    var onList = total - c.failed;
    var bad = c.failed > 0;
    var open = false;

    var box = el("div", "push-result" + (bad ? " warn" : ""));
    box.setAttribute("role", bad ? "alert" : "status");
    box.appendChild(el("span", "ico", bad ? "⚠️" : "✓"));
    var body = el("div", "body");
    body.appendChild(el("div", "title", bad ? plural(c.failed, "item") + " need" + (c.failed === 1 ? "s" : "") + " attention" : onList + " on your list"));

    var parts = [];
    if (c.added) parts.push(c.added + " added");
    if (c.updated) parts.push(c.updated + " updated" + (c.uncrossed ? " (" + c.uncrossed + " un-crossed)" : ""));
    if (c.already) parts.push(c.already + " already there");
    body.appendChild(el("div", "sub", bad ? "The other " + onList + " " + (onList === 1 ? "is" : "are") + " on your list." : parts.join(" · ")));

    var listSlot = el("div");
    body.appendChild(listSlot);
    box.appendChild(body);

    var toggle = el("button", bad ? "btn-sm" : "btn-link", "Details ▾");
    toggle.type = "button";

    function paint() {
      listSlot.innerHTML = "";
      if (bad) listSlot.appendChild(resultList(items, !open));
      else if (open) listSlot.appendChild(resultList(items, false));
      toggle.textContent = open ? (bad ? "Hide details ▴" : "Hide ▴") : "Details ▾";
    }

    toggle.addEventListener("click", function () { open = !open; paint(); });
    if (bad) {
      var actions = el("div", "actions");
      var retry = el("button", "primary btn-sm", "Try again");
      retry.type = "button";
      retry.addEventListener("click", onRetry);
      actions.appendChild(retry);
      actions.appendChild(toggle);
      body.appendChild(actions);
    } else {
      box.appendChild(toggle);
    }
    paint();
    return box;
  }

  // opts: { sessionId, items, usuals, pushUsualIds, lastPush, onResult(res), onReload() }
  // `lastPush` is the previous push's response (kept by checklist.js across the reload a push
  // triggers) and is shown as the result card; onResult receives each settled push so the caller
  // can keep it; onReload refreshes the checklist from the server afterwards.
  function renderSummary(opts) {
    var wrap = el("div");
    wrap.style.marginTop = "12px";
    var line = el("div", "muted");
    wrap.appendChild(line);
    var actions = el("div", "sticky-actions");
    var pushBtn = el("button", "primary btn-block", "Push to AnyList");
    pushBtn.addEventListener("click", function () { doPush(false); });
    actions.appendChild(pushBtn);
    wrap.appendChild(actions);
    var stepsSlot = el("div"); // stages + per-line rows while pushing; errors/questions after
    wrap.appendChild(stepsSlot);
    var resultSlot = el("div");
    wrap.appendChild(resultSlot);

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

    if (opts.lastPush) resultSlot.appendChild(renderResult(opts.lastPush, function () { doPush(false); }));

    function resetButton() {
      pushBtn.disabled = false;
      pushBtn.innerHTML = "";
      pushBtn.textContent = "Push to AnyList";
    }

    function doPush(force) {
      pushBtn.disabled = true;
      global.Feedback.clear(stepsSlot);
      stepsSlot.innerHTML = "";
      resultSlot.innerHTML = "";
      var lines = pushLines(opts.pushUsualIds, opts.items, opts.usuals);
      var token = makeToken();

      pushBtn.innerHTML = "";
      pushBtn.appendChild(el("span", "spinner"));
      pushBtn.appendChild(document.createTextNode(" Pushing…"));

      var stageList = el("ol", "push-stages");
      var stepsScroll = el("div", "push-steps");
      var stepsWrap = el("div", "step-list-vertical");
      stepsScroll.appendChild(stepsWrap);
      var note = el("div", "push-note");
      note.hidden = true;
      note.appendChild(el("span", "spinner"));
      note.appendChild(document.createTextNode(" Checking AnyList has everything…"));
      stepsSlot.appendChild(stageList);
      if (lines.length) stepsSlot.appendChild(stepsScroll);
      stepsSlot.appendChild(note);

      var rows = {};
      lines.forEach(function (ln) {
        var row = el("div", "step-row");
        var icon = el("div", "step-icon pending");
        var label = el("div", "step-label pending", ln.label);
        row.appendChild(icon);
        row.appendChild(label);
        stepsWrap.appendChild(row);
        rows[ln.key] = { icon: icon, label: label, row: row, status: "pending" };
      });
      var stage = "reading";
      renderStages(stageList, stage, 0, lines.length);

      function applyProgress(data) {
        var sent = 0;
        (data.steps || []).forEach(function (s) {
          var row = rows[s.name];
          if (!row) return;
          if (s.label) row.label.textContent = s.label;
          row.icon.className = "step-icon " + s.status;
          row.icon.textContent = s.status === "done" ? "✓" : s.status === "failed" ? "✕" : "";
          row.label.className = "step-label " + s.status;
          if (s.status === "done" || s.status === "failed") sent++;
          if (s.status === "active" && row.status !== "active") {
            // keep the line being sent in view inside the short scrolling list
            stepsScroll.scrollTop = Math.max(0, row.row.offsetTop - stepsScroll.clientHeight + row.row.offsetHeight);
          }
          row.status = s.status;
        });
        stage = data.stage || stage;
        renderStages(stageList, stage, sent, lines.length);
        note.hidden = stage !== "confirming";
      }

      activePushTimer = global.setInterval(function () {
        api.checklist
          .pushProgress(token)
          .then(applyProgress)
          .catch(function () {
            // 404 until the backend has registered the token — expected right at the very start,
            // just keep polling.
          });
      }, 500);

      function stopProgress() {
        if (activePushTimer) {
          global.clearInterval(activePushTimer);
          activePushTimer = null;
        }
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
          opts.onResult(res); // checklist.js keeps it and re-renders, which shows the result card
          opts.onReload();
        })
        .catch(function (err) {
          stopProgress();
          resetButton();
          stepsSlot.innerHTML = "";
          if (err.code === "SESSION_ALREADY_PUSHED") {
            // Not a native confirm(): an inline card, in plain words, buttons named for what they do.
            global.Feedback.card(stepsSlot, {
              into: true,
              tone: "warn",
              title: "Already pushed to AnyList",
              body:
                "Pushing again checks the list and only changes what's different — items already " +
                "there are left alone.",
              confirmLabel: "Push again",
              cancelLabel: "Not now",
              onConfirm: function () { doPush(true); },
            });
            return;
          }
          // The list couldn't even be read (or the server couldn't be reached): nothing was changed.
          global.Feedback.error(
            stepsSlot,
            "Couldn't push to AnyList. Nothing was changed. (" + global.Feedback.messageOf(err) + ")",
            { box: true, retry: function () { doPush(false); }, retryLabel: "Try again" }
          );
        });
    }

    return { el: wrap, refresh: update };
  }

  global.ChecklistPush = {
    renderSummary: renderSummary,
    renderResult: renderResult,
    unmount: unmount,
  };
})(window);
