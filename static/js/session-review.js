/* Planning session — ingredient review + ad-hoc substitution + consolidated
   shopping-list summary. Split from sessions.js per CLAUDE.md > Code Architecture
   & Maintainability. See CLAUDE.md > Ingredient Substitution and > Build Phases >
   Phase 4 > Chunk 4.7.

   Session-only overrides are held here client-side and passed into the
   /consolidate call (the "No, don't remember" path writes nothing to the DB).
   "Yes, remember" POSTs a remembered_substitutions row.

   Phase 3.9 M8: a swap can also carry a quantity/unit equivalence pair
   ("2 cob ≈ 1 can") — optional inputs on the swap form, threaded into the override
   and into the "remember" POST. */

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
    var overrides = []; // [{ original_name, substitute_name, ...equivalence pair }] — session-only
    var knownSubs = {}; // original_name -> [full saved-swap row, ...]

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
          (knownSubs[r.original_name] = knownSubs[r.original_name] || []).push(r);
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

      // Phase 5 — proceed to the checklist ("do you have this?" + push to AnyList).
      var next = el("a", "btn primary", "Next: checklist →");
      next.href = "#/checklist/" + sessionId;
      next.style.marginTop = "12px";
      next.style.display = "inline-block";
      body.appendChild(next);
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

      // M8 — optional "N unit ≈ M unit" so a swap can change the amount as well as the name.
      // Left blank => a straight rename. The "from" unit defaults to this line's unit.
      wrap.appendChild(el("span", "muted", " amount (optional): "));
      var oQty = el("input");
      oQty.type = "number";
      oQty.step = "any";
      oQty.placeholder = "amt";
      oQty.className = "ingredient-qty-input";
      var oUnit = el("input");
      oUnit.type = "text";
      oUnit.placeholder = "unit";
      oUnit.className = "ingredient-unit-input";
      oUnit.value = item.total_unit || "";
      var sQty = el("input");
      sQty.type = "number";
      sQty.step = "any";
      sQty.placeholder = "amt";
      sQty.className = "ingredient-qty-input";
      var sUnit = el("input");
      sUnit.type = "text";
      sUnit.placeholder = "unit";
      sUnit.className = "ingredient-unit-input";
      [oQty, oUnit, el("span", "muted", "≈"), sQty, sUnit].forEach(function (n) {
        wrap.appendChild(n);
      });

      var applyBtn = el("button", "primary", "Apply");
      wrap.appendChild(applyBtn);
      var errSpan = el("span", "form-error");
      wrap.appendChild(errSpan);

      (knownSubs[item.ingredient_name] || []).forEach(function (row) {
        var label = row.substitute_name;
        if (row.original_qty && row.substitute_qty != null) {
          label += " (" + row.original_qty + " " + (row.original_unit || "") + " ≈ " +
            row.substitute_qty + " " + (row.substitute_unit || "") + ")";
        }
        var pick = el("button", null, label);
        pick.addEventListener("click", function () {
          input.value = row.substitute_name;
          oQty.value = row.original_qty != null ? row.original_qty : "";
          oUnit.value = row.original_unit || item.total_unit || "";
          sQty.value = row.substitute_qty != null ? row.substitute_qty : "";
          sUnit.value = row.substitute_unit || "";
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
        var oq = parseFloat(oQty.value);
        var sq = parseFloat(sQty.value);
        var hasPair =
          !isNaN(oq) && oq > 0 && !isNaN(sq) && sq > 0 && oUnit.value.trim() && sUnit.value.trim();
        var ov = { original_name: item.ingredient_name, substitute_name: sub };
        if (hasPair) {
          ov.original_qty = oq;
          ov.original_unit = oUnit.value.trim();
          ov.substitute_qty = sq;
          ov.substitute_unit = sUnit.value.trim();
        }
        // record/replace the session-only override, then re-consolidate
        overrides = overrides.filter(function (o) {
          return o.original_name !== item.ingredient_name;
        });
        overrides.push(ov);
        runConsolidate();
        askRemember(ov);
      });
    }

    function askRemember(ov) {
      if (
        global.confirm(
          'Save "' +
            ov.original_name +
            '" → "' +
            ov.substitute_name +
            '" as a quick pick? It won\'t apply on its own — you\'ll just be offered it when reviewing a recipe that uses "' +
            ov.original_name +
            '".'
        )
      ) {
        var payload = {
          original_name: ov.original_name,
          substitute_name: ov.substitute_name,
        };
        if (ov.original_qty != null) {
          payload.original_qty = ov.original_qty;
          payload.original_unit = ov.original_unit;
          payload.substitute_qty = ov.substitute_qty;
          payload.substitute_unit = ov.substitute_unit;
        }
        api.settings.substitutions.create(payload).catch(function (err) {
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
