/* On-the-fly ingredient-name alias nudge (Fix 4, 2026-09-27/28 — CLAUDE.md > Ingredient
   Handling > Ingredient Aliases). Mirrors unit-hints.js's Layer C duplicate-unit nudge
   structurally, applied to the ingredient NAME field instead of the unit field: on blur, if
   what's typed is close to an already-known ingredient name but not an exact (post-
   normalisation) match, offer a dismissible, never-blocking nudge with two one-tap actions.

   Complementary to Fix 1: a plain plural/hyphen variant of an already-known name already
   merges silently at consolidation time with no alias needed, so this nudge only fires for a
   genuine different-wording pair (matched against the *normalised* form of both the typed text
   and the known-names list, so it never nudges about something Fix 1 already handles).

   Client-side normalisation gap (deliberate, documented, see the ingredient-name-matching
   plan's Fix 4 grounding pass): this file ports only the HAND-ROLLED portion of
   app/services/text_normalize.py's singularise() rules (the US whitelist, "-ies", the
   sibilant-suffix "-es" drop, the generic "-s" drop). It does NOT replicate the "-ves"/true-
   irregular branches that delegate to the `inflect` library server-side (no JS equivalent is
   vendored in this no-build-step app). Worst case: an occasional missed nudge-suppression for a
   rare pair like "olive"/"olives" or "goose"/"geese" — a cosmetic miss, dismissible with one
   tap, never a wrong merge and never a blocked save, same safe-failure direction as every other
   heuristic in this app. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  var HYPHEN_FAMILY = /[-‐‑‒–—]/g;
  var US_WHITELIST = { asparagus: true, couscous: true, hummus: true, citrus: true };

  // Mirrors text_normalize.py::base_norm exactly (no inflect dependency in this part -- fully
  // portable): lowercase, fold hyphens/dashes to a space, collapse whitespace.
  function baseNorm(name) {
    return (name || "")
      .trim()
      .toLowerCase()
      .replace(HYPHEN_FAMILY, " ")
      .split(/\s+/)
      .filter(function (s) { return s.length; })
      .join(" ");
  }

  // Trailing-word-only singularisation -- the hand-rolled subset of
  // text_normalize.py::_singularise_word (see this file's header for the documented gap).
  function singulariseWord(word) {
    if (US_WHITELIST[word]) return word;
    if (word.length > 4 && word.slice(-3) === "ies") return word.slice(0, -3) + "y";
    if (word.length > 4 && /(?:ses|xes|zes|ches|shes|oes)$/.test(word)) return word.slice(0, -2);
    if (word.length > 3 && word.charAt(word.length - 1) === "s" && word.slice(-2) !== "ss") {
      return word.slice(0, -1);
    }
    return word;
  }

  function normalise(name) {
    var normed = baseNorm(name);
    var idx = normed.lastIndexOf(" ");
    if (idx === -1) return singulariseWord(normed);
    return normed.slice(0, idx + 1) + singulariseWord(normed.slice(idx + 1));
  }

  // Same plain edit-distance helper as unit-hints.js -- ingredient names are short phrases, so
  // this is cheap regardless of algorithm choice even run against the whole known-names list.
  function levenshtein(a, b) {
    var m = a.length, n = b.length;
    var d = [];
    for (var i = 0; i <= m; i++) d.push([i]);
    for (var j = 0; j <= n; j++) d[0][j] = j;
    for (i = 1; i <= m; i++) {
      for (j = 1; j <= n; j++) {
        d[i][j] = a.charAt(i - 1) === b.charAt(j - 1)
          ? d[i - 1][j - 1]
          : 1 + Math.min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1]);
      }
    }
    return d[m][n];
  }

  // Returns the closest known (already-normalised) name worth suggesting, or null if `typed`
  // already matches one exactly (post-normalisation) or nothing is close enough. Threshold
  // scales with length -- a short name needs a tighter tolerance (a 1-character difference on a
  // short word can easily be a genuinely different ingredient), tuned by hand-testing.
  function closestMatch(typed, knownNames) {
    var normedTyped = normalise(typed);
    if (!normedTyped || !knownNames || !knownNames.length) return null;
    if (knownNames.indexOf(normedTyped) !== -1) return null; // already known, nothing to suggest
    var best = null;
    var bestDist = Infinity;
    knownNames.forEach(function (k) {
      var dist = levenshtein(normedTyped, k);
      if (dist < bestDist) {
        bestDist = dist;
        best = k;
      }
    });
    var threshold = normedTyped.length <= 6 ? 1 : normedTyped.length <= 12 ? 2 : 3;
    return best && bestDist > 0 && bestDist <= threshold ? best : null;
  }

  // Module-level cache -- one flat GET, shared across every attach() call on the page (unlike
  // UnitHints' own per-ingredient-name cache, this list isn't parameterised).
  var _namesCache = null;
  function fetchKnownNames(cb) {
    if (_namesCache) {
      cb(_namesCache);
      return;
    }
    api.recipes
      .ingredientNames()
      .then(function (data) {
        _namesCache = data.names || [];
        cb(_namesCache);
      })
      .catch(function () {
        cb([]);
      });
  }

  // This file's own local copy of the same 4-field amount/unit grid shape already duplicated in
  // settings-ingredient-aliases.js / settings-substitutions.js / checklist.js -- this codebase's
  // established convention for this exact class of small, self-contained UI helper, not
  // something to extract into a shared module. Field names match IngredientAliasCreate exactly.
  function pairFields() {
    function num() {
      var n = el("input");
      n.type = "number";
      n.step = "any";
      n.inputMode = "decimal";
      return n;
    }
    function txt() {
      var t = el("input");
      t.type = "text";
      return t;
    }
    function miniField(labelText, inputEl) {
      var wrap = el("div", "mini-field");
      wrap.appendChild(el("label", null, labelText));
      wrap.appendChild(inputEl);
      return wrap;
    }
    var aqty = num();
    var aunit = txt();
    var cqty = num();
    var cunit = txt();
    var grid = el("div", "ing-grid");
    grid.style.gridTemplateColumns = "1fr 1fr 1fr 1fr";
    grid.appendChild(miniField("This amount", aqty));
    grid.appendChild(miniField("Unit", aunit));
    grid.appendChild(miniField("= Existing amount", cqty));
    grid.appendChild(miniField("Unit (blank = count)", cunit));
    return {
      grid: grid,
      values: function () {
        var aq = parseFloat(aqty.value);
        var cq = parseFloat(cqty.value);
        return {
          alias_qty: isNaN(aq) ? null : aq,
          alias_unit: aunit.value.trim() || null,
          canonical_qty: isNaN(cq) ? null : cq,
          canonical_unit: cunit.value.trim() || null,
        };
      },
    };
  }

  // Wires the nudge onto one ingredient-name field. Returns the container element the caller
  // appends into the row (matching unit-hints.js's own return-a-wrap-element pattern).
  function attach(nameInput) {
    var wrap = el("div", "ingredient-name-hints muted");

    function clear() {
      wrap.innerHTML = "";
    }

    function showNudge() {
      clear();
      var typed = nameInput.value.trim();
      if (!typed) return;
      fetchKnownNames(function (knownNames) {
        var suggestion = closestMatch(typed, knownNames);
        if (!suggestion) return;

        var nudge = el("div", "ingredient-name-hints-nudge");
        nudge.appendChild(document.createTextNode('did you mean "' + suggestion + '"? '));

        var useBtn = el("button", "link-btn", "use it");
        useBtn.type = "button";
        useBtn.addEventListener("click", function () {
          nameInput.value = suggestion;
          clear();
        });

        var keepBothBtn = el("button", "link-btn", "keep both, treat as one shopping item");
        keepBothBtn.type = "button";

        var dismissBtn = el("button", "link-btn", "keep \"" + typed + "\"");
        dismissBtn.type = "button";
        dismissBtn.addEventListener("click", clear);

        nudge.appendChild(useBtn);
        nudge.appendChild(keepBothBtn);
        nudge.appendChild(dismissBtn);
        wrap.appendChild(nudge);

        var pair = null; // { grid, values() } from pairFields(), only when expanded
        var form = null;
        keepBothBtn.addEventListener("click", function () {
          if (form) {
            form.remove();
            form = null;
            return;
          }
          form = el("div", "pack-size-form");
          var pairLinkRow = el("div", "meta-row");
          var pairLink = el("button", "btn-link", "Not the same amount? Tap to set the equivalent");
          pairLinkRow.appendChild(pairLink);
          form.appendChild(pairLinkRow);

          var err = el("span", "form-error");
          var saveBtn = el("button", "btn-sm primary", "Save");
          var actions = el("div", "log-controls");
          actions.appendChild(saveBtn);
          actions.appendChild(err);

          pairLink.addEventListener("click", function () {
            if (pair) {
              pair.grid.remove();
              pair = null;
              pairLink.textContent = "Not the same amount? Tap to set the equivalent";
              return;
            }
            pair = pairFields();
            form.insertBefore(pair.grid, actions);
            pairLink.textContent = "Hide the amount equivalence";
          });

          saveBtn.addEventListener("click", function () {
            err.textContent = "";
            var values = pair ? pair.values() : {};
            if (pair && (values.alias_qty == null || values.canonical_qty == null)) {
              err.textContent = "Enter both amounts, or collapse the equivalence field to skip it.";
              return;
            }
            saveBtn.disabled = true;
            api.settings.ingredientAliases
              .create({
                alias_name: typed,
                canonical_name: suggestion,
                alias_qty: values.alias_qty != null ? values.alias_qty : null,
                alias_unit: values.alias_unit || null,
                canonical_qty: values.canonical_qty != null ? values.canonical_qty : null,
                canonical_unit: values.canonical_unit || null,
              })
              .then(function () {
                // The typed text is deliberately left in the field -- a recipe keeps showing
                // exactly what it said (CLAUDE.md > Ingredient Aliases); the new alias is what
                // makes it resolve correctly at consolidation time from here on.
                global.Toast.show('Saved -- "' + typed + '" will be treated as "' + suggestion + '" from now on.');
                clear();
              })
              .catch(function (e) {
                saveBtn.disabled = false;
                err.textContent = e.message;
              });
          });

          form.appendChild(actions);
          nudge.appendChild(form);
        });
      });
    }

    nameInput.addEventListener("blur", showNudge);

    return wrap;
  }

  global.IngredientNameHints = { attach: attach, closestMatch: closestMatch, normalise: normalise };
})(window);
