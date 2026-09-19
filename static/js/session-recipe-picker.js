/* "Add a recipe" search-and-pick, split out of sessions.js per CLAUDE.md > Code Architecture
   & Maintainability > file size discipline (sessions.js was pushing past ~400 lines once the
   Chunk 6.3 step indicator, next-empty-day default, and Undo-on-remove wiring landed).
   Self-contained, matching this file family's existing precedent. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // slot: element to render into. sessionId: the session being added to. dayOfWeek: the
  // suggested day (or null) a picked recipe's new slot is created with — see sessions.js's
  // nextEmptyDay(). reload: called after a successful add.
  function render(slot, sessionId, dayOfWeek, reload) {
    slot.innerHTML = "";
    var box = el("div", "card");
    box.appendChild(el("h2", null, "Add a recipe"));
    var search = el("input");
    search.type = "text";
    search.placeholder = "Search the library...";
    box.appendChild(search);
    var results = el("div");
    results.style.marginTop = "8px";
    box.appendChild(results);
    slot.appendChild(box);

    function load() {
      api.recipes
        .list({ search: search.value, limit: 50 })
        .then(function (data) {
          results.innerHTML = "";
          if (!data.items.length) {
            results.appendChild(el("div", "empty-state", "No matches."));
            return;
          }
          data.items.forEach(function (r) {
            var b = el("button", null, r.name + "  (" + r.base_servings + " serv)");
            b.style.display = "block";
            b.style.marginBottom = "4px";
            b.addEventListener("click", function () {
              api.sessions
                .addRecipe(sessionId, { recipe_id: r.id, day_of_week: dayOfWeek })
                .then(function () {
                  slot.innerHTML = "";
                  reload();
                })
                .catch(function (err) {
                  global.alert("Couldn't add: " + err.message);
                });
            });
            results.appendChild(b);
          });
        })
        .catch(function (err) {
          results.innerHTML = "";
          results.appendChild(el("div", "error-state", "Couldn't search: " + err.message));
        });
    }
    var t = null;
    search.addEventListener("input", function () {
      if (t) global.clearTimeout(t);
      t = global.setTimeout(load, 200);
    });
    load();
  }

  global.SessionRecipePicker = { render: render };
})(window);
