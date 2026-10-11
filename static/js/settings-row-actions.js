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
  //   row         — the row's own DOM element, removed in place on success
  //   onRestored(created) — appends a freshly-rendered row for the recreated object
  //   onError(err) — optional; called (with the button re-enabled) if the delete itself fails
  function wireDelete(deleteBtn, opts) {
    deleteBtn.addEventListener("click", function () {
      deleteBtn.disabled = true;
      opts
        .doDelete()
        .then(function () {
          opts.row.remove(); // in place — never a full-list rebuild
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

  global.SettingsRowActions = { wireDelete: wireDelete };
})(window);
