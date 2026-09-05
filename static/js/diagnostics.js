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
      { key: "claude_api", name: "Claude API" },
      { key: "anylist", name: "AnyList connection" },
    ];

    rows.forEach(function (r) {
      var d = data[r.key] || {};
      var row = el("div", "status-row");
      row.appendChild(el("span", "dot " + (d.state || "grey")));

      var body = el("div", "status-body");
      body.appendChild(el("div", "status-name", r.name));
      body.appendChild(el("div", "status-msg", d.message || ""));

      if (r.key === "claude_api") {
        var spend = el(
          "div",
          "status-msg",
          "Estimated spend: $" +
            (d.estimated_spend_usd != null ? d.estimated_spend_usd.toFixed(4) : "0.0000") +
            "  ·  last call: " +
            fmtTime(d.last_success)
        );
        body.appendChild(spend);
      }
      if (r.key === "anylist" && d.last_success) {
        body.appendChild(el("div", "status-msg", "Last auth: " + fmtTime(d.last_success)));
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
