/* Per-ingredient substitution control (Phase 3.9 M4, quantity/unit transform added M8).
   Used by capture-review.js. A collapsed "Swap?" toggle that expands to: a replacement
   text field (pre-filled from the AI flag or the top saved swap), a note field, an
   optional amount + unit for when the swap isn't 1:1 in the recipe's own unit
   ("2 corn cobs" -> "2 cans"), quick-pick buttons for saved swaps, and a "save this
   swap" checkbox. Nothing here applies a swap on its own — the parent form includes
   getState() in the confirm payload, and the human confirmed it by typing/picking.
   See CLAUDE.md > AI Provider Migration > Ingredient Substitution Flagging. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function round4(n) {
    // trim floating-point noise from the pre-fill without forcing a fixed dp
    return Math.round(n * 10000) / 10000;
  }

  // flag:  { original, suggested_substitute, note } | null   (AI's per-recipe suggestion)
  // picks: [{ substitute_name, note, original_qty, original_unit, substitute_qty,
  //           substitute_unit }]                             (this ingredient's saved swaps)
  // lineQty / lineUnit: the recipe line's own amount, used to pre-fill the transform from a
  //   saved equivalence pair.
  function create(flag, picks, lineQty, lineUnit) {
    picks = picks || [];
    var lineU = (lineUnit || "").trim().toLowerCase();
    var wrap = el("div", "ing-swap");

    var toggle = el("button", "link-btn", "Swap?");
    wrap.appendChild(toggle);

    var body = el("div", "ing-swap-body");
    body.hidden = true;

    var subInput = el("input");
    subInput.type = "text";
    subInput.placeholder = "use instead";
    subInput.className = "settings-name-input";

    var noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "note (optional)";
    noteInput.className = "settings-notes-input";

    // M8 — optional amount + unit for a non-1:1 swap.
    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.placeholder = "amount";
    qtyInput.className = "ingredient-qty-input";

    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "unit";
    unitInput.className = "ingredient-unit-input";

    var preview = el("div", "ing-swap-preview muted");

    function refreshPreview() {
      var sub = subInput.value.trim();
      if (!sub) {
        preview.textContent = "";
        return;
      }
      var lq = lineQty != null ? lineQty : "?";
      var left = lq + (lineUnit ? " " + lineUnit : "");
      var q = qtyInput.value.trim();
      var u = unitInput.value.trim();
      if (q && u) {
        preview.textContent = left + " → " + q + " " + u + " " + sub;
      } else {
        preview.textContent = left + " → " + left.replace(/^\S+\s?/, "") + sub + " (same amount)";
      }
    }
    qtyInput.addEventListener("input", refreshPreview);
    unitInput.addEventListener("input", refreshPreview);
    subInput.addEventListener("input", refreshPreview);

    var rememberBox = el("input");
    rememberBox.type = "checkbox";
    var rememberLabel = el("label", "ing-swap-remember");
    rememberLabel.appendChild(rememberBox);
    rememberLabel.appendChild(document.createTextNode(" save this swap"));

    var clearBtn = el("button", "link-btn", "clear");
    clearBtn.addEventListener("click", function () {
      subInput.value = "";
      noteInput.value = "";
      qtyInput.value = "";
      unitInput.value = "";
      rememberBox.checked = false;
      refreshPreview();
    });

    body.appendChild(el("span", "muted", "→"));
    body.appendChild(subInput);
    body.appendChild(noteInput);
    body.appendChild(qtyInput);
    body.appendChild(unitInput);
    body.appendChild(preview);

    function applyPick(p) {
      subInput.value = p.substitute_name;
      if (p.note) noteInput.value = p.note;
      // If the saved swap carries an equivalence pair AND its "from" unit matches this
      // line's unit, pre-fill the amount by scaling the pair to the line's quantity.
      if (
        p.original_qty &&
        p.original_qty > 0 &&
        p.substitute_qty != null &&
        (p.original_unit || "").trim().toLowerCase() === lineU &&
        lineQty != null
      ) {
        qtyInput.value = round4((lineQty / p.original_qty) * p.substitute_qty);
        unitInput.value = p.substitute_unit || "";
      }
      refreshPreview();
    }

    if (picks.length) {
      var pickRow = el("div", "ing-swap-picks");
      pickRow.appendChild(el("span", "muted", "saved: "));
      picks.forEach(function (p) {
        var label = p.substitute_name;
        if (p.original_qty && p.substitute_qty != null) {
          label += " (" + p.original_qty + " " + (p.original_unit || "") + " ≈ " +
            p.substitute_qty + " " + (p.substitute_unit || "") + ")";
        }
        var b = el("button", "link-btn", label);
        b.title = p.note || "";
        b.addEventListener("click", function () {
          applyPick(p);
        });
        pickRow.appendChild(b);
      });
      body.appendChild(pickRow);
    }

    body.appendChild(rememberLabel);
    body.appendChild(clearBtn);
    wrap.appendChild(body);

    var flagHint = null;
    if (flag) {
      flagHint = el("div", "ing-swap-flag muted", "AI: try " + flag.suggested_substitute +
        (flag.note ? " — " + flag.note : ""));
      wrap.appendChild(flagHint);
      // pre-fill the name from the AI flag but leave it collapsed; the user opens + confirms.
      // The AI never suggests the numbers (M8 decision (b)).
      subInput.value = flag.suggested_substitute;
      if (flag.note) noteInput.value = flag.note;
    } else if (picks.length === 1) {
      applyPick(picks[0]);
    }
    refreshPreview();

    toggle.addEventListener("click", function () {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden ? "Swap?" : "Swap ▾";
    });

    function getState() {
      var resolved = subInput.value.trim();
      if (!resolved) {
        return {
          resolved_ingredient: null,
          substitution_note: null,
          resolved_quantity: null,
          resolved_unit: null,
          remember: false,
        };
      }
      // both-or-neither on the amount/unit — a half-pair is dropped rather than sent
      var q = parseFloat(qtyInput.value);
      var u = unitInput.value.trim();
      var hasTransform = !isNaN(q) && q > 0 && !!u;
      return {
        resolved_ingredient: resolved,
        substitution_note: noteInput.value.trim() || null,
        resolved_quantity: hasTransform ? q : null,
        resolved_unit: hasTransform ? u : null,
        remember: !!rememberBox.checked,
      };
    }

    return { el: wrap, getState: getState };
  }

  global.IngredientSwap = { create: create };
})(window);
