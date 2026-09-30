/* Checklist ingredient panel (2026-09-30, chunk 7.5 — Review→Checklist merge / bottom-sheet
   feedback batch). Split out of checklist.js once this piece pushed it over the file-size
   guideline (CLAUDE.md > Code Architecture & Maintainability), same reason checklist-push.js
   was split out before it.

   The nested "Edit ingredient ▾" toggle + select-exclusive chip row approved in the chunk 7.1
   mockup (https://claude.ai/artifact/B6SiNLcKvND7tWnjdrsXMf, 4 revision rounds) — appended
   into a row's already-expanded recipe-breakdown slot (checklist.js > rowNameParts()), so a
   row always shows its breakdown first, with everything else behind one more tap. Five chips:
   pack size, substitute, alias, coarse item, merge. Every chip ends with the same shared
   this-list-only/always toggle (default: this list only, per §0.3 — a slip-of-the-thumb
   permanent edit mid-shop has a bigger blast radius than a scoped one) + an explicit Save
   button + a "Saved ✓" confirmation, so nothing ever commits as a side effect of typing.

   Point-of-need guardrail (docs/ui-ux.md): a chip only appears when that gap actually exists
   for this ingredient — Pack size only when no pack size resolves yet (same condition the old
   standalone "+ Add pack size" link used); Merge only when there's another row to merge with.
   Substitute/Alias/Coarse are always offered (there's always a valid "add one" action, not a
   broken state to detect) — same standing the now-deleted Review screen's own "Swap" button
   had on every row.

   Merge itself has no sub-panel here — it hands off to checklist.js's own existing
   screen-level "Select to merge" mode (mergeMode/mergeSelected), pre-selecting this row,
   rather than building a second, parallel merge mechanism. */

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

  var CHIP_LABELS = {
    pack: "Pack size",
    substitute: "Substitute",
    alias: "Alias",
    coarse: "Coarse item",
    merge: "Merge",
  };

  // pack: same gap condition the old standalone "+ Add pack size" link used — see
  // checklist.js's own qtyText() comment for why this specific check detects it.
  function computeChips(item, opts) {
    var chips = [];
    if (item.total_quantity != null && !item.display_qty) chips.push("pack");
    chips.push("substitute");
    chips.push("alias");
    chips.push("coarse");
    if (opts.canMerge) chips.push("merge");
    return chips;
  }

  // The shared toggle+Save+"Saved ✓" row every chip ends with (§0.3). `permanentLabel` is the
  // chip-specific wording for the "Always" side (e.g. "Always (edits Settings)"); `onSave(mode)`
  // does the actual write and returns a Promise — this only owns the mode toggle, the disabled
  // state while saving, and the confirmation, not the save itself.
  function persistControls(permanentLabel, onSave) {
    var mode = "list"; // default: this list only (§0.3)
    var toggleWrap = el("div", "persist-toggle");
    var listBtn = el("button", "persist-btn on", "This list only");
    var alwaysBtn = el("button", "persist-btn", permanentLabel);
    function syncToggle() {
      listBtn.className = "persist-btn" + (mode === "list" ? " on" : "");
      alwaysBtn.className = "persist-btn" + (mode === "always" ? " on" : "");
    }
    listBtn.addEventListener("click", function () {
      mode = "list";
      syncToggle();
      saved.hidden = true;
    });
    alwaysBtn.addEventListener("click", function () {
      mode = "always";
      syncToggle();
      saved.hidden = true;
    });
    toggleWrap.appendChild(listBtn);
    toggleWrap.appendChild(alwaysBtn);

    var actions = el("div", "log-controls persist-actions");
    var saveBtn = el("button", "btn-sm primary", "Save");
    var err = el("span", "form-error");
    var saved = el("span", "saved-note", "Saved ✓");
    saved.hidden = true;
    saveBtn.addEventListener("click", function () {
      err.textContent = "";
      saved.hidden = true;
      saveBtn.disabled = true;
      onSave(mode === "always")
        .then(function () {
          saveBtn.disabled = false;
          saved.hidden = false;
        })
        .catch(function (e) {
          saveBtn.disabled = false;
          err.textContent = e.message;
        });
    });
    actions.appendChild(saveBtn);
    actions.appendChild(saved);
    actions.appendChild(err);

    var wrap = el("div");
    wrap.appendChild(toggleWrap);
    wrap.appendChild(actions);
    return wrap;
  }

  function packSizePanel(sessionId, item, onSaved) {
    var wrap = el("div", "pack-size-form");
    wrap.appendChild(el("div", "hdr", "Pack size"));
    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "e.g. 500g pack";
    var qtyInput = el("input");
    qtyInput.type = "number";
    qtyInput.step = "any";
    qtyInput.inputMode = "decimal";
    qtyInput.placeholder = "e.g. 500";
    var unitInput = el("input");
    unitInput.type = "text";
    unitInput.placeholder = "e.g. g";
    wrap.appendChild(miniField("Pack label", labelInput));
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr";
    grid.appendChild(miniField("Pack quantity", qtyInput));
    grid.appendChild(miniField("Unit", unitInput));
    wrap.appendChild(grid);

    wrap.appendChild(
      persistControls("Always (edits Settings)", function (remember) {
        var label = labelInput.value.trim();
        var qty = parseFloat(qtyInput.value);
        if (!label || isNaN(qty) || qty <= 0) {
          return Promise.reject(new Error("Pack label and a positive quantity are required."));
        }
        return api.checklist
          .packSize(sessionId, item.id, {
            purchase_label: label,
            purchase_qty: qty,
            purchase_unit: unitInput.value.trim() || null,
            remember: remember,
          })
          .then(onSaved);
      })
    );
    return wrap;
  }

  function substitutePanel(sessionId, item, picksByName, onSaved) {
    var wrap = el("div", "swap-panel");
    wrap.appendChild(el("div", "hdr", "Substitute this ingredient"));
    var input = el("input");
    input.type = "text";
    input.placeholder = "e.g. regular feta";
    input.className = "settings-name-input";
    wrap.appendChild(miniField("Use instead", input));

    var oQty = el("input"); oQty.type = "number"; oQty.step = "any"; oQty.inputMode = "decimal";
    oQty.placeholder = "e.g. 2";
    var oUnit = el("input"); oUnit.type = "text"; oUnit.placeholder = "e.g. can";
    oUnit.value = item.total_unit || "";
    var sQty = el("input"); sQty.type = "number"; sQty.step = "any"; sQty.inputMode = "decimal";
    sQty.placeholder = "e.g. 350";
    var sUnit = el("input"); sUnit.type = "text"; sUnit.placeholder = "e.g. g";
    var amtGrid = el("div", "ing-grid");
    amtGrid.style.gridTemplateColumns = "1fr 1fr";
    amtGrid.appendChild(miniField("This amount", oQty));
    amtGrid.appendChild(miniField("Unit", oUnit));
    wrap.appendChild(amtGrid);
    var subGrid = el("div", "ing-grid");
    subGrid.style.gridTemplateColumns = "1fr 1fr";
    subGrid.appendChild(miniField("Substitute amount", sQty));
    subGrid.appendChild(miniField("Substitute unit", sUnit));
    wrap.appendChild(subGrid);

    var picks = picksByName[item.ingredient_name] || [];
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
        b.addEventListener("click", function () {
          input.value = p.substitute_name;
          oQty.value = p.original_qty != null ? p.original_qty : "";
          oUnit.value = p.original_unit || item.total_unit || "";
          sQty.value = p.substitute_qty != null ? p.substitute_qty : "";
          sUnit.value = p.substitute_unit || "";
        });
        pickRow.appendChild(b);
      });
      wrap.appendChild(pickRow);
    }

    wrap.appendChild(
      persistControls("Always for this recipe", function (remember) {
        var sub = input.value.trim();
        if (!sub) return Promise.reject(new Error("Type a replacement first."));
        var oq = parseFloat(oQty.value);
        var sq = parseFloat(sQty.value);
        var hasPair = !isNaN(oq) && oq > 0 && !isNaN(sq) && sq > 0 && oUnit.value.trim() && sUnit.value.trim();
        return api.checklist
          .substitute(sessionId, item.id, {
            substitute_name: sub,
            original_qty: hasPair ? oq : null,
            original_unit: hasPair ? oUnit.value.trim() : null,
            substitute_qty: hasPair ? sq : null,
            substitute_unit: hasPair ? sUnit.value.trim() : null,
            remember: remember,
          })
          .then(onSaved);
      })
    );
    return wrap;
  }

  function aliasPanel(sessionId, item, onSaved) {
    var wrap = el("div", "swap-panel");
    wrap.appendChild(el("div", "hdr", "Same item as…"));
    var input = el("input");
    input.type = "text";
    input.placeholder = "e.g. natural yoghurt";
    input.className = "settings-name-input";
    wrap.appendChild(miniField("Also known as", input));

    wrap.appendChild(
      persistControls("Always (edits Settings)", function (remember) {
        var name = input.value.trim();
        if (!name) return Promise.reject(new Error("Type a name first."));
        return api.checklist
          .alias(sessionId, item.id, { alias_name: name, remember: remember })
          .then(onSaved);
      })
    );
    return wrap;
  }

  function coarsePanel(sessionId, item, onSaved) {
    var wrap = el("div", "pack-size-form");
    wrap.appendChild(el("div", "hdr", "Coarse item"));
    wrap.appendChild(
      el("div", "muted", "Skip quantity math — just buy enough packs for how many recipes need it.")
    );
    var labelInput = el("input");
    labelInput.type = "text";
    labelInput.placeholder = "e.g. bunch";
    var countInput = el("input");
    countInput.type = "number";
    countInput.step = "1";
    countInput.inputMode = "numeric";
    countInput.value = "3";
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr";
    grid.appendChild(miniField("Pack label", labelInput));
    grid.appendChild(miniField("Recipes per pack", countInput));
    wrap.appendChild(grid);

    wrap.appendChild(
      persistControls("Always (edits Settings)", function (remember) {
        var n = parseInt(countInput.value, 10);
        if (isNaN(n) || n < 1) return Promise.reject(new Error("Recipes per pack must be a positive whole number."));
        return api.checklist
          .coarse(sessionId, item.id, {
            purchase_label: labelInput.value.trim() || null,
            recipes_per_pack: n,
            remember: remember,
          })
          .then(onSaved);
      })
    );
    return wrap;
  }

  // Builds the "Edit ingredient ▾" toggle + select-exclusive chip row, or null when there's
  // nothing to edit (chips list empty — only possible if canMerge is false and the pack gap
  // doesn't apply, since substitute/alias/coarse are always offered). Appended by
  // checklist.js into the same slot its recipe-breakdown list already lives in.
  //
  // opts: { picksByName, canMerge, onStartMerge(item), onSaved() }
  function build(sessionId, item, opts) {
    var chips = computeChips(item, opts);
    if (!chips.length) return null;

    var container = el("div");
    var toggleBtn = el("button", "btn-link edit-ingredient-toggle", "▾ Edit ingredient");
    var body = el("div");
    body.hidden = true;
    var open = false;
    toggleBtn.addEventListener("click", function () {
      open = !open;
      body.hidden = !open;
      toggleBtn.textContent = (open ? "▴" : "▾") + " Edit ingredient";
    });
    container.appendChild(toggleBtn);
    container.appendChild(body);

    var chipRow = el("div", "ing-swap-picks edit-chip-row");
    var panelSlot = el("div");
    var activeChip = null;
    var panelBuilders = {
      pack: function () { return packSizePanel(sessionId, item, opts.onSaved); },
      substitute: function () { return substitutePanel(sessionId, item, opts.picksByName, opts.onSaved); },
      alias: function () { return aliasPanel(sessionId, item, opts.onSaved); },
      coarse: function () { return coarsePanel(sessionId, item, opts.onSaved); },
    };

    chips.forEach(function (key) {
      var btn = el("button", "link-btn", CHIP_LABELS[key]);
      btn.addEventListener("click", function () {
        if (key === "merge") {
          opts.onStartMerge(item);
          return;
        }
        if (activeChip === key) {
          // select-exclusive: tapping the open chip again closes it
          activeChip = null;
          panelSlot.innerHTML = "";
          syncChipStyles();
          return;
        }
        activeChip = key;
        panelSlot.innerHTML = "";
        panelSlot.appendChild(panelBuilders[key]());
        syncChipStyles();
      });
      chipRow.appendChild(btn);
    });

    function syncChipStyles() {
      Array.prototype.forEach.call(chipRow.children, function (btn, i) {
        btn.classList.toggle("on", chips[i] === activeChip);
      });
    }

    body.appendChild(chipRow);
    body.appendChild(panelSlot);
    return container;
  }

  global.ChecklistPanel = { build: build };
})(window);
