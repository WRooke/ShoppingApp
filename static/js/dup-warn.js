/* Shared "you might already have this recipe" warning panel + a live check-on-blur
   helper. Used by recipe-form.js (manual entry), capture-review.js (capture confirm)
   and capture.js (URL short-circuit). One place for the panel markup per CLAUDE.md >
   Code Architecture & Maintainability ("a new feature is a new file"), and per
   CLAUDE.md > Duplicate Recipe Prevention this is always warn-with-override, never a
   block. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // matches: [{ id, name, source_summary, matched_signal, archived }]
  // opts: { heading, onSaveAnyway (fn|null), onRestore (fn(id)|null), saveAnywayLabel }
  function panel(matches, opts) {
    opts = opts || {};
    var wrap = el("div", "dup-warn");
    wrap.appendChild(
      el("div", "dup-warn-heading", opts.heading || "You might already have this:")
    );

    var list = el("ul", "dup-warn-list");
    (matches || []).forEach(function (m) {
      var li = el("li");
      var link = el("a", null, m.name + (m.archived ? " (archived)" : ""));
      link.href = "#/recipes/" + m.id;
      li.appendChild(link);
      if (m.source_summary) {
        li.appendChild(el("span", "muted", " — " + m.source_summary));
      }
      if (m.archived && typeof opts.onRestore === "function") {
        li.appendChild(document.createTextNode(" "));
        var restoreBtn = el("button", "link-btn", "Restore this one");
        restoreBtn.addEventListener("click", function () {
          opts.onRestore(m.id);
        });
        li.appendChild(restoreBtn);
      }
      list.appendChild(li);
    });
    wrap.appendChild(list);

    if (typeof opts.onSaveAnyway === "function") {
      var saveBtn = el("button", null, opts.saveAnywayLabel || "Save anyway");
      saveBtn.addEventListener("click", opts.onSaveAnyway);
      wrap.appendChild(saveBtn);
    }
    return wrap;
  }

  // Warn softly as the user types a name, before they ever hit save. Best-effort —
  // a failed check is silent, the submit-time 409 is the real backstop.
  // getContext: optional fn -> { source_url, source_book, source_page, exclude_id }
  function liveCheck(nameInput, hintEl, getContext) {
    nameInput.addEventListener("blur", function () {
      hintEl.innerHTML = "";
      var name = nameInput.value.trim();
      if (!name) return;
      var params = { name: name };
      var ctx = (typeof getContext === "function" && getContext()) || {};
      Object.keys(ctx).forEach(function (k) {
        if (ctx[k]) params[k] = ctx[k];
      });
      api.recipes
        .checkDuplicate(params)
        .then(function (data) {
          if (!data.matches || data.matches.length === 0) return;
          hintEl.appendChild(
            panel(data.matches, {
              heading: "Heads up — a similar recipe is already saved:",
            })
          );
        })
        .catch(function () {
          /* live hint is best-effort; stay quiet on failure */
        });
    });
  }

  global.DupWarn = { panel: panel, liveCheck: liveCheck };
})(window);
