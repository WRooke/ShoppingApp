/* Shared row-delete behaviour for every Settings card — Phase 6 Chunk 6.4 (see
   docs/build-status/phase-6-polish.md kickoff decisions #2/#9). All 6 cards (product units,
   substitutions, usuals, ingredient aliases, unit synonyms, coarse ingredients) follow the
   identical "list of editable rows" shape, so this is the "one
   reusable wiring applied consistently" the kickoff decision asked for, rather than six
   near-identical copies.

   Two things this buys, in one place: an in-place DOM removal instead of the old
   listBody.innerHTML="" full rebuild (the scroll-position bug — CLAUDE.md's own Decision
   Dialogue on it), and the shared Undo toast instead of a blocking confirm() dialog. */

(function (global) {
  "use strict";

  // deleteBtn: the row's Delete button. opts:
  //   label       — for the toast text ("Deleted "<label>"")
  //   doDelete()  — the actual DELETE call, returns a promise
  //   recreate()  — called only if Undo is tapped; re-POSTs the row, returns a promise
  //                 resolving to the newly-created object
  //   consequence — optional plain sentence on what removing changed (shown in the toast)
  //   onDeleted(container) — optional; called right after the row is removed, with the element it was in
  //                 (use tidyAfterDelete so counts, empty group cards and the empty state stay true)
  //   row         — the row's own DOM element, removed in place on success
  //   onRestored(created) — appends a freshly-rendered row for the recreated object
  //   onError(err) — optional; called (with the button re-enabled) if the delete itself fails
  function wireDelete(deleteBtn, opts) {
    deleteBtn.addEventListener("click", function () {
      deleteBtn.disabled = true;
      opts
        .doDelete()
        .then(function () {
          var container = opts.row.parentNode;
          opts.row.remove(); // in place — never a full-list rebuild
          if (opts.onDeleted) opts.onDeleted(container);
          function undo() {
            opts
              .recreate()
              .then(function (created) {
                if (opts.onRestored) opts.onRestored(created);
              })
              .catch(function (err) {
                // the row is gone, so no inline spot exists: an error toast with Retry (the shared
                // handler for all six Settings lists)
                global.Toast.show("Couldn't restore “" + opts.label + "” — " + global.Feedback.messageOf(err), {
                  tone: "error", actionLabel: "Retry", onAction: undo,
                });
              });
          }
          global.Toast.show(
            "Removed “" + opts.label + "”." + (opts.consequence ? " " + opts.consequence : ""),
            { actionLabel: "Undo", onAction: undo }
          );
        })
        .catch(function (err) {
          deleteBtn.disabled = false;
          if (opts.onError) opts.onError(err);
        });
    });
  }

  // After an in-place delete, keep what is on screen true (2026-10-11, Chunk 6.7): a group card
  // whose last row went is removed and the others' counts are updated; a sub-group heading with no
  // rows left is removed; an emptied list shows its empty state again. No reload, so scroll and
  // any unsaved typing elsewhere on the page are untouched.
  //   o.listBody  — the list container
  //   o.rowSel    — selector of one row
  //   o.cardSel   — (grouped cards) selector of a group card
  //   o.countSel  — (grouped cards) selector of the count label inside a card
  //   o.countText — (grouped cards) function(n, oldText) -> new count text
  //   o.emptyText — text of the empty state
  function tidyAfterDelete(container, o) {
    if (o.cardSel && container && container.matches && container.matches(o.cardSel)) {
      var left = container.querySelectorAll(o.rowSel).length;
      if (left === 0) {
        container.remove();
      } else {
        var c = container.querySelector(o.countSel);
        if (c && o.countText) c.textContent = o.countText(left, c.textContent);
      }
    }
    // a "sub-group-heading" (name above its rows) with no row after it before the next heading
    Array.prototype.slice.call(o.listBody.querySelectorAll(".sub-group-heading")).forEach(function (h) {
      var next = h.nextElementSibling;
      if (!next || !next.matches(o.rowSel)) h.remove();
    });
    if (!o.listBody.querySelector(o.rowSel) && !o.listBody.querySelector(".empty-state")) {
      var empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = o.emptyText;
      o.listBody.appendChild(empty);
    }
  }

  global.SettingsRowActions = { wireDelete: wireDelete, tidyAfterDelete: tidyAfterDelete };
})(window);
