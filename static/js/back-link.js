/* Shared "Back" component — Phase 6 Chunk 6.1 (see CLAUDE.md > UI / UX and
   docs/build-status/phase-6-polish.md kickoff decision #9). Built here as infrastructure;
   Chunks 6.2/6.3/6.4 replace their own files' hardcoded back-destinations
   (capture.js/capture-review.js/recipe-form.js/session-review.js/sessions.js all currently do
   `back.href = "#/fixed-route"`, confirmed while planning this phase — none of them return to
   wherever the user actually came from) with a call to this file. Chunk 6.1 itself has no
   caller yet (Home is the router's root, nothing links back from it).

   Uses history.back() rather than a fixed href: a hash change already pushes a real browser-
   history entry (confirmed — router.js's Router.navigate() and every plain <a href="#/...">
   both go through location.hash), so this correctly returns to the actual previous screen
   instead of one hardcoded guess. Falls back to Home only for a cold deep-link with no prior
   entry in this tab's history, which history.back() alone can't detect — window.history.length
   is the best available signal (1 means this is the first entry in the tab). */

(function (global) {
  "use strict";

  function render(fallbackKey) {
    var el = document.createElement("button");
    el.type = "button";
    el.className = "back-link";
    el.textContent = "← Back";
    el.addEventListener("click", function () {
      if (global.history.length > 1) {
        global.history.back();
      } else if (global.Router) {
        global.Router.navigate(fallbackKey || "home");
      }
    });
    return el;
  }

  global.BackLink = { render: render };
})(window);
