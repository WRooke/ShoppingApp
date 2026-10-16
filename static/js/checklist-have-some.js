/* Checklist — the "I have some" control under a row's amount (2026-10-16, Chunk 6.7, user-feedback batch polish
   batch 3). A leftover tomato when the plan needs 3: type how many are already at home and the
   list only asks for the rest. Always this plan only (never remembered anywhere).

   Visible on the row itself, not behind the ingredient panel (maintainer: a dropdown adds
   friction). A small link under the amount opens a field on the same row.

   State that must survive a re-render lives in the caller's `drafts` object (ingredient name ->
   typed text, present only while the field is open), per docs/ui-ux.md > UI state must not
   silently vanish. See docs/checklist-and-shopping.md > "I have some". */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtNum(n) {
    return n === Math.round(n) ? String(Math.round(n)) : String(Math.round(n * 100) / 100);
  }

  // Only rows with one numeric amount can have "some" taken off: not coarse / "to taste" rows and
  // not an unresolved mixed-unit conflict (the server refuses those too).
  function applies(item) {
    return item.total_quantity != null && !item.needs_review;
  }

  // opts: sessionId, drafts, onItems(items), onDraftChange(), errSlot (the row's feedback line)
  function build(item, opts) {
    var wrap = el("div", "have-some");
    if (!applies(item)) return wrap;
    var key = item.ingredient_name;
    var drafts = opts.drafts;
    var open = Object.prototype.hasOwnProperty.call(drafts, key);

    if (!open) {
      // Hidden on a plain Have it row (nothing to buy), but kept once an amount has been
      // recorded so it can be changed or cleared.
      if (item.have_it === "yes" && item.have_quantity == null) return wrap;
      var link = el("button", "btn-link have-link", item.have_quantity != null ? "Change what I have" : "I have some");
      link.addEventListener("click", function () {
        drafts[key] = item.have_quantity != null ? fmtNum(item.have_quantity) : "";
        opts.onDraftChange();
      });
      wrap.appendChild(link);
      return wrap;
    }

    var unit = item.display_unit || item.total_unit;
    var line = el("div", "have-inline");
    line.appendChild(el("span", null, "I have"));
    var input = el("input");
    input.type = "number";
    input.min = "0";
    input.step = "any";
    input.inputMode = "decimal";
    input.value = drafts[key];
    input.setAttribute("aria-label", "How many " + (item.display_name || key) + " you have");
    input.addEventListener("input", function () {
      drafts[key] = input.value;
    });
    line.appendChild(input);
    line.appendChild(el("span", null, "of " + fmtNum(item.total_quantity) + (unit ? " " + unit : "")));
    var save = el("button", "btn-sm primary", "Save");
    var cancel = el("button", "btn-sm", "Cancel");
    line.appendChild(save);
    line.appendChild(cancel);
    wrap.appendChild(line);
    var err = el("div");
    wrap.appendChild(err);

    cancel.addEventListener("click", function () {
      delete drafts[key];
      opts.onDraftChange();
    });
    save.addEventListener("click", function () {
      global.Feedback.clear(err);
      var raw = String(input.value).trim();
      var n = raw === "" ? 0 : parseFloat(raw);
      if (isNaN(n) || n < 0) {
        global.Feedback.error(err, "Enter how many you have, like 1 or 0.5. Leave it blank to clear it.");
        return;
      }
      save.disabled = true;
      api.checklist
        .haveSome(opts.sessionId, item.id, n > 0 ? n : null)
        .then(function (res) {
          delete drafts[key];
          opts.onItems(res.items || []);
        })
        .catch(function (e) {
          save.disabled = false;
          global.Feedback.error(err, "Couldn’t save — " + global.Feedback.messageOf(e) + ". Tap Save to try again.");
        });
    });
    // Focus after the row is in the page, so a tap on the link lands the cursor in the field.
    setTimeout(function () { if (document.body.contains(input) && !input.value) input.focus(); }, 0);
    return wrap;
  }

  // The row's amount line when an amount is already had: what to buy, then what is had of the
  // total. `base` is the usual text for the full amount (used when nothing is recorded).
  function summaryText(item, base) {
    if (!applies(item) || item.have_quantity == null || item.buy_quantity == null) return base;
    var unit = item.display_unit || item.total_unit;
    var had = "have " + fmtNum(item.have_quantity) + " of " + fmtNum(item.total_quantity) + (unit ? " " + unit : "");
    if (item.buy_quantity <= 0) return had;
    var buy = item.display_qty ? item.display_qty : fmtNum(item.buy_quantity) + (unit ? " " + unit : "");
    var s = "Buy " + buy + " · " + had;
    if (item.note) s += " · " + item.note;
    return s;
  }

  global.ChecklistHaveSome = { build: build, summaryText: summaryText, applies: applies };
})(window);
