# Build Status — Phase 7: Checklist Consolidation, Ingredient Panel & Diagnostics

### Phase 7 — Checklist Consolidation, Ingredient Panel & Diagnostics

**Out-of-sequence note, recorded rather than hidden:** this phase was inserted ahead of
[Phase 6](./phase-6-polish.md)'s own closure — Chunk 6.7 (manual user testing) and the Phase 6
review are both still open — because the maintainer sent a 5-item feedback/change-request
document (2026-09-29) that needed prompt handling, not because Phase 6 was actually finished.
This is a deliberate, acknowledged deviation from
[Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking)'s "build and
verify each phase before starting the next," not an oversight. Phase 6 Chunk 6.7 + its review
remain the next open item on the original roadmap once this phase's own review below is signed
off. (A separate, previously-planned "Shop Layout Reorganisation" body of work had informally
been called "Phase 7" in planning notes outside this repo before this phase existed in the
docs — nothing in CLAUDE.md or `docs/` ever committed to that numbering, so no renumbering was
needed here; that work is Phase 8 when it starts.)

Full design plan: `C:\Users\User\.claude\plans\harmonic-leaping-waffle.md` (not part of the
repo — kept for the session's own record). This file is the durable summary.

The five feedback items, and which chunk(s) addressed each:
1. Retire the standalone Review screen, merge its useful parts into Checklist — Chunks 7.3, 7.4.
2. Per-ingredient edit surface on Checklist rows (pack size / substitute / alias / coarse item
   / merge) — Chunks 7.1, 7.5.
3. Remove the AI substitution-*flagging* call only, keep manual substitution entirely — Chunk 7.2.
4. Back navigation that always returns to the real previous screen, never "three screens ago" —
   Chunk 7.6.
5. Diagnostics: unslice Recent Errors, add a Copy button, fix its contrast/layout, quiet
   WinError 10054 noise — Chunk 7.7.

- [x] **Chunk 7.1 — Mockup gate.** Interactive mockup at
  https://claude.ai/artifact/B6SiNLcKvND7tWnjdrsXMf, four revision rounds. Locked design: tap a
  row's name to expand **only the recipe breakdown** first (read-only, no chip needed — every
  expanded row has one); a nested **"Edit ingredient ▾"** toggle underneath, shown only when the
  row has something to edit, reveals a **select-exclusive** chip row (**pack size, substitute,
  alias, coarse item, merge** — unit spelling dropped entirely, stays Settings-only); Have
  it/Need it stay as labelled buttons on the collapsed row, untouched; every chip sub-panel ends
  with the this-list-only/permanent toggle, an explicit Save, and a "Saved ✓" confirmation. A
  true bottom-sheet pattern (the maintainer's original phrasing) was considered and explicitly
  declined for now in favour of this codebase's only existing inline-expand pattern — kept on
  record in [Checklist, AnyList Push & Shopping List Layout](../checklist-and-shopping.md) as a
  noted alternative, not dropped.

- [x] **Chunk 7.2 — Remove the AI substitution-flagging call only.** Scope corrected mid-plan
  after the maintainer's own clarifying answer ("why would it delete the substitutions? I still
  want to substitute stuff, I just don't want to waste an AI call that adds next to no value") —
  every manual substitution mechanism (`remembered_substitutions`, the Settings CRUD, ad-hoc
  swap UI, `resolved_ingredient`) stayed fully intact; only Gemini's `flag_substitutions()` call
  and its orchestration step, prompt, schema fields, and the "AI suggests: X" hint UI were
  removed. Capture drops from a 3-call to a 2-call flow (extract → sections). 677 tests passed
  at this chunk, including a live headless check that capture still completes with only 2
  progress steps. See [Recipe Capture](../recipe-capture.md#recipe-capture--ai-extraction) and
  [Ingredient Handling](../ingredient-handling.md#ingredient-handling--normalisation-substitution-aliases--units).

- [x] **Chunk 7.3 — Checklist load triggers consolidation + recipe-breakdown surfacing.**
  `load_checklist()` now always calls `consolidate_session_with_breakdown()` on every load, not
  just when empty — corrected during implementation from the original plan (recomputing only on
  an empty session couldn't produce `recipe_breakdown` on every subsequent load, which Chunk 7.4
  needed). `ChecklistNotReadyError` removed entirely, including its `main.py` 409 handler. 679
  tests passed. See [Checklist, AnyList Push & Shopping List
  Layout](../checklist-and-shopping.md#the-ingredient-panel-2026-09-30-chunk-75).

- [x] **Chunk 7.4 — Delete Review, wire Plan → Checklist directly.** `session-review.js`
  deleted outright (not kept dormant); Plan's sticky action links straight to
  `#/checklist/<id>`; step indicator collapses `Plan → Review → Checklist → Push` to
  `Plan → Checklist → Push`; the recipe-breakdown display folded into Checklist's own row
  expansion (Chunk 7.1's approved shell). `HANDOVER-review-checklist-merge.md`'s resolution
  folded into `checklist-and-shopping.md`/`scaling-and-consolidation.md`, then the handover file
  deleted. 680 tests passed, including an end-to-end browser test driving the real Plan button
  click with zero prior `/consolidate` calls.

- [x] **Chunk 7.5 — Remaining panel sections + session-scoped override store.** New file
  `static/js/checklist-panel.js` (split out once `checklist.js` hit the file-size guideline).
  `session_ingredient_merges` extended with a `kind` discriminator (`merge` | `substitute` |
  `pack_size` | `coarse`) plus 4 new columns via migration `c7c1ecd37ec8`, tested round-trip
  (upgrade/downgrade/upgrade) against a real scratch DB per CLAUDE.md rule 3 — resolves the
  override-persistence question `HANDOVER-review-checklist-merge.md` had left open, by extending
  the existing merge-store mechanism rather than building a parallel one, per the maintainer's
  explicit ask that it "gel with the merge functionality just implemented."
  `session_consolidation.py` reads this table itself on every consolidate call now (the
  `ConsolidateRequest.overrides` request-body shape is gone). Resolution order: recipe-level
  `resolved_ingredient` → session substitute override → alias → session merge override → (pack
  size / coarse apply separately, at the quantity/display stage). Substitute/Alias/Coarse item
  chips always offered; Pack size gated on the existing gap condition; Merge on 2+ rows (hands
  off to the existing screen-level "Select to merge" mode rather than a second mechanism — Merge
  and Alias write through the identical `ingredient_aliases` mechanism, confirmed against the
  real code, not just similar in spirit). **Merge/Alias false-positive risk documented, not
  solved** — see [Deferred Decisions](../deferred-decisions.md#deferred-decisions)'s "No
  persistent 'don't suggest this pairing again' memory" row (a real production example: Fix 5's
  rejected "flour"/"plain flour" suggestion); mitigated only by Save always being explicit,
  never auto-applied. 698 tests passed.

- [x] **Chunk 7.6 — Back-navigation fixes.** New file `static/js/panel-back-guard.js` —
  history-balanced: exactly one `close()` function ever closes the panel, whether triggered by
  `popstate` (hardware/Android back, the browser's own back control, and the in-app ← link are
  indistinguishable at this level — one listener covers all three) or by a link tap while the
  panel is open (intercepted globally in the capturing phase, since a plain hash-link click
  fires `hashchange` but never `popstate`). Checklist scroll position captured on `unmount()`,
  restored once on the next `mount()`. Found (documented, not fixed — explicitly out of scope)
  the same same-hash-DOM-swap bug class in `capture.js`'s post-capture transition — see
  [Deferred Decisions](../deferred-decisions.md#deferred-decisions). 701 tests passed, including
  3 covering the maintainer's exact flagged scenarios (panel-closes-before-navigate, link-tap-
  from-open-panel leaves the stack balanced, scroll restore).

- [x] **Chunk 7.7 — Diagnostics (5a–5d).** `/recent-errors` returns every ERROR+ entry in the
  ring buffer instead of a hard `[:10]` slice; ring buffer cap raised 1000 → 5000
  (`app/log_config.py::RING_BUFFER_MAXLEN`). "Copy errors" button on the Recent Errors card
  (always ERROR+), copying `timestamp | level | logger: message` + full traceback per entry via
  `navigator.clipboard.writeText`, with a Toast confirmation. `.log-line`'s message column
  widened, `.log-time`/`.log-trace` moved off the low-contrast `--text-dim` onto `--text`,
  `.errors-box`'s hardcoded `#fdf3f3` onto `var(--danger-tint)` (adapts in dark mode). A
  `logging.Filter` on the `asyncio` logger downgrades WinError 10054
  (`ConnectionResetError`/WSAECONNRESET — routine on a home LAN/WiFi) from ERROR to DEBUG,
  matched on the exception object itself (type + `.winerror`), not a message string, and scoped
  to that one logger, not a blanket exception handler. 707 tests passed (5 new filter tests, 1
  new ">10 entries" router test); 5b/5c verified live via `scripts/cdp.py` against a seeded
  scratch server (14 ERROR entries all rendered and copied correctly in the right format; a
  seeded WinError 10054 record confirmed excluded from `/recent-errors` in the same run). See
  [Diagnostics & Logging](../diagnostics-and-logging.md#diagnostics--logging).

- [x] **Chunk 7.8 — Phase-end review.** Full `pytest` run: **708 pass** (689 backend + 19
  frontend). Full live walkthrough via `scripts/cdp.py` against a seeded scratch server,
  integration-style (not just each chunk's own isolated check): create a recipe → session → Plan
  screen shows the collapsed `Plan → Checklist → Push` indicator with no Review control anywhere
  → straight to Checklist with zero prior `/consolidate` call, items render correctly → expand a
  row (breakdown shown) → "Edit ingredient" reveals the select-exclusive chip row (Substitute /
  Alias / Coarse item / Merge — no Pack size chip on an item that already resolved cleanly,
  confirming the gap-gating) → Have it/Need it tappable without opening the panel → Back once
  closes the panel with the route unchanged, Back again returns to the real previous screen
  (Plan) — the exact "three screens ago" scenario the maintainer originally flagged, now
  confirmed fixed end to end, not just in each chunk's own narrower test → scroll down, visit a
  recipe, return, scroll position restored → Push to AnyList (fake mode) confirms → Diagnostics
  page shows zero errors throughout the run.

  **One real bug found during this review's own screenshot pass** (independently flagged by the
  maintainer looking at the same screenshot): `.checklist-row` is a `flex` container with no
  `flex-wrap`, so the expand-slot (recipe breakdown + edit panel) — appended as a third flex
  child with an inline `flex-basis: 100%`, meant to drop onto its own full-width line beneath
  the row per `rowNameParts()`'s own docstring — never actually got that line break; without
  `flex-wrap`, `flex-basis` alone doesn't force one, so the default `flex-shrink: 1` instead
  squeezed the quantity text down to a sliver narrow enough to wrap character-by-character.
  Fixed with `flex-wrap: wrap` on `.checklist-row`
  (`static/css/components-screens.css`). Confirmed via live screenshot before/after, and locked
  in with a new geometry-based regression test,
  `test_expanded_row_meta_text_is_not_squeezed_onto_its_own_line`
  (`tests/frontend/test_frontend_regressions.py`) — checked to actually fail without the fix
  (reverted it and re-ran to confirm) before being counted as a real regression guard, not just
  a passing assertion. This is the +1 test between Chunk 7.7's 707 and this review's 708.

  **Docs re-checked**, each already updated chunk-by-chunk rather than left to this review:
  [Checklist, AnyList Push & Shopping List Layout](../checklist-and-shopping.md) (the ingredient
  panel section, the Review→Checklist merge resolution, the recipe-breakdown section, the
  back-guard paragraph), [Recipe Capture](../recipe-capture.md) (2-call flow),
  [Ingredient Handling](../ingredient-handling.md) (AI-flagging removal, still-intact manual
  substitution), [Scaling & Consolidation](../scaling-and-consolidation.md) (breakdown no longer
  review-screen-only), [Diagnostics & Logging](../diagnostics-and-logging.md) (ring buffer cap
  now documented, WinError filter documented, "last 10" language gone), and
  [Deferred Decisions](../deferred-decisions.md) (Merge/Alias false-positive risk row, the
  capture.js same-hash-DOM-swap finding, point-of-need row marked resolved). CLAUDE.md's
  manifest gains this file's own row (below this phase's kickoff).

**Deliverable:** Checklist is now the one screen for shopping-list prep — consolidates itself,
shows the per-recipe breakdown, and lets you fix an ingredient (pack size, substitute, alias,
coarse item, merge) right on the row instead of a Settings trip, all session-scoped by default
with an explicit permanent option. Back always goes where you'd expect, including through an
open panel. Diagnostics surfaces every real error, lets you copy them out, and no longer drowns
them in routine Windows connection-reset noise.

**Next:** resume [Phase 6](./phase-6-polish.md) — Chunk 6.7 (manual user testing) and its
review are still open.
