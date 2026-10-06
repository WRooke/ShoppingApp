/* Client auto-update notification — docs/ui-ux.md > Client auto-update notification, and
   docs/deployment-and-operations.md > "How an open phone learns the NUC was updated".
   App-shell level, like toast.js/nav-badges.js — mounted once in index.html.

   WHAT IT DOES: the NUC gets updated (update.bat pulls new code and restarts the server); a phone
   that already has the app open can't know. This shows a persistent "Update available — tap to
   refresh" so the user decides when to reload (never a forced reload — that could interrupt a
   capture or checklist edit), and the reload really does fetch the new code.

   Deliberately NOT the shared Toast: Toast auto-dismisses after 5s and is torn down by router.js
   on every hashchange — both wrong here; an update notice must persist until acted on.

   HOW (rewritten 2026-10-06 — the first version never fired in practice):
   * The BASELINE is the build id of the assets this page was actually served: the server stamps
     it into index.html as <meta name="app-build"> (app/main.py > index()). It used to be "whatever
     /health said on first load", which is wrong whenever the page is restored from cache after
     the server has already been updated (the common phone case): the stale page adopted the NEW
     build as its baseline and never noticed it was old.
   * It then compares /api/v1/health's build_id (a hash of the code, app/services/version.py)
     with that baseline. Different => the server runs newer code than this page.
   * It checks when it can actually be noticed, not only on a timer a phone may have frozen: on
     load, when the tab becomes visible, on pageshow (back/forward cache), when the network
     returns, on focus, on navigation (throttled), and every CHECK_VISIBLE_MS while visible. A
     check that fails (the server is mid-restart for ~10s) is retried at 5/10/20s instead of
     waiting for the next tick.
   * "Update pending" is kept in sessionStorage, so the banner survives a reload that did not pick
     up the new code, and the tap can tell the user honestly when an update "didn't load".
   * Tapping navigates to ?b=<new build>: a fresh document request (index.html is no-cache) whose
     asset URLs carry the new build (?v=), so every script and stylesheet is fetched fresh, not
     served from a heuristic cache.

   If the page was served without a stamp (opened from disk, or an old server) it degrades to the
   previous behaviour: the first successful health check becomes the baseline. */

(function (global) {
  "use strict";

  var CHECK_VISIBLE_MS = 90 * 1000; // while the tab is visible
  var MIN_GAP_MS = 5 * 1000; // coalesces visibility+focus+pageshow firing together
  var NAV_GAP_MS = 30 * 1000; // hashchange checks, at most this often
  var TIMEOUT_MS = 8 * 1000;
  var RETRY_DELAYS_MS = [5000, 10000, 20000];
  var PENDING_KEY = "updatePendingBuild";
  var ATTEMPT_KEY = "updateAttempt";

  var baseline = readStamp();
  var bannerEl = null;
  var state = { status: "idle", target: null };
  var lastCheckAt = 0;
  var lastNavCheckAt = 0;
  var inFlight = false;
  var retryIndex = 0;
  var retryTimer = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function readStamp() {
    var meta = document.querySelector('meta[name="app-build"]');
    var v = meta && meta.getAttribute("content");
    return v && v !== "__BUILD__" ? v : null;
  }

  function store(key, value) {
    try {
      if (value == null) global.sessionStorage.removeItem(key);
      else global.sessionStorage.setItem(key, value);
    } catch (_) { /* private mode etc.: the banner just won't survive a reload */ }
  }
  function load(key) {
    try { return global.sessionStorage.getItem(key); } catch (_) { return null; }
  }
  function attempts(target) {
    try {
      var a = JSON.parse(load(ATTEMPT_KEY) || "null");
      return a && a.target === target ? a.n : 0;
    } catch (_) { return 0; }
  }

  // ---- banner ----

  function labels() {
    return state.status === "failed"
      ? ["Update didn't load", "Tap to try again"]
      : ["Update available", "Tap to refresh"];
  }

  function render() {
    var text = labels();
    if (!bannerEl) {
      bannerEl = el("div", "update-banner");
      bannerEl.setAttribute("role", "button");
      bannerEl.setAttribute("tabindex", "0");
      bannerEl.setAttribute("aria-live", "polite");
      bannerEl.appendChild(el("span", "ico", "🔄"));
      bannerEl.appendChild(el("span", "msg"));
      bannerEl.appendChild(el("span", "cta"));
      bannerEl.addEventListener("click", refresh);
      bannerEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); refresh(); }
      });
      document.body.insertBefore(bannerEl, document.body.firstChild);
    }
    bannerEl.querySelector(".msg").textContent = text[0];
    bannerEl.querySelector(".cta").textContent = text[1];
    // Push the page down by the banner's real height (it is position:fixed, so it would
    // otherwise cover the header title) — see components.css .has-update-banner.
    document.body.classList.add("has-update-banner");
    document.documentElement.style.setProperty("--update-banner-h", bannerEl.offsetHeight + "px");
  }

  function refresh() {
    var target = state.target;
    if (!target) { global.location.reload(); return; }
    store(ATTEMPT_KEY, JSON.stringify({ target: target, n: attempts(target) + 1 }));
    global.location.assign(global.location.pathname + "?b=" + encodeURIComponent(target) + global.location.hash);
  }

  function setAvailable(target) {
    state.target = target;
    store(PENDING_KEY, target);
    state.status = attempts(target) > 0 ? "failed" : "available";
    render();
  }

  // ---- checking ----

  function fetchBuild() {
    var controller = global.AbortController ? new global.AbortController() : null;
    var timer = global.setTimeout(function () { if (controller) controller.abort(); }, TIMEOUT_MS);
    return global
      .fetch("/api/v1/health", { cache: "no-store", signal: controller ? controller.signal : undefined })
      .then(function (r) {
        global.clearTimeout(timer);
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (body) {
        var d = body && body.data;
        return d && (d.build_id || d.version);
      });
  }

  function checkNow(force) {
    var now = Date.now();
    if (inFlight) return;
    if (force !== true && now - lastCheckAt < MIN_GAP_MS) return;
    lastCheckAt = now;
    inFlight = true;
    fetchBuild()
      .then(function (build) {
        inFlight = false;
        retryIndex = 0;
        if (!build) return;
        if (baseline === null) {
          baseline = build; // unstamped page: degrade to "first answer is the baseline"
        } else if (build !== baseline) {
          setAvailable(build);
        }
      })
      .catch(function (err) {
        inFlight = false;
        if (global.console && global.console.warn) {
          global.console.warn("update check failed:", err && err.message ? err.message : err);
        }
        if (retryIndex < RETRY_DELAYS_MS.length) {
          var delay = RETRY_DELAYS_MS[retryIndex++];
          global.clearTimeout(retryTimer);
          retryTimer = global.setTimeout(function () { checkNow(true); }, delay);
        }
      });
  }

  // ---- startup ----

  (function init() {
    // A previous reload may not have brought the new code: remember that across the reload.
    var pending = load(PENDING_KEY);
    if (pending && baseline && pending !== baseline) {
      state.target = pending;
      state.status = attempts(pending) > 0 ? "failed" : "available";
      render();
    } else if (pending && baseline && pending === baseline) {
      store(PENDING_KEY, null); // the update took
      store(ATTEMPT_KEY, null);
    }
    // Tidy the ?b= we navigated with out of the address bar (keeps the hash route intact).
    if (/[?&]b=/.test(global.location.search) && global.history && global.history.replaceState) {
      global.history.replaceState(null, "", global.location.pathname + global.location.hash);
    }
  })();

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") checkNow(false);
  });
  global.addEventListener("pageshow", function (e) { checkNow(e && e.persisted === true); });
  global.addEventListener("online", function () { checkNow(true); });
  global.addEventListener("focus", function () { checkNow(false); });
  global.addEventListener("hashchange", function () {
    var now = Date.now();
    if (now - lastNavCheckAt < NAV_GAP_MS) return;
    lastNavCheckAt = now;
    checkNow(false);
  });
  global.setInterval(function () {
    if (document.visibilityState === "visible") checkNow(false);
  }, CHECK_VISIBLE_MS);

  checkNow(true);

  // Exposed for tests (tests/frontend) and for debugging from the phone's console.
  global.UpdateBanner = {
    checkNow: function () { checkNow(true); },
    getLoadedVersion: function () { return baseline; }, // the build id this page was served with
    getState: function () { return { status: state.status, target: state.target, baseline: baseline }; },
  };
})(window);
