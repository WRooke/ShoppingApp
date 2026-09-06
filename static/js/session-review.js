/* Planning session — ingredient review + ad-hoc substitution + consolidated
   shopping-list summary. Split from sessions.js per CLAUDE.md > Code Architecture
   & Maintainability. See CLAUDE.md > Ingredient Substitution and > Build Phases >
   Phase 4 > Chunk 4.7.

   Session-only overrides are held here client-side and passed into the
   /consolidate call (the "No, don't remember" path writes nothing to the DB).
   "Yes, remember" POSTs a real ingredient_substitutions rule. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtQty(item) {
    if (item.needs_review) return "needs review";
    if (item.total_quantity == null) return item.note || "";
    var q = item.total_quantity;
    var n = q === Math.round(q) ? String(Math.round(q)) : String(q);
    return item.total_unit ? n + " " + item.total_unit : n;
  }

  function mount(root, sessionId) {
    root.innerHTML = "";
    var overrides = []; // [{ original_name, substitute_name }] — session-only
    var knownSubs = {}; // original_name -> [substitute_name, ...]

    var back = el("a", "btn", "← Back to session");
    back.href = "#/plan/" + sessionId;
    root.appendChild(back);

    var card = el("div", "card");
    card.appendChild(el("h2", null, "Shopping list"));
    card.appendChild(
      el(
        "div",
        "muted",
        "Consolidated across every recipe in the session, scaled and resolved to pack sizes. Swap anything you'd rather not buy."
      )
    );
    var body = el("div");
    body.textContent = "Consolidating...";
    card.appendChild(body);
    root.appendChild(card);

    api.settings.substitutions
      .list()
      .then(function (data) {
        (data.items || []).forEach(function (r) {
          (knownSubs[r.original_name] = knownSubs[r.original_name] || []).push(r.substitute_name);
        });
      })
      .catch(function () {})
      .then(runConsolidate);

    function runConsolidate() {
      body.textContent = "Consolidating...";
      api.sessions
        .consolidate(sessionId, overrides)
        .then(function (data) {
          renderItems(data.items || []);
        })
        .catch(function (err) {
          body.textContent = "Couldn't consolidate: " + err.message;
        });
    }

    function renderItems(items) {
      body.innerHTML = "";
      if (items.length === 0) {
        body.appendChild(el("div", "muted", "Nothing to buy — the session has no recipe ingredients."));
        return;
      }
      var list = el("div", "settings-list");
      items.forEach(function (item) {
        list.appendChild(renderItemRow(item));
      });
      body.appendChild(list);
    }

    function renderItemRow(item) {
      var row = el("div", "settings-row");

      var main = el("div");
      main.style.flex = "3 1 200px";
      main.appendChild(el("div", "recipe-row-name", item.ingredient_name));

      var detail;
      if (item.needs_review) {
        detail = "⚠ " + (item.note || "mixed units — needs review");
      } else if (item.display_qty) {
        detail = item.display_qty + " · need ~" + fmtQty(item);
        if (item.note) detail += " · " + item.note;
      } else {
        detail = fmtQty(item);
        if (item.note && item.total_quantity != null) detail += " · " + item.note;
      }
      var d = el("div", "recipe-row-meta muted", detail);
      main.appendChild(d);
      if (item.is_staple) main.appendChild(el("div", "recipe-row-meta muted", "(staple)"));
      row.appendChild(main);

      var swapBtn = el("button", null, "Swap");
      row.appendChild(swapBtn);

      var swapSlot = el("div");
      swapSlot.style.flexBasis = "100%";
      row.appendChild(swapSlot);

      swapBtn.addEventListener("click", function () {
        if (swapSlot.firstChild) {
          swapSlot.innerHTML = "";
          return;
        }
        renderSwapForm(swapSlot, item);
      });

      return row;
    }

    function renderSwapForm(slot, item) {
      slot.innerHTML = "";
      var wrap = el("div");
      wrap.style.marginTop = "6px";
      wrap.appendChild(el("span", "muted", "Use instead: "));

      var input = el("input");
      input.type = "text";
      input.placeholder = "e.g. regular feta";
      input.className = "settings-name-input";
      wrap.appendChild(input);

      var applyBtn = el("button", "primary", "Apply");
      wrap.appendChild(applyBtn);
      var errSpan = el("span", "form-error");
      wrap.appendChild(errSpan);

      (knownSubs[item.ingredient_name] || []).forEach(function (sub) {
        var pick = el("button", null, sub);
        pick.addEventListener("click", function () {
          input.value = sub;
        });
        wrap.appendChild(pick);
      });

      slot.appendChild(wrap);

      applyBtn.addEventListener("click", function () {
        var sub = input.value.trim();
        if (!sub) {
          errSpan.textContent = "Type a replacement first.";
          return;
        }
        // record/replace the session-only override, then re-consolidate
        overrides = overrides.filter(function (o) {
          return o.original_name !== item.ingredient_name;
        });
        overrides.push({ original_name: item.ingredient_name, substitute_name: sub });
        runConsolidate();
        askRemember(item.ingredient_name, sub);
      });
    }

    function askRemember(originalName, substituteName) {
      if (
        global.confirm(
          'Save "' +
            originalName +
            '" → "' +
            substituteName +
            '" as a quick pick? It won\'t apply on its own — you\'ll just be offered it when reviewing a recipe that uses "' +
            originalName +
            '".'
        )
      ) {
        api.settings.substitutions
          .create({ original_name: originalName, substitute_name: substituteName })
          .catch(function (err) {
            // a duplicate saved swap is fine — it already exists
            if (err.code !== "DUPLICATE_SUBSTITUTION") {
              global.alert("Couldn't save the swap: " + err.message);
            }
          });
      }
    }
  }

  global.SessionReviewView = { mount: mount };
})(window);
