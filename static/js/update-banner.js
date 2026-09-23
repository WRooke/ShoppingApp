/* Client auto-update notification — see CLAUDE.md > UI/UX > Client auto-update notification.
   App-shell level, like toast.js/nav-badges.js — mounted once in index.html, no per-view
   wiring needed.

   Deliberately NOT the shared Toast component: Toast auto-dismisses after 5s and is torn
   down by router.js on every hashchange (kickoff decision #12, Phase 6) — both wrong for
   this: an update notice must persist until the user actually acts on it, across as many
   navigations as it takes them to notice it.

   Mechanism: GET /api/v1/health once on load to record the version this page was served
   with, then poll the same endpoint every POLL_MS and compare. A mismatch means the server
   process has restarted since this page loaded (a NUC update via scripts/update.py) — show
   the banner; tapping it does a plain reload. */

(function (global) {
  "use strict";

  var POLL_MS = 5 * 60 * 1000; // 5 minutes — frequent enough to notice a same-day update
  var loadedVersion = null;
  var bannerEl = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function showBanner() {
    if (bannerEl) return; // already showing
    bannerEl = el("div", "update-banner");
    bannerEl.setAttribute("role", "button");
    bannerEl.setAttribute("tabindex", "0");
    bannerEl.appendChild(el("span", "ico", "🔄"));
    bannerEl.appendChild(el("span", null, "Update available"));
    bannerEl.appendChild(el("span", "cta", "Tap to refresh"));
    function refresh() {
      global.location.reload();
    }
    bannerEl.addEventListener("click", refresh);
    bannerEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") refresh();
    });
    document.body.insertBefore(bannerEl, document.body.firstChild);
  }

  function checkVersion() {
    if (!(global.api && global.api.health)) return;
    global.api
      .health()
      .then(function (res) {
        var version = res && res.version;
        if (!version) return;
        if (loadedVersion === null) {
          loadedVersion = version;
        } else if (version !== loadedVersion) {
          showBanner();
        }
      })
      .catch(function () {
        // Not load-bearing — a failed check just tries again next interval.
      });
  }

  checkVersion();
  global.setInterval(checkVersion, POLL_MS);

  // Exposed for tests (tests/frontend) to trigger a check on demand rather than waiting
  // POLL_MS for real — same precedent as nav-badges.js's NavBadges.refresh. getLoadedVersion()
  // lets a test discover the real version this page loaded with (whatever git describe
  // actually returned) so it can construct a genuine mismatch instead of guessing a value.
  global.UpdateBanner = {
    checkNow: checkVersion,
    getLoadedVersion: function () { return loadedVersion; },
  };
})(window);
