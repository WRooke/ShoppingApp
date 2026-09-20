/* Recipe detail view (view mode) — split out of recipes.js per CLAUDE.md > Code Architecture
   & Maintainability > file size discipline (recipes.js passed ~400 lines once Chunk 6.6's
   "I cooked this" landed in it). Edit mode lives in recipe-edit.js, the library list in
   recipes.js. Small helpers (el/fmtServings/ratingLabel/pendingBadge) are duplicated from
   recipes.js rather than shared, matching this file family's established
   self-contained-feature-file precedent. */

(function (global) {
  "use strict";

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

  // Only render a stored source_url as a link if it actually parses as http(s) —
  // never javascript:/data:/etc. (see CLAUDE.md > Build Phases > Phase 3 > Chunk 3.7c).
  // Anything else falls back to plain text.
  function safeHttpUrl(raw) {
    if (!raw) return null;
    try {
      var u = new global.URL(raw);
      if (u.protocol === "http:" || u.protocol === "https:") return u.href;
    } catch (e) {
      /* not a parseable URL — treat as plain text */
    }
    return null;
  }

  // "Source" block on the detail view — a source_url line (linked if safe, else plain),
  // a "From {book}, p.{page}" line (page optional), both, or nothing.
  function renderSource(card, r) {
    if (!r.source_url && !r.source_book) return;
    var wrap = el("div", "recipe-source");
    wrap.style.marginTop = "8px";

    if (r.source_url) {
      var urlLine = el("div", "muted");
      urlLine.appendChild(document.createTextNode("Source: "));
      var safe = safeHttpUrl(r.source_url);
      if (safe) {
        var a = el("a", null, r.source_url);
        a.href = safe;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        urlLine.appendChild(a);
      } else {
        urlLine.appendChild(document.createTextNode(r.source_url));
      }
      wrap.appendChild(urlLine);
    }

    if (r.source_book) {
      var bookText = "From " + r.source_book;
      if (r.source_page) bookText += ", p." + r.source_page;
      wrap.appendChild(el("div", "muted", bookText));
    }

    card.appendChild(wrap);
  }

  function render(root, id) {
    root.innerHTML = "";
    root.appendChild(global.BackLink.render("recipes"));

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
    var addToSessionBtn = el("button", "btn-sm", "+ Add to session");
    addToSessionBtn.addEventListener("click", function () {
      global.AddToSession.run(r.id, addToSessionBtn);
    });
    headRow.appendChild(addToSessionBtn);
    card.appendChild(headRow);

    var metaBits = [fmtServings(r.base_servings)];
    if (r.cuisine) metaBits.push(r.cuisine);
    if (r.protein) metaBits.push(r.protein);
    var rating = ratingLabel(r.rating);
    if (rating) metaBits.push(rating);
    card.appendChild(el("div", "muted", metaBits.join(" · ")));

    if (r.ai_pending_tasks && r.ai_pending_tasks.length) {
      card.appendChild(pendingBadge(r.ai_pending_tasks));
    }

    if (r.archived_at) {
      card.appendChild(el("div", "muted", "Archived"));
    }

    renderSource(card, r);

    // "I cooked this" (Phase 6 Chunk 6.6) — a low-stakes counter, no confirmation dialog.
    var cookedRow = el("div", "cooked-row");
    var cookedInfo = el("div", "cooked-info");
    cookedRow.appendChild(cookedInfo);
    var cookBtn = el("button", "btn-sm primary", "I cooked this");
    cookedRow.appendChild(cookBtn);
    card.appendChild(cookedRow);

    function renderCookedInfo() {
      cookedInfo.innerHTML = "";
      if (r.times_made > 0) {
        var b = el("b", null, r.times_made + (r.times_made === 1 ? " time" : " times"));
        cookedInfo.appendChild(document.createTextNode("Cooked "));
        cookedInfo.appendChild(b);
        if (r.last_made_at) {
          cookedInfo.appendChild(
            document.createTextNode(" · last on " + new Date(r.last_made_at).toLocaleDateString())
          );
        }
      } else {
        cookedInfo.appendChild(el("span", "never", "Never marked as cooked"));
      }
    }
    renderCookedInfo();

    cookBtn.addEventListener("click", function () {
      cookBtn.disabled = true;
      api.recipes
        .markCooked(r.id)
        .then(function (updated) {
          r.times_made = updated.times_made;
          r.last_made_at = updated.last_made_at;
          renderCookedInfo();
          global.Toast.show("Nice — marked as cooked.");
          cookBtn.disabled = false;
        })
        .catch(function (err) {
          cookBtn.disabled = false;
          global.alert("Couldn't mark cooked: " + err.message);
        });
    });

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
        var li = el("li", null, parts.join(" "));
        if (ing.resolved_ingredient) {
          // M8 — show the swapped amount/unit when the swap isn't 1:1 ("2 can canned corn")
          var swapAmt =
            ing.resolved_quantity != null
              ? ing.resolved_quantity + (ing.resolved_unit ? " " + ing.resolved_unit : "") + " "
              : "";
          var swapLine = el(
            "div",
            "ingredient-resolved",
            "→ using " +
              swapAmt +
              ing.resolved_ingredient +
              (ing.substitution_note ? " (" + ing.substitution_note + ")" : "")
          );
          li.appendChild(swapLine);
        }
        list.appendChild(li);
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

  global.RecipeDetailView = { render: render };
})(window);
