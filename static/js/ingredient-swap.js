/* Per-ingredient substitution control (Phase 3.9 M4). Used by capture-review.js.
   A collapsed "Swap?" toggle that expands to: a replacement text field (pre-filled
   from the AI flag or the top saved swap), a note field, quick-pick buttons for any
   saved swaps, and a "save this swap" checkbox. Nothing here applies a swap on its
   own — the parent form includes getState() in the confirm payload, and the human
   confirmed it by typing/picking. See CLAUDE.md > AI Provider Migration >
   Ingredient Substitution Flagging. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // flag:  { original, suggested_substitute, note } | null   (AI's per-recipe suggestion)
  // picks: [{ substitute_name, note }]                        (this ingredient's saved swaps)
  function create(flag, picks) {
    picks = picks || [];
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

    var rememberBox = el("input");
    rememberBox.type = "checkbox";
    var rememberLabel = el("label", "ing-swap-remember");
    rememberLabel.appendChild(rememberBox);
    rememberLabel.appendChild(document.createTextNode(" save this swap"));

    var clearBtn = el("button", "link-btn", "clear");
    clearBtn.addEventListener("click", function () {
      subInput.value = "";
      noteInput.value = "";
      rememberBox.checked = false;
    });

    body.appendChild(el("span", "muted", "→"));
    body.appendChild(subInput);
    body.appendChild(noteInput);

    if (picks.length) {
      var pickRow = el("div", "ing-swap-picks");
      pickRow.appendChild(el("span", "muted", "saved: "));
      picks.forEach(function (p) {
        var b = el("button", "link-btn", p.substitute_name);
        b.title = p.note || "";
        b.addEventListener("click", function () {
          subInput.value = p.substitute_name;
          if (p.note) noteInput.value = p.note;
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
      // pre-fill from the AI flag but leave it collapsed; the user opens + confirms
      subInput.value = flag.suggested_substitute;
      if (flag.note) noteInput.value = flag.note;
    } else if (picks.length === 1) {
      subInput.value = picks[0].substitute_name;
      if (picks[0].note) noteInput.value = picks[0].note;
    }

    toggle.addEventListener("click", function () {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden ? "Swap?" : "Swap ▾";
    });

    function getState() {
      var resolved = subInput.value.trim();
      if (!resolved) return { resolved_ingredient: null, substitution_note: null, remember: false };
      return {
        resolved_ingredient: resolved,
        substitution_note: noteInput.value.trim() || null,
        remember: !!rememberBox.checked,
      };
    }

    return { el: wrap, getState: getState };
  }

  global.IngredientSwap = { create: create };
})(window);
