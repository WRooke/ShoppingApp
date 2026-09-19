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

  function miniField(labelText, inputEl) {
    var wrap = el("div", "mini-field");
    wrap.appendChild(el("label", null, labelText));
    wrap.appendChild(inputEl);
    return wrap;
  }

  // Shared Plan -> Review -> Checklist -> Push indicator (Chunk 6.3) — matches sessions.js's
  // copy (own small helper, not a shared module, per this file family's existing
  // self-contained-feature-file precedent). The last two stay inactive placeholders here;
  // checklist.js's own matching indicator is Chunk 6.3b's job.
  function stepIndicator(activeLabel) {
    var labels = ["Plan", "Review", "Checklist", "Push"];
    var wrap = el("div", "step-list");
    labels.forEach(function (label, i) {
      wrap.appendChild(el("span", label === activeLabel ? "on" : null, label));
      if (i < labels.length - 1) wrap.appendChild(el("span", "sep", "→"));
    });
    return wrap;
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

    root.appendChild(global.BackLink.render("plan"));
    root.appendChild(stepIndicator("Review"));

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
    showSkeleton(body);
    card.appendChild(body);
    root.appendChild(card);

    function showSkeleton(container) {
      container.innerHTML = "";
      var skel = el("div", "skel-row");
      var skelLine = el("div", "skeleton skel-line");
      skelLine.style.width = "100%";
      skelLine.style.height = "60px";
      skel.appendChild(skelLine);
      container.appendChild(skel);
    }

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
      showSkeleton(body);
      api.sessions
        .consolidate(sessionId, overrides)
        .then(function (data) {
          renderItems(data.items || []);
        })
        .catch(function (err) {
          body.innerHTML = "";
          body.appendChild(el("div", "error-state", "Couldn't consolidate: " + err.message));
        });
    }

    function renderItems(items) {
      body.innerHTML = "";
      if (items.length === 0) {
        body.appendChild(el("div", "empty-state", "Nothing to buy — the session has no recipe ingredients."));
        return;
      }
      var list = el("div", "settings-list");
      items.forEach(function (item) {
        list.appendChild(renderItemRow(item));
      });
      body.appendChild(list);

      // Phase 5 — proceed to the checklist ("do you have this?" + push to AnyList).
      // Sticky (kickoff decision #12) — the primary forward action on a screen that's
      // often the longest one in the whole flow once a session has several recipes.
      var nextRow = el("div", "sticky-actions");
      var next = el("a", "btn primary", "Next: checklist →");
      next.href = "#/checklist/" + sessionId;
      nextRow.appendChild(next);
      body.appendChild(nextRow);
    }

    // 2026-09-11 — "which recipe is this ingredient from": one row per contributing recipe
    // SLOT, never merged (even two slots of the same recipe show separately — CLAUDE.md).
    // Purely a display aid for the "hey what did we need this for?" check before checklist/
    // push; the data itself is ephemeral (recomputed on every consolidate, never stored).
    function fmtContribution(c) {
      if (c.is_no_scale) return "to taste";
      var n = c.quantity === Math.round(c.quantity) ? String(Math.round(c.quantity)) : String(c.quantity);
      return c.unit ? n + " " + c.unit : n;
    }

    function renderBreakdown(item) {
      var wrap = el("div", "recipe-breakdown");
      (item.recipe_breakdown || []).forEach(function (c) {
        var line = el("div", "recipe-breakdown-row muted");
        var link = el("a", null, c.recipe_label);
        if (c.recipe_id != null) link.href = "#/recipes/" + c.recipe_id;
        line.appendChild(link);
        line.appendChild(document.createTextNode(" — " + fmtContribution(c)));
        wrap.appendChild(line);
      });
      return wrap;
    }

    function renderItemRow(item) {
      var row = el("div", "settings-row");
      var hasBreakdown = (item.recipe_breakdown || []).length > 0;

      var main = el("div");
      main.style.flex = "3 1 200px";
      var nameEl = hasBreakdown ? el("button", "recipe-row-name recipe-row-name-btn") : el("div", "recipe-row-name");
      nameEl.textContent = item.ingredient_name + (hasBreakdown ? " ▾" : "");
      main.appendChild(nameEl);

      var detail;
      if (item.needs_review) {
        detail = "⚠ " + (item.note || "mixed units — needs review");
      } else if (item.display_qty) {
        // 2026-09-12 (Ingredient Unit Handling Layer D, "coarse ingredients") — a coarse
        // item has a display_qty (e.g. "1 × bunch") but no precise total_quantity at all,
        // by design (that's the whole point of "coarse" — skip quantity math entirely).
        // Appending "· need ~" with nothing after it read as a dangling half-sentence.
        detail = item.display_qty;
        if (item.total_quantity != null) detail += " · need ~" + fmtQty(item);
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

      var breakdownSlot = el("div");
      breakdownSlot.style.flexBasis = "100%";
      row.appendChild(breakdownSlot);

      if (hasBreakdown) {
        nameEl.addEventListener("click", function () {
          if (breakdownSlot.firstChild) {
            breakdownSlot.innerHTML = "";
            nameEl.textContent = item.ingredient_name + " ▾";
            return;
          }
          breakdownSlot.innerHTML = "";
          breakdownSlot.appendChild(renderBreakdown(item));
          nameEl.textContent = item.ingredient_name + " ▴";
        });
      }

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
      var wrap = el("div", "swap-panel");
      wrap.appendChild(el("div", "hdr", "Session-only swap"));

      var input = el("input");
      input.type = "text";
      input.placeholder = "e.g. regular feta";
      input.className = "settings-name-input";
      wrap.appendChild(miniField("Use instead", input));

      // M8 — optional "N unit ≈ M unit" so a swap can change the amount as well as the name.
      // Left blank => a straight rename. The "from" unit defaults to this line's unit.
      var oQty = el("input");
      oQty.type = "number";
      oQty.step = "any";
      oQty.inputMode = "decimal";
      oQty.placeholder = "e.g. " + (item.total_quantity != null ? fmtQty(item).split(" ")[0] : "2");
      oQty.className = "ingredient-qty-input";
      var oUnit = el("input");
      oUnit.type = "text";
      oUnit.placeholder = "e.g. can";
      oUnit.className = "ingredient-unit-input";
      oUnit.value = item.total_unit || "";
      var sQty = el("input");
      sQty.type = "number";
      sQty.step = "any";
      sQty.inputMode = "decimal";
      sQty.placeholder = "e.g. 350";
      sQty.className = "ingredient-qty-input";
      var sUnit = el("input");
      sUnit.type = "text";
      sUnit.placeholder = "e.g. g";
      sUnit.className = "ingredient-unit-input";

      var amtGrid = el("div", "ing-grid");
      amtGrid.style.gridTemplateColumns = "1fr 1fr";
      amtGrid.appendChild(miniField("This recipe's amount", oQty));
      amtGrid.appendChild(miniField("Unit", oUnit));
      wrap.appendChild(amtGrid);
      var subGrid = el("div", "ing-grid");
      subGrid.style.gridTemplateColumns = "1fr 1fr";
      subGrid.appendChild(miniField("Substitute amount", sQty));
      subGrid.appendChild(miniField("Substitute unit", sUnit));
      wrap.appendChild(subGrid);

      var applyBtn = el("button", "btn-sm primary", "Apply swap");
      var errSpan = el("span", "form-error");

      (knownSubs[item.ingredient_name] || []).forEach(function (row) {
        var label = row.substitute_name;
        if (row.original_qty && row.substitute_qty != null) {
          label += " (" + row.original_qty + " " + (row.original_unit || "") + " ≈ " +
            row.substitute_qty + " " + (row.substitute_unit || "") + ")";
        }
        var pick = el("button", "btn-sm", label);
        pick.style.marginRight = "4px";
        pick.addEventListener("click", function () {
          input.value = row.substitute_name;
          oQty.value = row.original_qty != null ? row.original_qty : "";
          oUnit.value = row.original_unit || item.total_unit || "";
          sQty.value = row.substitute_qty != null ? row.substitute_qty : "";
          sUnit.value = row.substitute_unit || "";
        });
        wrap.appendChild(pick);
      });

      wrap.appendChild(applyBtn);
      wrap.appendChild(errSpan);
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
