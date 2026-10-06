# Checklist, AnyList Push & Shopping List Layout

## Checklist Screen Logic

At checklist screen load:
0. **Consolidate the session first** (`services/checklist.py > load_checklist()`, **2026-09-30,
   chunk 7.3**) — every load, not just the first. Checklist used to require a separate,
   standalone "Review" screen to have already run `POST /sessions/{id}/consolidate` at least
   once (raising `409 CHECKLIST_NOT_CONSOLIDATED` otherwise); that screen is deleted (chunk
   7.4, below) and Checklist now works standalone, straight from Plan. Safe to do
   unconditionally: consolidation's upsert already preserves `have_it`/`add_to_list`/
   `already_on_anylist` for every line that persists (see [Scaling Logic > "Re-running
   consolidation is a merge, not a rebuild"](./scaling-and-consolidation.md#scaling-logic)).
1. Fetch current AnyList items (names + quantities)
2. For each consolidated ingredient in `session_checklist_items`:
   a. Check if it appears in current AnyList list (fuzzy name match — normalised lowercase,
      strip plurals if needed)
   b. If found: set `already_on_anylist = True`, `have_it = 'yes'` by default
3. Present checklist to user:
   - Items already on AnyList: pre-ticked, shown in a distinct style (user can untick)
   - All other items: unchecked by default
4. User sets each item's `have_it` state via two independent one-tap toggles, "Have it" /
   "Need it" (`static/js/checklist.js`, `.have-need-pair`) — **reworked 2026-09-24**, replacing
   an earlier single button that cycled `unknown → yes → no → unknown` (reaching a specific
   target state from an arbitrary starting one could take up to two taps). Tapping the
   currently-pressed button reverts to `unknown`; tapping either button reaches its target
   state in exactly one tap regardless of the current state. `have_it` stays binary in the data
   model (no `'partial'` — see [Deferred Decisions](./deferred-decisions.md#deferred-decisions)); this was a pure
   interaction-model change, no backend change (`services/checklist.py > update_item()` already
   accepted `have_it`/`add_to_list` independently, with no validation on the transition).
5. Items marked 'no' or where `add_to_list` is True get pushed to AnyList

### The ingredient panel (2026-09-30, chunk 7.5)

The reference implementation of [UI/UX > Design principle: resolve at the point of
need](./ui-ux.md#design-principle-resolve-at-the-point-of-need-not-in-settings) — fixing a
pack size, a substitution, an alias, or a coarse-ingredient marking right here instead of
sending the user to Settings. Superseded the 2026-09-24 standalone "+ Add pack size" link
(below is its full replacement, not an addition alongside it) after a maintainer mockup review
(chunk 7.1, 4 revision rounds — https://claude.ai/artifact/B6SiNLcKvND7tWnjdrsXMf) settled the
design: an inline expand-in-place panel, not a bottom sheet, matching this app's only existing
pattern for this class of control (this section, the needs-review resolve control, and the
merge panel below are all the same interaction idiom — the maintainer's own explicit
preference, kept on record as a possible future reconsideration if rows ever feel cramped).

**Two-level nested expand** (`checklist.js > rowNameParts()` + `checklist-panel.js`):
1. Tapping a row's name (not Have it / Need it, which stay independent) expands it to show the
   recipe breakdown, always, first — see the section below.
2. An **"Edit ingredient ▾" toggle** underneath — shown only when there's something to edit
   (see "which chips appear", below) — reveals a second level: a row of **select-exclusive
   chips**. Tapping a chip replaces whichever one was already open for that row; at most one
   sub-panel shows at a time no matter how many chips exist. Five chips: **Pack size**,
   **Substitute**, **Alias**, **Coarse item**, **Merge**.

**Which chips appear** — point-of-need guardrail, only shown when the gap actually exists:
Pack size only when `item.total_quantity != null && !item.display_qty` (the exact condition
the old standalone link used); Merge only when 2+ regular rows exist to merge with. Substitute,
Alias, and Coarse item are always offered — there's always a valid "add one" action for these,
not a broken state to detect, same standing the now-deleted Review screen's own "Swap" button
had on every row.

**Every chip except Merge ends with the same shared persistence toggle** — "This list only"
(default) vs. "Always…" (worded per chip, e.g. "Always (edits Settings)") — plus an explicit
**Save** button and a **"Saved ✓"** confirmation once pressed (`checklist-panel.js >
persistControls()`). Nothing commits as a side effect of typing or toggling; changing the
toggle after a save clears the confirmation, so it's never ambiguous whether what's currently
showing has actually been written anywhere. Default is "this list only" (not "Always") because
Alias/Pack size/Coarse-item edits are otherwise global and retroactive to every future
session — a slip-of-the-thumb permanent edit mid-shop has a bigger blast radius than a scoped
one.

- **Pack size** (`packSizePanel`) — pack label / quantity / unit, same fields the old
  standalone form had. "This list only" writes a session-scoped
  `session_ingredient_merges` (kind='pack_size') row, read by `session_pack_resolution.py`
  alongside real `product_units` rows for this consolidate pass only (nothing written to
  `product_units`). "Always" writes a real `product_units` row (`POST
  /settings/product-units`, the same endpoint Settings' own "Product units" card uses) — every
  future session resolves it automatically from then on.
- **Substitute** (`substitutePanel`) — an ad-hoc ingredient swap, moved here from the
  now-deleted Review screen's own swap form (chunk 7.4/7.5). See [Ingredient
  Substitution](./ingredient-handling.md#ingredient-substitution) for the full design,
  including what "this list only" vs. "Always" write to and why "Always" here means a
  `remembered_substitutions` quick-pick, not the recipe's own `resolved_ingredient`.
- **Alias** (`aliasPanel`) — "Same item as…", a free-text name to fold into this ingredient.
  Mechanically identical to Merge below (both are a `member_name -> canonical_name` fold); the
  only difference is that Alias takes any typed name, not one picked from another checklist
  row. "This list only" writes the same `session_ingredient_merges` (kind='merge') row Merge's
  own session-scoped mode writes; "Always" writes a real
  [`ingredient_aliases`](./ingredient-handling.md#ingredient-aliases) row.
- **Coarse item** (`coarsePanel`) — pack label (optional) + recipes-per-pack, marking this
  ingredient to skip quantity math for this session ("this list only",
  `session_ingredient_merges` kind='coarse') or permanently ("Always",
  [`coarse_ingredients`](./ingredient-handling.md#ingredient-unit-handling)).
- **Merge** — no sub-panel of its own here; tapping it hands off to the existing
  screen-level "Select to merge" mode below, pre-selecting this row, rather than building a
  second, parallel merge mechanism.

**Re-consolidation, not just a reload, is required for any of this to resolve *this*
session** — as of chunk 7.3, `GET /checklist/{id}` already re-consolidates on every load, so a
plain reload after any chip's save picks everything up automatically; no separate consolidate
call is needed from the frontend any more (the panel's `onSaved` callback is just `load`).
This is safe because consolidation is a **merge, not a rebuild** (see [Scaling Logic >
"Re-running consolidation is a merge, not a
rebuild"](./scaling-and-consolidation.md#scaling-logic)) — `have_it`/`add_to_list`/
`already_on_anylist` are preserved for every line that persists.

**The false-positive risk this inherits** (Merge and Alias both write `ingredient_aliases`
when remembered) is documented, not silently accepted — see
[deferred-decisions.md](./deferred-decisions.md)'s "No persistent 'don't suggest this pairing
again' memory..." row.

**Row expansion is screen-wide select-exclusive** (at most one row's breakdown/panel open at
once, same one-open-at-a-time idiom as the chips within it), backed by a small shared module,
`static/js/panel-back-guard.js` (2026-09-30, chunk 7.6) — pressing Back (hardware button,
browser control, or an Android edge-swipe gesture; all fire the identical `popstate` event)
closes an open row before navigating away, rather than skipping past it. Also intercepts —
globally, in the capturing phase, before the link's own default navigation — any link tapped
while a row is expanded (a recipe-breakdown link, a nav-bar link, anything else), since a plain
forward link click fires `hashchange` but never `popstate`, and would otherwise leave the
guard's synthetic history entry dangling. See the module's own docstring for the full
"why a naive push-one-entry-pop-on-popstate approach silently eats a later Back press"
reasoning — this was the maintainer's own specific concern during review.

### Checklist-time ingredient merge (Fix 3, 2026-09-27; reachable from the ingredient panel's
Merge chip since chunk 7.5)

Rather than requiring a trip to Settings to notice and fix an ingredient-name mismatch (e.g. a
recipe's "corn" and another's "canned corn" showing as two separate lines), the checklist
screen itself offers a **"Select to merge"** mode (`checklist.js`, screen-level toggle shown
only when 2+ regular rows exist — not a permanent per-row control, matching the existing
convention that a row shouldn't carry two competing sets of controls at once). Reachable two
ways: the heading's own "Select to merge" link (select 2+ rows by hand), or the ingredient
panel's Merge chip on any single row (pre-selects that row, then prompts for a second).
Selecting 2+ rows and tapping "Merge (N)" opens a small panel:
- **Keep which name?** — a radio choice of which selected item's name becomes canonical for the
  merge.
- **An optional, dormant "different amount?" field** — collapsed by default (the same
  point-of-need guardrail as the pack-size form: contextual, not a permanent extra control).
  Left collapsed, the merge is a plain rename with quantities summed directly (the common case —
  "capsicum"/"red capsicum" need no ratio at all). Expanded, it takes a
  `member_qty`/`member_unit` → `canonical_qty`/`canonical_unit` equivalence pair (e.g. "4 cob" =
  "1 can"), converting the non-canonical line's amount onto the canonical unit before summing.
  A unit mismatch at consolidation time falls back to the existing `needs_review` UX — no new
  "combined item count" math.
- **Two buttons, not a pop-up (2026-10-06):** **Merge every time — all future recipes** writes a
  durable `source='merge'` [ingredient alias](./ingredient-handling.md#ingredient-aliases) (live
  for every future recipe; tagged "from a checklist merge" in Settings); **Merge for this shopping list
  only** writes a session-scoped
  `session_ingredient_merges` row instead; either way a toast offers **Undo** (`POST .../undo-merge`; see
  [UI/UX > No native dialogs](./ui-ux.md#no-native-dialogs--ask-and-report-inline-2026-10-06-chunk-67)). The old
  yes/no `confirm()` is gone. The rest of this bullet describes the same two outcomes
   (this week only, cascade-deleted with the session — see
  [Ingredient Aliases](./ingredient-handling.md#ingredient-aliases) for the table shape and how
  it slots into the resolution chain as the step after alias resolution).
- **Merge is pre-push only** — disabled once `session.status == "pushed"` (avoids leaving an
  un-cleanable stray duplicate on the real AnyList list). Not proactively hidden once pushed;
  surfaced the same reactive way the Push button's own "already pushed" case already is (a
  friendly message on the 409, not a pre-emptive status fetch just to hide the control).
- Have-it/add-to-list state on a merged-away row is preserved onto the surviving canonical row
  (strongest value wins: "no" beats "yes" beats "unknown" for have-it; any "add to list" wins) —
  merging never silently discards an in-progress decision.

### Review→Checklist merge — resolution of the 2026-09-24 handover (2026-09-30)

A standalone Review screen (`session-review.js`, between Plan and Checklist) used to be the
only place that triggered consolidation, showed the recipe breakdown, and offered an ad-hoc
session-only ingredient swap. An investigation written 2026-09-24
(`HANDOVER-review-checklist-merge.md`, since folded in here and deleted per its own stated
lifecycle) found it mostly redundant with Checklist and proposed merging it in, but flagged one
blocking question first: **how does an ad-hoc, not-yet-remembered swap survive Checklist
re-consolidating on every load**, when two existing call sites (pack-size save, Fix-3 merge)
already re-consolidate with no override list at all? Resolved as part of this merge (chunks
7.3–7.5): a new session-scoped override store (generalising the existing
`session_ingredient_merges` table Fix 3 already built, rather than a parallel mechanism) holds
every "this list only" edit — including the ad-hoc swap — and `session_consolidation.py` reads
it internally on every consolidate call, regardless of what triggered it. The three other
open items the handover raised: the step indicator collapses to `Plan → Checklist → Push`
(done, chunk 7.4); `session-review.js` is deleted outright, not kept dormant (done, chunk 7.4);
row crowding is addressed by the ingredient panel's own mockup gate (chunk 7.1) rather than a
separate pass.

### Recipe breakdown — "which recipe is this from" (moved here 2026-09-30, chunk 7.4)

Every regular and needs-review row's name becomes a tappable `▾`/`▴` toggle when
`item.recipe_breakdown` is non-empty (`checklist.js > rowNameParts()`), expanding to a small
list of "Recipe name — amount" rows, each linking to its recipe (`#/recipes/<id>`). Ported
verbatim from the now-deleted standalone Review screen (`session-review.js`), which was the
only place this ran before Checklist consolidated itself (chunk 7.3 makes `recipe_breakdown`
available on every checklist load, not just a one-off review pass). Full design — one row per
contributing recipe *slot*, never merged, ephemeral/recomputed every load — in [Scaling Logic
\> Which Recipe Is This Ingredient From](./scaling-and-consolidation.md#which-recipe-is-this-ingredient-from).

### "The usuals" — household recurring items

Raised 2026-09-05, **designed at the Phase 5 kickoff (2026-09-07)**: alongside the
recipe-driven checklist above, a pass over recurring non-recipe household items — laundry
powder, dishwashing liquid, and similar things bought periodically regardless of what's being
cooked. Was distinct from the now-retired [`staples`](./data-model.md#staples) feature in the
one way that mattered even before that removal: this has real cadence/memory
(`cadence_days`/`last_added_at`), which `staples` never did — see [Decision History > Staples —
usefulness assessment](./decision-history.md#staples--usefulness-assessment-raised-2026-09-27).

**Resolved design** (Decision Dialogue → option 2, day-based cadence, checklist group):
- **Own table** — [`usual_items`](./data-model.md#usual_items) (`name` / `notes` / `cadence_days` /
  `last_added_at`).
- **Day-based cadence.** Each item carries `cadence_days` ("buy roughly every N days"). It is
  *due* when `last_added_at IS NULL` or `last_added_at + cadence_days` has passed. Days rather
  than "every N sessions" because ad-hoc single-recipe sessions make a session an unreliable
  clock. `last_added_at` is stamped when the item is actually pushed to AnyList (Chunk 5.6),
  not merely offered.
- **Checklist group, not a separate screen.** Due usuals render as the final group on the
  existing checklist screen, each with a checkbox; ticked ones ride the same push as the
  recipe items. Non-due items don't appear.
- **Managed in Settings** (`settings-usuals.js`), same CRUD shape as product-units.
  Seeded empty — same "don't pre-guess" discipline as every other reference list.

Built in [Phase 5 Chunks 5.4 / 5.5 / 5.6](./build-status/phase-5-checklist-anylist.md#phase-5--checklist--anylist-integration).

---

## AnyList Push Logic

> **Rewritten 2026-10-06 (Chunk 6.7).** The authoritative, detailed description — the operation
> table, the decision matrix, verification semantics, per-item statuses, log format, a
> troubleshooting runbook and the test map — now lives in **[anylist-push.md](./anylist-push.md)**.
> This section is the summary; if the two ever disagree, anylist-push.md wins. The history of how
> the write mechanisms were found is in
> [build-status/anylist-fault-finding-spike.md](./build-status/anylist-fault-finding-spike.md).

**The contract of a push:** every row the user marked **Need it** (`add_to_list` or
`have_it = 'no'`), plus any ticked due **"usual"**, ends up **on the AnyList list, NOT crossed
off, exactly once, with the wanted quantity and note — and the push proves it by reading the list
back.** Anything that did not make it is reported **by name with a reason**; a push never fails
silently and never reports `confirmed` unless every line passed the read-back.

How (`services/checklist.py > push_to_anylist()` + `services/anylist_client.py`):
1. **Read the list fresh.** If that fails, nothing is changed (502).
2. **Match each wanted line to an AnyList item by name against that fresh read** — the id stored on
   the checklist row is only a hint and may be stale. An *active* (uncrossed) match is preferred
   over a crossed-off duplicate. A crossed-off item is **not** "on the list" (it is already
   bought): it does not pre-tick a row "Have it" and it is not counted as on the list.
3. **Decide per line** (one function, `_decide`, shared by the real connector and the in-memory
   fake): not on the list → **add**; active and identical → **leave alone** ("already active");
   active, bare-count quantity changed → `set-list-item-quantity`; crossed off → **un-cross**
   (`set-list-item-checked` `'n'`, then set the quantity if it changed — live-verified on TestList
   2026-10-06); anything else that must change (unit-bearing quantity or a changed note) →
   **replace** (remove + add under a new id, the only reliable write for those). The household's
   own note on an item is never overwritten by a push that has no note of its own.
4. **One operation per HTTP request**, then a **fresh read-back** of the whole list. Every line is
   checked: present, **uncrossed**, right quantity, right note/name where this push set them, and —
   for a replace — the old item gone. A read that merely lags is re-read before anything is
   re-sent; a line still wrong is re-sent (same new id, so a retry can never duplicate), at most
   `_MAX_RETRIES` times. If the old item of a replace will not go away it is crossed off instead
   so it is not an active duplicate. One failing line never aborts the batch; after three failed
   sends in a row the rest are marked "not sent" instead of waiting out a timeout per line.
5. **Result per line:** `added`, `updated`, `un-crossed`, `already-active` or `failed(reason)`,
   keyed by checklist row (`item:<id>` / `usual:<id>`), never by display name. `confirmed` is true
   only when no line failed. The AnyList ids that landed are written back onto the rows.
6. **Only a fully confirmed push marks the session `pushed`** (and stamps the usuals); a partial
   failure leaves it re-pushable *without* the "already pushed" prompt — the next push re-reads
   the list, leaves what landed alone and retries only what failed. A forced re-push of a fully
   pushed session is still allowed (`?force=true`).
7. **Recorded and visible:** one `shopping_history` row per push (`items_json` snapshot +
   `anylist_response_json` with `push_id`, the per-item results, timings and retries), one
   `push_id` on every log line, and the **Diagnostics** page (latest push + recent pushes with
   per-item detail — `GET /diagnostics/pushes`).

Name and quantity formatting for what is sent: the name is the display name
([Ingredient Handling](./ingredient-handling.md)), the quantity is `_anylist_quantity()` (the plain
"need" total — not the pack sentence), the note is `_anylist_note()` (pack breakdown plus the
checklist note, joined with " · ").

### Rename-proof decisions (Chunk 6.7)

A "Need it" tick lives on a row keyed by `ingredient_name`. When a row is renamed (an alias, a
merge, a substitute, or a Settings alias added between visits) consolidation deletes the old row
and creates a new one — which used to start as "unknown" and silently lose the tick (and, if the
new name matched something on AnyList, get pre-ticked "Have it" and never pushed). Consolidation
now carries the decision across (`session_consolidation._carry_state_across_renames`): the
strongest `have_it` wins, `add_to_list` is OR-ed, a survivor is never downgraded, and a row whose
ingredient truly disappeared is dropped as before.

### Real push progress UI (2026-09-23, revised 2026-10-06)

The frontend sends a `progress_token` on `POST /checklist/{id}/push` and polls
`GET /checklist/push/progress/{token}` every 500 ms. The response is `{stage, steps}`: `stage` is
the coarse phase of the whole push (`reading` → `sending` → `confirming` → `done` /
`needs-attention`), and `steps` are one per wanted line, addressed by **row key** with the display
name as `label` (2026-10-06: they used to be matched by display name, which the server
title-cases/pluralises, so per-item progress never lined up). `anylist_client` reports through
optional `on_item(ref, status)` / `on_stage(stage)` callbacks and imports nothing from
`progress_tracker`; `checklist.push_to_anylist()` wires them up. A line is `done` once its write
was *sent*; it only counts as landed after the read-back, which the **Confirming** stage covers —
any line the read-back rejects is flipped to `failed` with its reason.

---

## Shopping List Store Layout

**Status: in scope, UI build deferred out of Phase 6** (folded in from the Shop Layout
Reorganisation addendum). Originally listed as a deferred item ("Shop layout reorganisation" —
Phase 6 or post-MVP) and, separately, "Multi-shop support" was Post-MVP/descoped. Both are now
active scope — a fixed single-store layout doesn't match the actual use case, so the descope was
reversed. Schema lands in Phase 1 (see [Data Model](./data-model.md#data-model)) and is already
built — `stores`/`store_sections`/`product_sections` exist, and `services/product_sections.py`
already tags AI-suggested sections in the background on every recipe save. **The setup and
rendering UI was originally slated for Phase 6, but was deliberately pulled back out at the
Phase 6 kickoff (2026-09-19/20)** — the maintainer judged there's more nuance to it (store
setup UX, section-correction UX, store-sorted rendering) than was worth deciding in the same
pass as the rest of Phase 6's polish work. It now has no reserved phase; see
[Deferred Decisions](./deferred-decisions.md#deferred-decisions). Nothing about the schema or the
background tagging changes — only the still-missing UI's timing.

### Use case
The shopping list should render in a walking order that matches whichever store the trip is
actually happening at — not one fixed layout, and not alphabetical or list-order. Each store
has its own section layout, defined once and reused on every future trip to that store.

### Scope decisions (confirmed)
- **Multi-store**: in scope. Each store is a distinct entity with its own section order.
- **Ordering data source**: no learning/inference from behaviour. The user sets a fixed section
  order per store, once, and edits it manually if a store's layout changes.
- **AnyList relationship**: AnyList stays untouched. This is a separate, app-native sorted
  view/printout generated from the same underlying list data — not a write-back into AnyList's
  own categories/sections. This keeps AnyList as the single source of truth for list state and
  avoids depending on what AnyList's API does or doesn't expose for section control.
- **Section assignment**: mixed — AI suggests a section for each item at capture time, user
  confirms/corrects (see the Phase 3 extraction prompt extension above).

### Key simplification
A product's *section* (e.g. "dairy", "produce", "frozen") is a property of the product, assigned
once, store-independent. A store's *section order* (which section comes first when walking that
store) is a property of the store, assigned once, product-independent. Sorting a list for a given
store is then just: group items by section → order groups by that store's section order → render.
This avoids a per-product-per-store mapping (which would require re-tagging every product for
every store) in favour of two small, independent tables that combine at render time — see the
`stores` / `store_sections` / `product_sections` tables in the Data Model.

### Store setup flow (new, small UI — future phase, not yet scheduled)
One-time per store: user adds a store by name, then drags the section vocabulary into their
preferred walking order. Editable later if a store rearranges. No per-product interaction here —
this screen only touches `store_sections`.

### List rendering flow (future phase, not yet scheduled)
1. User selects a store for the current shopping trip (defaults to last-used store).
2. App pulls the current checklist (from the existing planning engine output — unchanged).
3. Items are grouped by `section_name` via `product_sections`.
4. Groups are ordered using that store's `store_sections.sort_order`.
5. Any item with no section yet (never tagged) falls into an "other" group at the end, surfaced
   for tagging next time it comes up in capture.
6. Rendered as a sorted view/printout in-app. The AnyList list itself is not modified.

### Cost/complexity profile
Low. Two new small tables, one new one-time setup screen, one additional field in an extraction
prompt that's already being called per recipe, and a grouping/sort operation at render time. No
new AI calls beyond the existing per-recipe extraction (section suggestion piggybacks on it).

### Open items
- Store deletion/merge is not designed — low priority, add if it comes up (see
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions)).
- Never-tagged items fall into an "other" group at render time — fine for MVP, not revisited.

---

