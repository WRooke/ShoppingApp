/* Recipe capture — URL and photo entry forms. Calls the two extraction endpoints
   (POST /capture/url, /capture/photo) and hands the raw result to capture-review.js
   for editing + confirm-save. Split from that file per CLAUDE.md > Code Architecture
   & Maintainability > file size discipline — this file is "get an extraction",
   capture-review.js is "review and save one". */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function labeledField(labelText, inputEl) {
    var wrap = el("div", "field");
    wrap.appendChild(el("label", null, labelText));
    wrap.appendChild(inputEl);
    return wrap;
  }

  // 2026-09-23 — real, backend-driven step progress (replaces the old client-side-only
  // rotating label, which had zero relation to what the server was actually doing). The
  // steps mirror services/ai_extraction/calls.py's PROGRESS_STEPS exactly (extract ->
  // sections — a third step, "substitutions", was removed 2026-09-30 along with the AI
  // substitution-flagging call; manual substitution stays, just without an AI suggestion)
  // — see app/services/progress_tracker.py and GET /recipes/capture/progress/{token}, polled
  // here every 600ms while the main capture request is in flight. `firstMessage` still covers
  // the one phase with no tracked step at all (fetching the page / uploading the photo, which
  // happens before capture_recipe() is even called) — honest about that gap rather than
  // inventing a step for it.
  var STEP_LABELS = {
    extract: "Extracting ingredients",
    sections: "Suggesting aisles",
  };
  var STEP_ORDER = ["extract", "sections"];

  function makeToken() {
    if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
    return "t-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  }

  function iconFor(status) {
    if (status === "done") return "✓";
    if (status === "failed") return "✕";
    return "";
  }

  function startProgress(container, firstMessage) {
    var token = makeToken();
    var wrap = el("div", "capture-progress");
    wrap.appendChild(el("span", "spinner"));
    wrap.appendChild(el("span", null, firstMessage));
    container.appendChild(wrap);

    var stepsWrap = el("div", "step-list-vertical");
    var rows = {};
    STEP_ORDER.forEach(function (name) {
      var row = el("div", "step-row");
      var icon = el("div", "step-icon pending");
      var label = el("div", "step-label pending", STEP_LABELS[name]);
      row.appendChild(icon);
      row.appendChild(label);
      stepsWrap.appendChild(row);
      rows[name] = { icon: icon, label: label };
    });
    container.appendChild(stepsWrap);

    var pollTimer = global.setInterval(function () {
      api.recipes
        .captureProgress(token)
        .then(function (res) {
          (res.steps || []).forEach(function (s) {
            var row = rows[s.name];
            if (!row) return;
            row.icon.className = "step-icon " + s.status;
            row.icon.textContent = iconFor(s.status);
            row.label.className = "step-label " + s.status;
          });
        })
        .catch(function () {
          // 404 until the backend's first step_active() call actually lands — expected at
          // the very start (still fetching the page/photo), just keep polling.
        });
    }, 600);

    return {
      token: token,
      stop: function () {
        global.clearInterval(pollTimer);
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
        if (stepsWrap.parentNode) stepsWrap.parentNode.removeChild(stepsWrap);
      },
    };
  }

  // Errors from the capture endpoints (CLAUDE_API_DISABLED, EXTRACTION_FAILED,
  // RECIPE_FETCH_FAILED, INVALID_IMAGE) already carry a plain-language message from the
  // backend — see CLAUDE.md > API Conventions and > UI/UX > Tone & copy — so there's nothing
  // code-specific to branch on here, just show it.
  function describeError(err) {
    return err.message || "Something went wrong.";
  }

  // 2026-09-13 code review — the capture endpoints return {"ok": true, "data": {"queued":
  // true, "message": ...}} (see routers/recipes.py > _QUEUED) when every Gemini model is over
  // quota; the capture has been parked on the retry queue (services/capture_queue.py) rather
  // than failed outright. This used to be handed straight to CaptureReviewView.mount() like a
  // real extraction, landing the user on a blank ingredient form with no ingredients, no title,
  // and no explanation. Show the backend's own message instead.
  function showQueuedMessage(root, message) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("recipes"));
    var card = el("div", "card");
    card.appendChild(el("h2", null, "Capture queued"));
    card.appendChild(el("div", "muted", message));
    card.appendChild(
      el(
        "div",
        "muted",
        "No need to do anything — check back in the recipe library in a while, or watch the " +
          "capture queue on the Diagnostics page."
      )
    );
    root.appendChild(card);
  }

  function mountUrl(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("recipes"));

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Capture from a web page"));
    card.appendChild(
      el("div", "muted", "Paste a recipe page's URL — ingredients are extracted for you to review before saving.")
    );

    var urlInput = el("input");
    urlInput.type = "url";
    urlInput.placeholder = "https://example.com/some-recipe";
    card.appendChild(labeledField("Recipe URL", urlInput));

    var formErr = el("div", "form-error");
    card.appendChild(formErr);

    var dupPanel = el("div"); // holds the pre-extraction 409 short-circuit panel, if shown
    card.appendChild(dupPanel);

    var actionsRow = el("div", "log-controls");
    var goBtn = el("button", "primary", "Fetch & extract");
    actionsRow.appendChild(goBtn);
    card.appendChild(actionsRow);

    function run(allowDuplicate) {
      formErr.textContent = "";
      dupPanel.innerHTML = "";
      var url = urlInput.value.trim();
      if (!url) {
        formErr.textContent = "Enter a URL first.";
        return;
      }

      goBtn.disabled = true;
      var progress = startProgress(card, "Fetching the page…");
      api.recipes
        .captureUrl(url, allowDuplicate, progress.token)
        .then(function (result) {
          progress.stop();
          if (result && result.queued) {
            showQueuedMessage(root, result.message);
            return;
          }
          global.CaptureReviewView.mount(root, result);
        })
        .catch(function (err) {
          progress.stop();
          goBtn.disabled = false;
          // Exact source_url match — the backend short-circuited before any Claude call
          // (CLAUDE.md > Duplicate Recipe Prevention > URL capture short-circuit).
          if (err.code === "POSSIBLE_DUPLICATE_RECIPE" && Array.isArray(err.detail)) {
            dupPanel.appendChild(
              global.DupWarn.panel(err.detail, {
                heading: "You've already captured this page:",
                saveAnywayLabel: "Capture again anyway",
                onSaveAnyway: function () {
                  run(true);
                },
                onRestore: function (id) {
                  api.recipes
                    .restore(id)
                    .then(function () {
                      global.Router.navigate("recipes", id);
                    })
                    .catch(function (e) {
                      formErr.textContent = "Couldn't restore: " + e.message;
                    });
                },
              })
            );
            return;
          }
          formErr.textContent = describeError(err);
        });
    }

    goBtn.addEventListener("click", function () {
      run(false);
    });

    root.appendChild(card);
  }

  function mountPhoto(root) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("recipes"));

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Capture from a photo"));
    card.appendChild(
      el("div", "muted", "Take or choose a photo of a recipe (JPEG or PNG) — ingredients are extracted for you to review before saving.")
    );

    var fileInput = el("input");
    fileInput.type = "file";
    fileInput.accept = "image/jpeg,image/png";
    card.appendChild(labeledField("Recipe photo", fileInput));

    var formErr = el("div", "form-error");
    card.appendChild(formErr);

    var actionsRow = el("div", "log-controls");
    var goBtn = el("button", "primary", "Upload & extract");
    actionsRow.appendChild(goBtn);
    card.appendChild(actionsRow);

    goBtn.addEventListener("click", function () {
      formErr.textContent = "";
      var file = fileInput.files && fileInput.files[0];
      if (!file) {
        formErr.textContent = "Choose a photo first.";
        return;
      }

      goBtn.disabled = true;
      var progress = startProgress(card, "Uploading the photo…");
      api.recipes
        .capturePhoto(file, progress.token)
        .then(function (result) {
          progress.stop();
          if (result && result.queued) {
            showQueuedMessage(root, result.message);
            return;
          }
          global.CaptureReviewView.mount(root, result);
        })
        .catch(function (err) {
          progress.stop();
          goBtn.disabled = false;
          formErr.textContent = describeError(err);
        });
    });

    root.appendChild(card);
  }

  global.CaptureView = { mountUrl: mountUrl, mountPhoto: mountPhoto, describeError: describeError };
})(window);
