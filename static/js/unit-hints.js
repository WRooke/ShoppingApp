/* Shared per-ingredient unit quick-picks + a duplicate-unit nudge (2026-09-12, Ingredient
   Unit Handling Layers B + C). Used by recipe-form.js (manual entry), recipe-edit.js
   (editing), and capture-review.js (capture confirm) — one place for this UI per CLAUDE.md
   > Code Architecture & Maintainability, same precedent as dup-warn.js.

   Layer B: fetches units already used for the current ingredient name (pooled across its
   alias group server-side) and offers them as quick-pick buttons — reduces the chance of a
   fresh spelling variant ever being typed.
   Layer C: on the unit field's blur, if what's typed doesn't match anything known but is
   close to something that is, nudges toward the existing one. Never blocks — dismissing the
   nudge keeps whatever was typed. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // Mirrors app/services/unit_synonyms.py > strip_plural() exactly, so the duplicate check
  // here agrees with what the backend will actually resolve a typed unit to.
  function stripPlural(unit) {
    var u = (unit || "").trim().toLowerCase();
    if (u.length > 4 && /(?:ses|xes|zes|ches|shes|oes)$/.test(u)) return u.slice(0, -2);
    if (u.length > 3 && u.charAt(u.length - 1) === "s" && u.slice(-2) !== "ss") {
      return u.slice(0, -1);
    }
    return u;
  }

  // Plain edit distance, no library — unit strings are short (a handful of characters), so
  // this is cheap regardless of algorithm choice.
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

  // Returns the closest known unit worth suggesting, or null if `typed` already matches one
  // (post plural-strip) or nothing is close enough. Threshold is deliberately tight for
  // short words (a 1-character difference on a 2-3 letter unit like "g"/"ml" can easily be a
  // genuinely different unit, not a typo) and a little looser for longer words.
  function closestMatch(typed, knownUnits) {
    var strippedTyped = stripPlural(typed);
    if (!strippedTyped || !knownUnits || !knownUnits.length) return null;
    if (knownUnits.indexOf(strippedTyped) !== -1) return null; // already known, nothing to suggest
    var best = null;
    var bestDist = Infinity;
    knownUnits.forEach(function (k) {
      var dist = levenshtein(strippedTyped, stripPlural(k));
      if (dist < bestDist) {
        bestDist = dist;
        best = k;
      }
    });
    var threshold = strippedTyped.length <= 4 ? 1 : 2;
    return best && bestDist > 0 && bestDist <= threshold ? best : null;
  }

  // Wires quick-picks + the duplicate nudge onto one ingredient row. Returns the container
  // element the caller appends into the row (matching the row-appends-its-own-children
  // pattern already used everywhere). Best-effort throughout — a failed fetch just means no
  // hints show, never an error the user has to deal with.
  function attach(nameInput, unitInput) {
    var wrap = el("div", "unit-hints muted");
    var cache = { name: null, units: [] };

    function fetchKnown(name, cb) {
      if (cache.name === name) {
        cb(cache.units);
        return;
      }
      api.recipes
        .ingredientUnits(name)
        .then(function (data) {
          cache = { name: name, units: data.units || [] };
          cb(cache.units);
        })
        .catch(function () {
          cb([]);
        });
    }

    function showQuickPicks() {
      wrap.innerHTML = "";
      var name = nameInput.value.trim();
      if (!name) return;
      fetchKnown(name, function (units) {
        if (!units.length) return;
        var picks = el("span", "unit-hints-picks");
        picks.appendChild(document.createTextNode("used before: "));
        units.forEach(function (u) {
          var btn = el("button", "link-btn", u);
          btn.type = "button";
          btn.addEventListener("click", function () {
            unitInput.value = u;
          });
          picks.appendChild(btn);
        });
        wrap.appendChild(picks);
      });
    }

    function showDuplicateNudge() {
      var existingNudge = wrap.querySelector(".unit-hints-nudge");
      if (existingNudge) wrap.removeChild(existingNudge);
      var typed = unitInput.value.trim();
      var name = nameInput.value.trim();
      if (!typed || !name) return;
      fetchKnown(name, function (units) {
        var suggestion = closestMatch(typed, units);
        if (!suggestion) return;
        var nudge = el("span", "unit-hints-nudge");
        nudge.appendChild(
          document.createTextNode('did you mean "' + suggestion + '"? ')
        );
        var useBtn = el("button", "link-btn", "use it");
        useBtn.type = "button";
        useBtn.addEventListener("click", function () {
          unitInput.value = suggestion;
          if (nudge.parentNode) wrap.removeChild(nudge);
        });
        var dismissBtn = el("button", "link-btn", "keep \"" + typed + "\"");
        dismissBtn.type = "button";
        dismissBtn.addEventListener("click", function () {
          if (nudge.parentNode) wrap.removeChild(nudge);
        });
        nudge.appendChild(useBtn);
        nudge.appendChild(dismissBtn);
        wrap.appendChild(nudge);
      });
    }

    nameInput.addEventListener("blur", showQuickPicks);
    unitInput.addEventListener("blur", showDuplicateNudge);

    return wrap;
  }

  global.UnitHints = { attach: attach, closestMatch: closestMatch, stripPlural: stripPlural };
})(window);
