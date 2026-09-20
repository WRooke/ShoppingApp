/* Recipe library view: browse list (search by name) + recipe detail in view
   mode. Edit mode (recipe-level fields + ingredient CRUD) lives in
   recipe-edit.js, and manual "new recipe from scratch" entry lives in
   recipe-form.js (see CLAUDE.md > Code Architecture & Maintainability > file
   size discipline — split by sub-feature rather than growing one file past
   ~400 lines). */

(function (global) {
  "use strict";

  var state = {
    search: "",
    cuisine: "", // Phase 6 Chunk 6.2 — quick-filter chips, "" = All
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtServings(n) {
    return n + (n === 1 ? " serving" : " servings");
  }

  function ratingLabel(rating) {
    if (rating === "up") return "👍";
    if (rating === "down") return "👎";
    return null;
  }

  // "Pending AI processing" badge (Phase 3.9 M6) — a queued capture whose enrichment
  // (section suggestion) hasn't finished yet. Names the outstanding sub-task(s).
  function pendingBadge(tasks) {
    var pretty = (tasks || [])
      .map(function (t) {
        return t === "suggest_sections" ? "sections" : t;
      })
      .join(", ");
    return el("div", "pending-ai-badge", "⏳ Pending AI processing (" + pretty + ")");
  }

  // --- list view -----------------------------------------------------

  function renderList(root) {
    root.innerHTML = "";

    var searchCard = el("div", "card");
    var searchRow = el("div", "log-controls");
    var input = el("input");
    input.type = "text";
    input.placeholder = "Search recipes by name...";
    input.value = state.search;
    input.setAttribute("aria-label", "Search recipes by name");
    searchRow.appendChild(input);
    searchCard.appendChild(searchRow);
    root.appendChild(searchCard);

    var actionsRow = el("div", "log-controls");
    actionsRow.style.marginBottom = "16px";

    var newLink = el("a", "btn primary", "+ Add recipe");
    newLink.href = "#/recipes/new";
    actionsRow.appendChild(newLink);

    var captureUrlLink = el("a", "btn", "Capture from URL");
    captureUrlLink.href = "#/recipes/capture-url";
    actionsRow.appendChild(captureUrlLink);

    var capturePhotoLink = el("a", "btn", "Capture from photo");
    capturePhotoLink.href = "#/recipes/capture-photo";
    actionsRow.appendChild(capturePhotoLink);

    root.appendChild(actionsRow);

    // Cuisine quick-filter chips (Chunk 6.2) — the chip set itself is derived once from
    // the library's own unfiltered contents (below), not a fixed vocabulary, so it only
    // ever shows cuisines this household has actually used.
    var filterRow = el("div", "filter-row");
    filterRow.setAttribute("role", "group");
    filterRow.setAttribute("aria-label", "Filter by cuisine");
    root.appendChild(filterRow);

    var listCard = el("div", "card");
    listCard.appendChild(el("h2", null, "Recipes"));
    var listBody = el("div");
    listBody.id = "recipe-list-body";
    listBody.textContent = "Loading...";
    listCard.appendChild(listBody);
    root.appendChild(listCard);

    var knownCuisines = null; // computed once; stays stable while a filter is applied so
                               // the chip row itself never disappears out from under you

    function renderChips(cuisines) {
      filterRow.innerHTML = "";
      if (!cuisines.length) return; // nothing to filter by yet
      var allChip = el("button", "chip", "All");
      allChip.type = "button";
      allChip.setAttribute("aria-pressed", String(!state.cuisine));
      allChip.addEventListener("click", function () {
        state.cuisine = "";
        load();
      });
      filterRow.appendChild(allChip);
      cuisines.forEach(function (c) {
        var chip = el("button", "chip", c);
        chip.type = "button";
        chip.setAttribute("aria-pressed", String(state.cuisine === c));
        chip.addEventListener("click", function () {
          state.cuisine = c;
          load();
        });
        filterRow.appendChild(chip);
      });
    }

    function cuisinesFrom(items) {
      var seen = {};
      var out = [];
      items.forEach(function (r) {
        if (r.cuisine && !seen[r.cuisine]) {
          seen[r.cuisine] = true;
          out.push(r.cuisine);
        }
      });
      return out.sort();
    }

    function load() {
      listBody.textContent = "Loading...";
      api.recipes
        .list({ search: state.search, cuisine: state.cuisine, limit: 200 })
        .then(function (data) {
          renderListBody(listBody, data.items);
          if (knownCuisines) {
            renderChips(knownCuisines); // re-render so the pressed state stays in sync
            return;
          }
          // First load only. An unfiltered result already shows the full cuisine set;
          // a filtered one (e.g. a direct search) doesn't, so fetch once more, quietly,
          // just to build the chip row — the only extra request this feature costs.
          if (!state.search && !state.cuisine) {
            knownCuisines = cuisinesFrom(data.items);
            renderChips(knownCuisines);
          } else {
            api.recipes
              .list({ limit: 200 })
              .then(function (full) {
                knownCuisines = cuisinesFrom(full.items);
                renderChips(knownCuisines);
              })
              .catch(function () {
                /* chips are a nicety — a failed background fetch just leaves them absent */
              });
          }
        })
        .catch(function (err) {
          listBody.textContent = "Couldn't load recipes: " + err.message;
        });
    }

    var debounceTimer = null;
    input.addEventListener("input", function () {
      state.search = input.value;
      if (debounceTimer) global.clearTimeout(debounceTimer);
      debounceTimer = global.setTimeout(load, 250);
    });

    load();
  }

  function renderListBody(container, items) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
      container.appendChild(el("div", "muted", "No recipes found."));
      return;
    }
    items.forEach(function (r) {
      var row = el("a", "recipe-row");
      row.href = "#/recipes/" + r.id;

      var main = el("div", "recipe-row-main");
      main.appendChild(el("div", "recipe-row-name", r.name));
      var metaBits = [fmtServings(r.base_servings)];
      if (r.cuisine) metaBits.push(r.cuisine);
      if (r.protein) metaBits.push(r.protein);
      main.appendChild(el("div", "recipe-row-meta muted", metaBits.join(" · ")));
      if (r.ai_pending_tasks && r.ai_pending_tasks.length) {
        main.appendChild(pendingBadge(r.ai_pending_tasks));
      }
      row.appendChild(main);

      var rating = ratingLabel(r.rating);
      if (rating) row.appendChild(el("div", "recipe-row-rating", rating));

      var addBtn = el("button", "btn-sm", "+ Add to session");
      addBtn.addEventListener("click", function (ev) {
        // Row is a full-card <a> — stop the click reaching it, or this both adds the
        // recipe to a session AND navigates to the recipe's own detail page.
        ev.preventDefault();
        ev.stopPropagation();
        global.AddToSession.run(r.id, addBtn);
      });
      row.appendChild(addBtn);

      container.appendChild(row);
    });
  }

  // --- entry point -----------------------------------------------------
  // Detail view (view mode, incl. "I cooked this") lives in recipe-detail.js — split out
  // per CLAUDE.md > Code Architecture & Maintainability > file size discipline.

  function mount(root, param) {
    if (param === "new") {
      global.RecipeFormView.mount(root);
    } else if (param === "capture-url") {
      global.CaptureView.mountUrl(root);
    } else if (param === "capture-photo") {
      global.CaptureView.mountPhoto(root);
    } else if (param) {
      global.RecipeDetailView.render(root, param);
    } else {
      renderList(root);
    }
  }

  function unmount() {
    // Nothing to tear down yet — no timers/intervals in this view.
  }

  global.RecipesView = { mount: mount, unmount: unmount };
})(window);
