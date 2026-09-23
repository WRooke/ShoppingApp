# Handover — Review vs. Checklist screen redundancy

**Status: investigation complete, direction proposed, NOT implemented.** Written 2026-09-24 for
a future session (or the maintainer) to pick up independently. Deliberately kept outside the
`docs/` Manifest tree (see `CLAUDE.md`) — this is an undecided proposal, not a settled spec.
If a decision is made to proceed, fold the relevant parts into `docs/checklist-and-shopping.md`
and `docs/scaling-and-consolidation.md` as usual, and delete this file.

## The original question

The "Review ingredients & shopping list" screen (`static/js/session-review.js`, reached between
Plan and Checklist) was suspected of being low-value and largely redundant with the Checklist
screen (`static/js/checklist.js`). Investigate what Review does that Checklist doesn't already
cover, determine whether it's genuinely redundant, and propose whether to merge it into
Checklist, keep it separate, or reduce its scope.

## Investigation finding: partially redundant, not fully

Feature-by-feature comparison, confirmed directly in the code:

| Review does this | Checklist today |
|---|---|
| Triggers `POST /sessions/{id}/consolidate` (`session-review.js > runConsolidate()`) — the **only** frontend call site for this endpoint (confirmed via grep across `static/js`) | Never triggers it — `app/services/checklist.py > load_checklist()` requires consolidation to have already run, raising `409 CHECKLIST_NOT_CONSOLIDATED` (`ChecklistNotReadyError`) otherwise |
| Displays name / quantity / note / staple-flag per consolidated item (`renderItemRow`) | **Duplicated deliberately** — `checklist.js`'s `qtyText()` carries a comment explicitly noting it was matched to Review's `renderItemRow` so both screens show the same information |
| A `needs_review` (irreconcilable units) line is shown as a **plain warning line** — `"⚠ " + note` — with no resolve mechanism | **Strictly more capable** — `checklist.js > reviewGroup()` (lines 189–241) has a real resolve control: quick-pick buttons from `item.review_options`, plus a manual amount/unit entry, both calling `POST /checklist/{id}/items/{id}/resolve`. Review has no equivalent at all. |
| Expandable **"which recipe is this ingredient from"** breakdown (`item.recipe_breakdown`, toggle button per row) | **Nothing** — `recipe_breakdown` is deliberately ephemeral: computed fresh only inside the `POST /consolidate` response (`routers/sessions.py`, via `model_copy()` after validation), never persisted to `session_checklist_items`. `checklist.js` contains zero references to `recipe_breakdown` anywhere. This is by design — `docs/scaling-and-consolidation.md`'s "Which Recipe Is This Ingredient From" section explicitly says: "review-screen-only... it doesn't need to survive to the checklist screen... the ingredient-review step is the one place this check makes sense, right before the household commits to 'do I have this?' and pushes." |
| A hand-rolled, **session-only ingredient substitution/swap form** (`renderSwapForm`, lines 218–314) — name swap + optional qty/unit equivalence pair, quick-picks from `remembered_substitutions`, an `askRemember()` "save this swap?" prompt | **Nothing.** This is *not* the shared `ingredient-swap.js` module — that module is mounted only in `capture-review.js`, for AI-flagged substitutions at recipe-capture time, a completely separate screen/feature. Review's swap form is an independent, parallel implementation with no shared code. |
| Only forward action is a plain `<a href="#/checklist/...">` anchor — no save/confirm API call of its own beyond the consolidate that already ran | — |

## What would be lost by simply deleting Review

If Review were deleted and "confirm and move on" pointed straight at Checklist, three things
would be lost outright, with no replacement anywhere in Checklist's current code:
1. The expandable per-recipe "which recipe is this ingredient from" breakdown.
2. The session-only ingredient swap/substitution form, including its "remember as a quick-pick"
   save flow.
3. The trigger point for consolidation itself — something would still need to call
   `POST /sessions/{id}/consolidate` before Checklist could load at all, since
   `load_checklist()` refuses to run against an unconsolidated session.

Everything else Review shows today is already shown, at least as well, on Checklist — and
Checklist's own `needs_review` handling is strictly better (a real resolve control vs. a static
warning line).

## Proposed direction, for review — not implemented

Merge Review's two genuinely unique pieces into Checklist and retire Review as a separate
screen/route, rather than keeping two screens that duplicate most of the same display for no
remaining reason:

1. Checklist's own `load()` calls `consolidate` first (passing any session-only overrides — see
   the open question below), then loads the checklist. This collapses the step indicator from
   "Plan → Review → Checklist → Push" to "Plan → Checklist → Push", and removes a click-through
   screen that makes no decision of its own today (its only forward action is a bare link).
2. Move the recipe-breakdown expand/collapse toggle onto each Checklist row, verbatim from
   `session-review.js`'s existing rendering code.
3. Move the substitution swap form onto each Checklist row the same way, verbatim.
4. Retire `session-review.js` and its `#/plan/<id>/review` (or equivalent) route.

## Open items a future session needs to resolve — read all of these before implementing

### 1. Override persistence across page loads (the load-bearing open question)

Today, a session-only substitution override is held in `session-review.js`'s own in-memory
JS state and submitted as part of the *one* `consolidate` call Review makes right before the
user navigates to Checklist — it never needs to survive a page reload, because Review is a
single-use, one-way screen.

If Checklist calls `consolidate` on **every** load (as proposed — including the load right after
item 2's new inline pack-size save, or after a plain page refresh), a swap made in a *previous*
visit needs to keep applying. Two options, neither obviously correct without the maintainer's
input:
- **(a) Auto-apply via `remembered_substitutions`.** Only swaps the user has explicitly ticked
  "remember this" for survive a reload; a one-off, not-remembered swap would silently revert the
  next time Checklist re-consolidates. This changes today's behavior (currently a one-off swap
  lasts exactly as long as the single session, because Review only consolidates once) to
  something narrower (a one-off swap now only lasts until the *next* reload).
- **(b) Client-held override list, resent on every consolidate call.** Checklist would need to
  hold the same session-only override list Review holds today, keep it alive across the
  screen's own re-renders (already how Review does it), AND resend it on every subsequent
  `consolidate` call this session — including the ones triggered by unrelated actions like
  item 2's pack-size save. This preserves today's exact behavior but pushes real state-
  management complexity onto a screen (`checklist.js`) that has stayed comparatively simple so
  far, and raises a question of its own: does a page *reload* (not just a re-render) still lose
  the override, since it's only ever been in-memory JS state? If so, is that acceptable, or does
  it need to move somewhere that survives a reload (which starts to look like a real feature
  addition, not just a screen merge)?

Recommend surfacing this exact question to the maintainer before writing any code — it changes
user-visible behavior, not just where a UI element lives.

### 2. Step indicator wording

The `Plan → Review → Checklist → Push` step indicator is implemented as "its own small copy per
file" in `sessions.js`, `session-review.js`, and `checklist.js` (an established convention in
this file family — see e.g. Chunk 6.3's header comments). If `Review` is dropped, decide: does
it become `Plan → Checklist → Push` (3 steps), or is there a reason to keep a 4-step shape with
different wording? All three copies need updating together if changed — there's no shared
`stepIndicator()` module today, so this is a search-and-fix-all-three, not a one-line change.

### 3. Delete `session-review.js` outright, or keep it dormant?

A judgement call for the maintainer, not an agent: delete the file and its route entirely once
the merge is verified working, or keep it in place but unrouted (a safety net in case the merge
needs reverting)? The project's own precedent elsewhere favors deleting genuinely dead code
rather than leaving unreachable files around (see CLAUDE.md's general "don't leave half-finished
implementations" guidance), but this file's removal is coupled to a real behavior change (item 1
above), so a rollback might be wanted for at least one release cycle.

### 4. Row crowding — a fourth mockup gate, not just three

If this merge proceeds, a single Checklist row could end up with: the have/need one-tap control
(this batch's item 1), the "+ Add pack size" inline-entry affordance (this batch's item 2), the
recipe-breakdown expand toggle, AND the substitution swap form trigger — four interactive
affordances on one row. This plan's items 1 and 2 were each given their own mockup gate; if the
Review merge is picked up, it needs its **own** mockup pass specifically checking that a row
carrying all four doesn't become cluttered or confusing at phone width, per the project's
standing "every UI-visible change gets a mockup" norm — not an incremental add-on to items 1/2's
mockups, since those were approved before this merge was on the table.

## Recommendation

Worth doing — the duplication is real and Checklist's needs_review handling is already better
than Review's. But **do not implement until the maintainer has explicitly answered open item 1**
(override persistence) — that's a real user-facing behavior question, not an implementation
detail this session can decide unilaterally. Items 2–4 are process/sequencing decisions that can
be made at kickoff once item 1 is settled.

If picked up, record the decision in `docs/checklist-and-shopping.md` (Checklist Screen Logic)
and `docs/scaling-and-consolidation.md` ("Which Recipe Is This Ingredient From" — its
"review-screen-only" framing would need updating to reflect the new home), and log it as a
normal chunk under whichever phase is current at the time, replacing this handover file.
