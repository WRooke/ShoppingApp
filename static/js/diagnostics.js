/* Diagnostics view: component status panel, recent errors, live log tail.
   Auto-refreshes every 5 seconds while the view is mounted (CLAUDE.md). */

(function (global) {
  "use strict";

  var REFRESH_MS = 5000;
  var state = {
    timer: null,
    level: "",
    limit: 200,
    lastErrors: [],
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtTime(iso) {
    if (!iso) return "-";
    // Local time, e.g. "11 Oct, 3:15 pm" (the server sends UTC, with or without a zone suffix).
    var raw = String(iso);
    var hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(raw);
    var d = new Date(hasZone ? raw : raw.replace(" ", "T") + "Z");
    if (isNaN(d.getTime())) return raw.replace("T", " ");
    return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  }

  // Push history (Chunk 6.7): which pushes are expanded survives the 5-second auto-refresh that
  // rebuilds this panel. Undefined = default (the newest push opens itself if it had a problem).
  var openPushes = {};
  var anylistCheckText = "";
  var anylistChecking = false;
  var OUTCOME_LABEL = { "added": "added", "updated": "amount changed", "un-crossed": "put back", "already-active": "already on AnyList", "failed": "failed" };
  var OUTCOME_CLASS = { "added": "added", "updated": "updated", "un-crossed": "uncrossed", "already-active": "", "failed": "failed" };

  function pushCountText(p) {
    var c = p.counts || {};
    if (c.failed) return c.failed + " failed";
    return p.confirmed ? "confirmed" : "not confirmed";
  }

  function renderPushHistory(pushes) {
    var wrap = el("div", "push-history");
    wrap.appendChild(el("div", "hdr", "Recent pushes"));
    pushes.forEach(function (p, idx) {
      var bad = !p.confirmed;
      var isOpen = openPushes[p.history_id] !== undefined ? openPushes[p.history_id] : idx === 0 && bad;
      var row = el("div", "history-row" + (isOpen ? " open" : ""));
      var head = el("button", "history-head");
      head.type = "button";
      var main = el("div", "main");
      main.appendChild(el("div", "name", fmtTime(p.pushed_at)));
      main.appendChild(
        el("div", "meta", ((p.items || []).length || "?") + " lines" + (p.push_id ? " · push " + p.push_id : "") + " · session " + p.session_id)
      );
      head.appendChild(main);
      head.appendChild(el("span", "status-pill " + (bad ? "attention" : "confirmed"), pushCountText(p)));
      head.appendChild(el("span", "chev", "›"));
      row.appendChild(head);

      var body = el("div", "history-body");
      if (p.items && p.items.length) {
        var ul = el("ul", "result-list");
        // failures first, then the rest in push order
        p.items.slice().sort(function (a, b) { return (b.outcome === "failed") - (a.outcome === "failed"); }).forEach(function (it) {
          var li = el("li");
          li.appendChild(el("span", null, it.name));
          li.appendChild(el("span", "chip-out " + (OUTCOME_CLASS[it.outcome] || ""), OUTCOME_LABEL[it.outcome] || it.outcome));
          if (it.reason) li.appendChild(el("span", "why", it.reason + (it.retries ? " (retried " + it.retries + "×)" : "")));
          ul.appendChild(li);
        });
        body.appendChild(ul);
        var t = p.timings || {};
        var kv = el("dl", "kv");
        kv.appendChild(el("dt", null, "Timings"));
        kv.appendChild(el("dd", null, "read " + (t.read || 0) + "s · send " + (t.send || 0) + "s · confirm " + (t.confirm || 0) + "s"));
        if (p.push_id) {
          kv.appendChild(el("dt", null, "Log"));
          kv.appendChild(el("dd", null, "grep " + p.push_id + " logs/app.log"));
        }
        body.appendChild(kv);
      } else {
        body.appendChild(el("div", "status-msg", "No per-item detail was recorded for this push (it was made before results were kept)."));
      }
      row.appendChild(body);
      head.addEventListener("click", function () {
        var nowOpen = !row.classList.contains("open");
        row.classList.toggle("open", nowOpen);
        openPushes[p.history_id] = nowOpen;
      });
      wrap.appendChild(row);
    });
    return wrap;
  }

  function renderBuildRow(build) {
    var row = el("div", "status-row");
    row.appendChild(el("span", "dot " + (build.version_source === "git" ? "green" : "amber")));
    var body = el("div", "status-body");
    body.appendChild(el("div", "status-name", "Running build"));
    body.appendChild(el("div", "status-msg", "Started " + fmtTime(build.started_at)));
    var kv = el("dl", "kv");
    kv.appendChild(el("dt", null, "Build"));
    kv.appendChild(el("dd", null, build.build_id));
    kv.appendChild(el("dt", null, "Release"));
    kv.appendChild(el("dd", null, build.version + (build.version_source === "git" ? "" : " (git not available to the server — the build id above is unaffected)")));
    kv.appendChild(el("dt", null, "Process"));
    kv.appendChild(el("dd", null, "boot " + build.boot_id));
    body.appendChild(kv);
    row.appendChild(body);
    return row;
  }

  function renderStatusPanel(container, data) {
    container.innerHTML = "";
    var rows = [
      { key: "database", name: "Database" },
      { key: "ai_extraction", name: "Recipe reader" },
      { key: "anylist", name: "AnyList" },
    ];

    // Plain summary first; the detail below is for whoever looks after the app (docs/ui-ux.md >
    // Plain language & no ambiguity). Colour is never the only signal: every row also says it.
    var worst = "green";
    rows.forEach(function (r) {
      var st = (data[r.key] || {}).state || "grey";
      if (st === "red") worst = "red";
      else if (st === "amber" && worst !== "red") worst = "amber";
    });
    container.appendChild(
      el(
        "h3",
        "status-summary",
        worst === "red" ? "Something isn’t working" : worst === "amber" ? "Something needs a look" : "Everything is working"
      )
    );

    rows.forEach(function (r) {
      var d = data[r.key] || {};
      var row = el("div", "status-row");
      row.appendChild(el("span", "dot " + (d.state || "grey")));

      var body = el("div", "status-body");
      body.appendChild(el("div", "status-name", r.name));
      body.appendChild(el("div", "status-msg", d.message || ""));

      if (r.key === "ai_extraction") {
        body.appendChild(
          el(
            "div",
            "status-msg",
            "Connected: " + (d.api_enabled ? "yes" : "no") + "  ·  test mode: " + (d.fake_mode ? "yes" : "no")
          )
        );

        // Quota indicator — observed request count today per model (best-effort; Gemini's
        // free-tier caps aren't reliably documented — see CLAUDE.md > AI Provider Migration).
        var byModel = d.today_by_model || {};
        var quotaBits = Object.keys(byModel).map(function (m) {
          return m + ": " + byModel[m];
        });
        body.appendChild(
          el(
            "div",
            "status-msg",
            "Today: " + (quotaBits.length ? quotaBits.join("  ·  ") : "no calls") +
              "  ·  last success: " + fmtTime(d.last_success)
          )
        );

        if (d.dashboard_url) {
          var link = el("a", null, "open Google AI Studio quota dashboard →");
          link.href = d.dashboard_url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          var linkWrap = el("div", "status-msg");
          linkWrap.appendChild(link);
          body.appendChild(linkWrap);
        }

        var q = d.queue || { depth: 0, items: [], stalled_count: 0 };
        if (q.depth) {
          body.appendChild(
            el(
              "div",
              "status-msg",
              "Capture queue: " +
                q.depth +
                " item(s) waiting on quota — " +
                q.items
                  .map(function (it) {
                    // 2026-09-13 code review — run_once() never drops a permanently-broken
                    // item (a deleted photo file, a now-dead URL), so it just keeps retrying
                    // hourly forever; flag one that's clearly stuck rather than let it read
                    // the same as a task still working through transient quota exhaustion.
                    var label = it.task + (it.attempt_count ? " (×" + it.attempt_count + ")" : "");
                    return it.stalled ? label + " ⚠ stalled" : label;
                  })
                  .join(", ")
            )
          );
          if (q.stalled_count) {
            body.appendChild(
              el(
                "div",
                "status-msg",
                "⚠ " +
                  q.stalled_count +
                  " item(s) have failed repeatedly and may need attention (e.g. a deleted " +
                  "photo, or a URL that no longer works) — they'll keep retrying hourly, but " +
                  "won't succeed on their own if the underlying problem hasn't changed."
              )
            );
          }
        }

        var recent = d.recent_calls || [];
        if (recent.length) {
          var log = el("div", "ai-attempt-log");
          recent.forEach(function (c) {
            var line = el("div", "log-line");
            line.appendChild(el("span", "log-time", fmtTime(c.time)));
            line.appendChild(el("span", "log-level " + (c.outcome === "success" ? "INFO" : c.outcome === "quota" ? "WARNING" : "ERROR"), c.outcome));
            line.appendChild(
              el("span", "log-msg", c.task + " / " + c.model + (c.error_detail ? " — " + c.error_detail : ""))
            );
            log.appendChild(line);
          });
          body.appendChild(el("div", "status-msg", "Recent attempts:"));
          body.appendChild(log);
        }
      }
      if (r.key === "anylist") {
        body.appendChild(
          el(
            "div",
            "status-msg",
            "Connected: " + (d.enabled ? "yes" : "no") +
              "  ·  test mode: " + (d.fake_mode ? "yes" : "no") +
              "  ·  list: " + (d.target_list || "?") +
              "  ·  login saved: " + (d.credentials_configured ? "yes" : "no")
          )
        );
        if (d.last_success)
          body.appendChild(el("div", "status-msg", "Last success: " + fmtTime(d.last_success)));
        if (d.last_push)
          body.appendChild(
            el(
              "div",
              "status-msg",
              "Last push: session " + d.last_push.session_id + " at " + fmtTime(d.last_push.pushed_at) +
                (d.last_push.confirmed ? " (confirmed)" : " — NOT confirmed")
            )
          );
        var checkBtn = el("button", null, "Check AnyList now");
        var checkOut = el("span", "status-msg");
        // Held in module state: this panel is rebuilt every 5 seconds, which used to wipe the result
        // (and re-enable the button) before it could be read.
        checkOut.textContent = anylistCheckText;
        checkBtn.disabled = anylistChecking;
        checkBtn.addEventListener("click", function () {
          anylistChecking = true;
          anylistCheckText = " checking…";
          checkBtn.disabled = true;
          checkOut.textContent = anylistCheckText;
          api.diagnostics
            .anylistCheck()
            .then(function (res) {
              anylistCheckText = " " + (res.ok ? "OK" : "Failed") + " — " + res.detail;
            })
            .catch(function (err) {
              anylistCheckText = " Couldn’t check: " + err.message;
            })
            .then(function () {
              anylistChecking = false;
              checkOut.textContent = anylistCheckText;
              checkBtn.disabled = false;
            });
        });
        var checkWrap = el("div", "status-msg");
        checkWrap.appendChild(checkBtn);
        checkWrap.appendChild(checkOut);
        body.appendChild(checkWrap);
        if (d.recent_pushes && d.recent_pushes.length) body.appendChild(renderPushHistory(d.recent_pushes));
      }

      var STATE_WORDS = { green: "Working", amber: "Check this", red: "Not working", grey: "Not in use" };
      body.appendChild(el("div", "state-label", STATE_WORDS[d.state || "grey"] || d.state));
      row.appendChild(body);
      container.appendChild(row);
    });
    if (data.build) container.appendChild(renderBuildRow(data.build));
  }

  function renderLogLines(container, entries) {
    container.innerHTML = "";
    if (!entries || entries.length === 0) {
      container.appendChild(el("div", "log-line", "no entries"));
      return;
    }
    entries.forEach(function (e) {
      var line = el("div", "log-line");
      line.appendChild(el("span", "log-time", fmtTime(e.time)));
      line.appendChild(el("span", "log-level " + e.level, e.level));
      line.appendChild(el("span", "log-msg", e.logger + ": " + e.message));
      if (e.traceback) {
        line.appendChild(el("pre", "log-trace", e.traceback));
      }
      container.appendChild(line);
    });
  }

  // One line per entry: "timestamp | level | logger: message", then the full traceback (if
  // any) on the following lines — plain text, suitable for pasting into a bug report or chat
  // (diagnostics chunk 7.7, 5b). Always every entry currently shown on the Recent Errors
  // card (ERROR+), never the level filter applied to the Live log tail below it.
  // Copy `text` to the clipboard; resolves true/false, never rejects. The async Clipboard API
  // exists only in a secure context (https or localhost), and this app is served over plain HTTP
  // on the home network, so it is undefined on a phone: fall back to selecting a throw-away
  // textarea and `execCommand("copy")`, which still works there when called inside the tap.
  function copyText(text) {
    function legacy() {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.top = "0";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        return !!ok;
      } catch (_) {
        return false;
      }
    }
    if (navigator.clipboard && global.isSecureContext) {
      return navigator.clipboard.writeText(text).then(
        function () { return true; },
        function () { return legacy(); }
      );
    }
    return Promise.resolve(legacy());
  }

  function formatErrorsForClipboard(entries) {
    return (entries || [])
      .map(function (e) {
        var header = fmtTime(e.time) + " | " + e.level + " | " + (e.logger ? e.logger + ": " : "") + e.message;
        return e.traceback ? header + "\n" + e.traceback : header;
      })
      .join("\n\n");
  }

  function refresh(root) {
    var statusPanel = root.querySelector("#diag-status");
    var errorsBox = root.querySelector("#diag-errors");
    var logList = root.querySelector("#diag-logs");
    var updated = root.querySelector("#diag-updated");

    api.diagnostics
      .status()
      .then(function (d) {
        if (statusPanel) renderStatusPanel(statusPanel, d);
      })
      .catch(function (err) {
        if (statusPanel) statusPanel.textContent = "Status unavailable: " + err.message;
      });

    api.diagnostics
      .recentErrors()
      .then(function (d) {
        state.lastErrors = d.entries || [];
        if (errorsBox) renderLogLines(errorsBox, d.entries);
      })
      .catch(function () {});

    api.diagnostics
      .logs(state.limit, state.level || null)
      .then(function (d) {
        if (logList) renderLogLines(logList, d.entries);
        if (updated) updated.textContent = "updated " + new Date().toLocaleTimeString();
      })
      .catch(function (err) {
        if (logList) logList.textContent = "Logs unavailable: " + err.message;
      });
  }

  function mount(root) {
    root.innerHTML = "";

    // component status
    var statusCard = el("div", "card");
    statusCard.appendChild(el("h2", null, "Status"));
    var statusPanel = el("div");
    statusPanel.id = "diag-status";
    var statusSkel = el("div", "skel-row");
    var statusSkelLine = el("div", "skeleton skel-line");
    statusSkelLine.style.width = "100%";
    statusSkel.appendChild(statusSkelLine);
    statusPanel.appendChild(statusSkel);
    statusCard.appendChild(statusPanel);
    root.appendChild(statusCard);

    // recent errors
    var errCard = el("div", "card");
    var errHead = el("div", "log-controls");
    errHead.appendChild(el("h2", null, "Recent errors"));
    var copyBtn = el("button", null, "Copy errors");
    copyBtn.style.marginLeft = "auto";
    // Shown only when the browser refuses every way of copying: the text in a box, already
    // selected, so a press-and-hold copies it (2026-10-16 — Firefox on a phone over plain HTTP).
    var fallbackBox = el("div");
    fallbackBox.hidden = true;
    var fallbackHint = el(
      "div",
      "hint",
      "Couldn’t copy automatically. Press and hold the text below, then choose Copy."
    );
    var fallbackText = el("textarea", "copy-fallback");
    fallbackText.readOnly = true;
    fallbackText.setAttribute("aria-label", "Errors to copy");
    fallbackBox.appendChild(fallbackHint);
    fallbackBox.appendChild(fallbackText);
    copyBtn.addEventListener("click", function () {
      var text = formatErrorsForClipboard(state.lastErrors);
      if (!text) {
        global.Toast.show("No errors to copy");
        return;
      }
      var n = state.lastErrors.length;
      copyText(text).then(function (ok) {
        if (ok) {
          fallbackBox.hidden = true;
          global.Toast.show("Copied " + n + (n === 1 ? " error" : " errors"));
          return;
        }
        fallbackText.value = text;
        fallbackBox.hidden = false;
        fallbackText.focus();
        fallbackText.select();
      });
    });
    errHead.appendChild(copyBtn);
    errCard.appendChild(errHead);
    errCard.appendChild(fallbackBox);
    var errBox = el("div", "log-list errors-box");
    errBox.id = "diag-errors";
    errCard.appendChild(errBox);
    root.appendChild(errCard);

    // log tail
    var logCard = el("div", "card");
    var head = el("h2", null, "Log (for troubleshooting)");
    logCard.appendChild(head);

    var controls = el("div", "log-controls");
    var levelSel = el("select");
    ["", "DEBUG", "INFO", "WARNING", "ERROR"].forEach(function (lv) {
      var opt = el("option", null, lv === "" ? "All levels" : lv);
      opt.value = lv;
      levelSel.appendChild(opt);
    });
    levelSel.value = state.level;
    levelSel.addEventListener("change", function () {
      state.level = levelSel.value;
      refresh(root);
    });
    controls.appendChild(levelSel);

    var refreshBtn = el("button", null, "Refresh now");
    refreshBtn.addEventListener("click", function () {
      refresh(root);
    });
    controls.appendChild(refreshBtn);

    var updated = el("span", "updated-note");
    updated.id = "diag-updated";
    controls.appendChild(updated);

    logCard.appendChild(controls);

    var logList = el("div", "log-list");
    logList.id = "diag-logs";
    logCard.appendChild(logList);
    // The raw log is for whoever looks after the app: folded away so the page opens on the plain
    // summary and the recent errors (docs/ui-ux.md > Plain language & no ambiguity).
    var advanced = el("details", "advanced-details");
    advanced.appendChild(el("summary", null, "Advanced"));
    advanced.appendChild(logCard);
    root.appendChild(advanced);

    refresh(root);
    state.timer = global.setInterval(function () {
      refresh(root);
    }, REFRESH_MS);
  }

  function unmount() {
    if (state.timer) {
      global.clearInterval(state.timer);
      state.timer = null;
    }
  }

  global.DiagnosticsView = { mount: mount, unmount: unmount };
})(window);
