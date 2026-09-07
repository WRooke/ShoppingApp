/* Diagnostics view: component status panel, recent errors, live log tail.
   Auto-refreshes every 5 seconds while the view is mounted (CLAUDE.md). */

(function (global) {
  "use strict";

  var REFRESH_MS = 5000;
  var state = {
    timer: null,
    level: "",
    limit: 200,
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtTime(iso) {
    if (!iso) return "-";
    return String(iso).replace("T", " ");
  }

  function renderStatusPanel(container, data) {
    container.innerHTML = "";
    var rows = [
      { key: "database", name: "Database connection" },
      { key: "ai_extraction", name: "AI extraction (Gemini)" },
      { key: "anylist", name: "AnyList connection" },
    ];

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
            "API enabled: " + (d.api_enabled ? "yes" : "no") + "  ·  fake mode: " + (d.fake_mode ? "yes" : "no")
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

        var q = d.queue || { depth: 0, items: [] };
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
                    return it.task + (it.attempt_count ? " (×" + it.attempt_count + ")" : "");
                  })
                  .join(", ")
            )
          );
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
            "enabled: " + (d.enabled ? "yes" : "no") +
              "  ·  fake mode: " + (d.fake_mode ? "yes" : "no") +
              "  ·  list: " + (d.target_list || "?") +
              "  ·  creds: " + (d.credentials_configured ? d.secret_source || "yes" : "none")
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
        checkBtn.addEventListener("click", function () {
          checkBtn.disabled = true;
          checkOut.textContent = " checking…";
          api.diagnostics
            .anylistCheck()
            .then(function (res) {
              checkOut.textContent = " " + (res.ok ? "OK" : "FAILED") + " — " + res.detail;
              checkBtn.disabled = false;
            })
            .catch(function (err) {
              checkOut.textContent = " error: " + err.message;
              checkBtn.disabled = false;
            });
        });
        var checkWrap = el("div", "status-msg");
        checkWrap.appendChild(checkBtn);
        checkWrap.appendChild(checkOut);
        body.appendChild(checkWrap);
      }

      body.appendChild(el("div", "state-label", "state: " + (d.state || "grey")));
      row.appendChild(body);
      container.appendChild(row);
    });
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
      container.appendChild(line);
    });
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
    statusCard.appendChild(el("h2", null, "Component status"));
    var statusPanel = el("div");
    statusPanel.id = "diag-status";
    statusPanel.textContent = "Loading...";
    statusCard.appendChild(statusPanel);
    root.appendChild(statusCard);

    // recent errors
    var errCard = el("div", "card");
    errCard.appendChild(el("h2", null, "Recent errors (last 10)"));
    var errBox = el("div", "log-list errors-box");
    errBox.id = "diag-errors";
    errCard.appendChild(errBox);
    root.appendChild(errCard);

    // log tail
    var logCard = el("div", "card");
    var head = el("h2", null, "Live log tail");
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
    root.appendChild(logCard);

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
