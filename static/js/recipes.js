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

    var newLink = el("a", "btn primary", "+ Add recipe");
    newLink.href = "#/recipes/new";
    newLink.style.display = "inline-block";
    newLink.style.marginBottom = "16px";
    root.appendChild(newLink);

    var listCard = el("div", "card");
    listCard.appendChild(el("h2", null, "Recipes"));
    var listBody = el("div");
    listBody.id = "recipe-list-body";
    listBody.textContent = "Loading...";
    listCard.appendChild(listBody);
    root.appendChild(listCard);

    function load() {
      listBody.textContent = "Loading...";
      api.recipes
        .list({ search: state.search, limit: 200 })
        .then(function (data) {
          renderListBody(listBody, data.items);
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
      row.appendChild(main);

      var rating = ratingLabel(r.rating);
      if (rating) row.appendChild(el("div", "recipe-row-rating", rating));

      container.appendChild(row);
    });
  }

  // --- detail view (view mode) -----------------------------------------

  function renderDetail(root, id) {
    root.innerHTML = "";

    var back = el("a", "btn", "← Back to recipes");
    back.href = "#/recipes";
    root.appendChild(back);

    var card = el("div", "card");
    card.textContent = "Loading...";
    root.appendChild(card);

    function load() {
      api.recipes
        .get(id)
        .then(function (r) {
          renderDetailView(card, r, load);
        })
        .catch(function (err) {
          card.innerHTML = "";
          if (err.code === "RECIPE_NOT_FOUND") {
            card.appendChild(
              el("div", "muted", "This recipe couldn't be found. It may have been deleted.")
            );
          } else {
            card.appendChild(el("div", "muted", "Couldn't load this recipe: " + err.message));
          }
        });
    }

    load();
  }

  function renderDetailView(card, r, reload) {
    card.innerHTML = "";

    var headRow = el("div", "detail-head-row");
    headRow.appendChild(el("h2", null, r.name));
    var editBtn = el("button", null, "Edit");
    editBtn.addEventListener("click", function () {
      global.RecipeEditView.mount(
        card,
        r,
        function () {
          reload(); // Cancel / Save both drop back to a freshly-loaded view mode
        },
        function () {
          global.Router.navigate("recipes"); // archived — nothing left to view here
        }
      );
    });
    headRow.appendChild(editBtn);
    card.appendChild(headRow);

    var metaBits = [fmtServings(r.base_servings)];
    if (r.cuisine) metaBits.push(r.cuisine);
    if (r.protein) metaBits.push(r.protein);
    var rating = ratingLabel(r.rating);
    if (rating) metaBits.push(rating);
    card.appendChild(el("div", "muted", metaBits.join(" · ")));

    if (r.archived_at) {
      card.appendChild(el("div", "muted", "Archived"));
    }

    var ingHeading = el("h2", null, "Ingredients");
    ingHeading.style.marginTop = "16px";
    card.appendChild(ingHeading);

    if (!r.ingredients || r.ingredients.length === 0) {
      card.appendChild(el("div", "muted", "No ingredients recorded."));
    } else {
      var list = el("ul", "ingredient-list");
      r.ingredients.forEach(function (ing) {
        var parts = [];
        parts.push(ing.quantity + (ing.unit ? " " + ing.unit : ""));
        parts.push(ing.name);
        if (ing.preparation) parts.push("(" + ing.preparation + ")");
        list.appendChild(el("li", null, parts.join(" ")));
      });
      card.appendChild(list);
    }

    if (r.notes) {
      var notesHeading = el("h2", null, "Notes");
      notesHeading.style.marginTop = "16px";
      card.appendChild(notesHeading);
      card.appendChild(el("div", null, r.notes));
    }
  }

  // --- entry point -----------------------------------------------------

  function mount(root, param) {
    if (param === "new") {
      global.RecipeFormView.mount(root);
    } else if (param) {
      renderDetail(root, param);
    } else {
      renderList(root);
    }
  }

  function unmount() {
    // Nothing to tear down yet — no timers/intervals in this view.
  }

  global.RecipesView = { mount: mount, unmount: unmount };
})(window);
