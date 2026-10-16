/* Checklist — live updates between phones (2026-10-16, Chunk 6.7, user-feedback batch polish batch 3).

   Two people can have the same checklist open. When one taps Need it, the other sees it within
   about a second, without anyone pressing refresh. How: the phone holds ONE request open
   (GET /checklist/{id}/changes, a long-poll, up to ~25 s); the server answers the moment the
   plan's revision number changes. An idle phone therefore makes 2-3 requests a minute, which
   costs less battery than polling every few seconds. Nothing is requested while the page is
   hidden. On a change the phone does one cheap re-read (GET /checklist/{id}/items) that never
   touches AnyList.

   Applying a remote update must never destroy what the person is doing (docs/ui-ux.md > UI
   state must not silently vanish): while `isBusy()` is true (a panel open, a field being typed
   in, a save in flight, merge mode) the update is HELD and applied the moment they finish.

   Our own edits also bump the revision, so the re-read usually matches what is already on
   screen; only rows that actually differ are re-rendered and highlighted. See
   docs/checklist-and-shopping.md > Live updates between phones. */

(function (global) {
  "use strict";

  var POLL_TIMEOUT_MS = 35000; // server holds ~25 s; this only catches a dead connection
  var BACKOFF_MS = [2000, 5000, 15000];
  var HELD_RECHECK_MS = 500;
  // Fields whose change makes a row "different" for highlighting; a row's other fields (breakdown,
  // timestamps) change on every consolidation without the person having done anything.
  var WATCHED = [
    "ingredient_name", "have_it", "add_to_list", "total_quantity", "total_unit", "have_quantity",
    "display_qty", "note", "needs_review", "purchase_label", "already_on_anylist",
  ];

  function rowKey(item) {
    return JSON.stringify(
      WATCHED.map(function (k) {
        return item[k];
      })
    );
  }

  // Names of rows that are new or differ between what is on screen and what the server now has;
  // plus whether anything at all differs (a removed row, or the usuals).
  function diff(current, incoming, curUsuals, newUsuals) {
    var before = {};
    (current || []).forEach(function (i) { before[i.ingredient_name] = rowKey(i); });
    var seen = {};
    var changed = [];
    (incoming || []).forEach(function (i) {
      seen[i.ingredient_name] = true;
      if (before[i.ingredient_name] !== rowKey(i)) changed.push(i.ingredient_name);
    });
    var removed = Object.keys(before).some(function (n) { return !seen[n]; });
    var usualsDiffer = newUsuals && JSON.stringify(newUsuals) !== JSON.stringify(curUsuals || []);
    return { changed: changed, any: changed.length > 0 || removed || !!usualsDiffer };
  }

  // opts: sessionId, epoch, rev, getItems(), getUsuals(), isBusy(), apply(items, usuals, changedNames),
  //       onHeld(bool)
  function start(opts) {
    var epoch = opts.epoch;
    var rev = opts.rev;
    var stopped = false;
    var pending = null; // a re-read waiting for the person to finish what they are doing
    var heldTimer = null;
    var pollAbort = null;
    var failures = 0;
    var base = "/api/v1/checklist/" + encodeURIComponent(opts.sessionId);

    function remember(data) {
      epoch = data.epoch;
      rev = data.rev;
    }

    function applyNow(data) {
      var d = diff(opts.getItems(), data.items, opts.getUsuals(), data.usuals);
      if (opts.onHeld) opts.onHeld(false);
      if (d.any) opts.apply(data.items, data.usuals, d.changed);
    }

    function considerPending() {
      if (stopped || !pending) return;
      if (opts.isBusy()) {
        if (!heldTimer) heldTimer = setInterval(considerPending, HELD_RECHECK_MS);
        return;
      }
      if (heldTimer) { clearInterval(heldTimer); heldTimer = null; }
      var data = pending;
      pending = null;
      applyNow(data);
    }

    function reread() {
      return api.get(base + "/items").then(function (data) {
        if (stopped) return;
        remember(data);
        var d = diff(opts.getItems(), data.items, opts.getUsuals(), data.usuals);
        if (!d.any) return; // our own edit coming back round
        pending = data;
        if (opts.isBusy() && opts.onHeld) opts.onHeld(true);
        considerPending();
      });
    }

    function wait(ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    // Each loop() starts a new generation; an older loop notices it has been replaced (a resume
    // aborted its request) and quietly ends, so there is never more than one request in flight.
    var generation = 0;

    function loop() {
      if (stopped) return;
      var mine = ++generation;
      (function step() {
        if (stopped || mine !== generation) return;
        if (document.hidden) return; // resumed by visibilitychange
        var abort = typeof AbortController === "function" ? new AbortController() : null;
        pollAbort = abort;
        var killer = setTimeout(function () { if (abort) abort.abort(); }, POLL_TIMEOUT_MS);
        fetch(base + "/changes?epoch=" + encodeURIComponent(epoch) + "&rev=" + encodeURIComponent(rev), {
          cache: "no-store",
          signal: abort ? abort.signal : undefined,
        })
          .then(function (res) { return res.json(); })
          .then(function (body) {
            clearTimeout(killer);
            if (stopped || mine !== generation) return;
            if (!body || body.ok !== true) throw new Error("bad response");
            failures = 0;
            if (body.data.changed) return reread(); // reread() moves epoch/rev forward
          })
          .catch(function () {
            clearTimeout(killer);
            if (stopped || mine !== generation) return;
            // A failed background poll never shows an error: the phone may be asleep or the server
            // restarting for an update. Back off and try again.
            var delay = BACKOFF_MS[Math.min(failures, BACKOFF_MS.length - 1)];
            failures++;
            return wait(delay);
          })
          .then(step);
      })();
    }

    function resume() {
      if (stopped || document.hidden) return;
      // Whatever happened while the page was hidden or offline: one cheap re-read, then listen.
      if (pollAbort) pollAbort.abort();
      generation++; // retire the old loop before starting the new one
      reread().catch(function () {}).then(loop);
    }

    function onVisibility() { if (!document.hidden) resume(); }
    document.addEventListener("visibilitychange", onVisibility);
    global.addEventListener("pageshow", resume);
    global.addEventListener("online", resume);
    loop();

    return {
      // A full load() just ran: its revision is the new baseline.
      reset: function (newEpoch, newRev) { epoch = newEpoch; rev = newRev; pending = null; if (opts.onHeld) opts.onHeld(false); },
      // The person finished what they were doing (closed a panel, saved a field).
      settled: considerPending,
      stop: function () {
        stopped = true;
        if (pollAbort) pollAbort.abort();
        if (heldTimer) clearInterval(heldTimer);
        document.removeEventListener("visibilitychange", onVisibility);
        global.removeEventListener("pageshow", resume);
        global.removeEventListener("online", resume);
      },
    };
  }

  global.ChecklistLive = { start: start, diff: diff };
})(window);
