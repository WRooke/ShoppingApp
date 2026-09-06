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

  function backLink() {
    var back = el("a", "btn", "← Back to recipes");
    back.href = "#/recipes";
    return back;
  }

  // Errors from the capture endpoints (CLAUDE_API_DISABLED, EXTRACTION_FAILED,
  // RECIPE_FETCH_FAILED, INVALID_IMAGE) already carry a plain-language message from the
  // backend — see CLAUDE.md > API Conventions and > UI/UX > Tone & copy — so there's nothing
  // code-specific to branch on here, just show it.
  function describeError(err) {
    return err.message || "Something went wrong.";
  }

  function mountUrl(root) {
    root.innerHTML = "";
    root.appendChild(backLink());

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
      goBtn.textContent = "Fetching & extracting...";
      api.recipes
        .captureUrl(url, allowDuplicate)
        .then(function (result) {
          global.CaptureReviewView.mount(root, result);
        })
        .catch(function (err) {
          goBtn.disabled = false;
          goBtn.textContent = "Fetch & extract";
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
    root.appendChild(backLink());

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
      goBtn.textContent = "Uploading & extracting...";
      api.recipes
        .capturePhoto(file)
        .then(function (result) {
          global.CaptureReviewView.mount(root, result);
        })
        .catch(function (err) {
          goBtn.disabled = false;
          goBtn.textContent = "Upload & extract";
          formErr.textContent = describeError(err);
        });
    });

    root.appendChild(card);
  }

  global.CaptureView = { mountUrl: mountUrl, mountPhoto: mountPhoto, describeError: describeError };
})(window);
