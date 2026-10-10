/* Sends the browser's own errors to the server log (POST /api/v1/client-log).

   Until now a script error, a failed request or an unhandled promise rejection on the phone left no
   trace anywhere the maintainer could read — Diagnostics only knew what reached the server. These
   show up in Diagnostics > Recent errors under the "app.client" logger
   (docs/diagnostics-and-logging.md > Browser errors).

   Deliberately dull and defensive: reporting must never itself throw, never recurse, never write to
   the console (the test suite asserts the console stays clean), and never flood — at most
   MAX_PER_PAGE reports per page load, each distinct kind+message once. The server rate-limits too. */

(function (global) {
  "use strict";

  var MAX_PER_PAGE = 10;
  var sent = 0;
  var seen = {};

  function buildId() {
    try {
      var meta = document.querySelector("meta[name=app-build]");
      return meta ? meta.getAttribute("content") : null;
    } catch (_) {
      return null;
    }
  }

  function report(kind, message, stack) {
    try {
      var text = String(message == null ? "" : message).slice(0, 500);
      var key = kind + "|" + text;
      if (sent >= MAX_PER_PAGE || seen[key]) return;
      seen[key] = true;
      sent++;
      var payload = JSON.stringify({
        kind: kind,
        message: text,
        stack: stack ? String(stack).slice(0, 4000) : null,
        url: global.location.pathname + global.location.hash,
        build: buildId(),
      });
      // keepalive so a report sent as the page is being torn down still goes out. Any failure is
      // swallowed: there is nowhere left to report a failure of the reporter.
      global
        .fetch("/api/v1/client-log", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload,
          keepalive: true,
        })
        .catch(function () {});
    } catch (_) {
      /* never throw from the reporter */
    }
  }

  // A rejected promise somebody swallowed with `.catch(function () {})`. ApiErrors are skipped:
  // the server already logged (or answered) those, so reporting them again would only be noise.
  function reportCaught(context, err) {
    if (err && err.name === "ApiError") return;
    report("error", context + ": " + (err && err.message ? err.message : err), err && err.stack);
  }

  global.addEventListener("error", function (e) {
    if (!e || e.target !== global) return; // element load errors (img/script) are not script errors
    var where = e.filename ? " (" + String(e.filename).split("/").pop() + ":" + e.lineno + ")" : "";
    report("error", (e.message || "script error") + where, e.error && e.error.stack);
  });

  global.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    if (r && r.name === "ApiError") return; // already logged server-side / shown inline
    report(
      "unhandledrejection",
      "Unhandled promise rejection: " + (r && r.message ? r.message : r),
      r && r.stack
    );
  });

  global.ErrorReport = { report: report, reportCaught: reportCaught };
})(window);
