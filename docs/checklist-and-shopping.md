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
- **"Always treat these as the same ingredient?"** (yes/no, a plain `confirm()`) — yes writes a
  durable `source='user'` [ingredient alias](./ingredient-handling.md#ingredient-aliases) (live
  for every future recipe); no writes a session-scoped
  `session_ingredient_merges` row instead (this week only, cascade-deleted with the session — see
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

Built in [Phase 5 Chunk 5.6](./build-status/phase-5-checklist-anylist.md#phase-5--checklist--anylist-integration) —
`services/checklist.py > push_to_anylist()`.

On push:
1. Collect `session_checklist_items` where `add_to_list = True` **OR** `have_it = 'no'`
   (the checklist tap sets `add_to_list` when you tap to "need it", so in practice these
   coincide), plus any ticked **due "usuals"**.
   - If `already_on_anylist = True` AND `anylist_item_id` is set, and the computed quantity is a
     **bare AnyList-native count** (no unit, e.g. `"3"`): **update the existing item in place**
     (`set-list-item-quantity`) — proven reliable for this shape, both live and at realistic
     scale.
   - If the same is true but the quantity has a **unit** (`"500 g"`, `"1.5 L"`, or a
     non-numeric coarse-ingredient string) — the common case, since most ingredients here have
     a unit: **replace the item** instead — delete it and add a fresh one under a new
     identifier. **Fixed 2026-09-20** (fault-finding spike, full trail in
     [docs/build-status/anylist-fault-finding-spike.md](./build-status/anylist-fault-finding-spike.md)'s
     2026-09-19/20 addenda): `set-list-item-quantity` was root-caused as a genuine AnyList
     server-side limitation for anything but a bare number or the literal tokens `"kg"`/`"lb"`
     — confirmed via an exhaustive live investigation and, decisively, by running the real
     unmodified reference `anylist` npm package against the identical case (it fails
     identically, ruling out a bug in this app's own implementation). ADD is 100% reliable for
     any quantity shape, so replacing is the fix. **Checked-state and the note both carry
     across the replace explicitly** — checked from the item's state just before the push,
     note from the freshly computed value (an improvement over the bare-count path below, which
     still never syncs notes). Live-confirmed (wire-level and phone-checked) that quantity,
     note, and checked all survive intact, and re-validated at realistic scale (8 simulated
     weekly cycles, ~24 items, zero discrepancies).
   - Otherwise (genuinely new): add as a new item (client-generated UUID identifier, per the
     spike). **Fixed 2026-09-19** (fault-finding spike mechanism #3): `push_to_anylist()` writes
     the new identifier straight back onto the checklist row (`already_on_anylist = True`,
     `anylist_item_id = <new id>`) as soon as the add — or a replace, which is also a real add
     under the hood — is confirmed. Before this fix, that write-back never happened for a fresh
     add, so a re-push of the same session before its next `load_checklist()` call — exactly
     what the checklist screen's own "already pushed, push again?" retry does — had no way to
     know the ingredient was already there and added it a second time. Reproduces every time an
     ingredient is new on the first push, confirmed live; not an edge case.
2. Item name: `ingredient_name` `.title()`-cased; a usual uses its own name.
3. **Item quantity and note (reworked at Chunk 5.7 live-verification, 2026-09-12, per the
   maintainer's request).** `services/checklist.py > _anylist_quantity()` sends the plain
   "need" total (`total_quantity`/`total_unit`) as AnyList's quantity — the amount to
   actually buy, not a sentence describing how it's packed — falling back to the pack-count
   string only when there's no numeric total at all (a coarse ingredient). `_anylist_note()`
   sends the pack breakdown (e.g. "2 × 500g pack") *plus* whatever the checklist's own `note`
   already carries (an overage hint, "to taste", a needs_review breakdown, an alias
   conversion), combined with " · ". Example: `passata — 2 × 750 g jars · need ~1.05 kg` on
   the app's own checklist becomes AnyList quantity `"1050 g"`, note
   `"2 × 750g jars · 450 g spare"`.
   **Known limitation, still standing for bare-count items only:** a note only lands correctly
   on an item's *first* push via the simple update path. Updating an existing AnyList item's
   note (`set-list-item-details`) was tried and reverted — it was found (Chunk 5.7) to reliably
   break that same item's quantity on every future update (a 2026-09-19 controlled A/B found no
   differential failure rate on this specific claim, casting some doubt, but it hasn't been
   re-verified enough to act on). **This limitation no longer applies to unit-bearing items** —
   those go through the replace path above, which syncs the note as a normal side effect of a
   real add. Only a bare-count item's note stays frozen at whatever it was on first add.
4. **One operation per HTTP request — never batched, even across different items**
   (`services/anylist_client.py > add_or_increment_items()`, reworked at the same
   Chunk 5.7 pass). AnyList's server was found to silently drop an operation whenever a
   single request touched more than one distinct list item — confirmed reproducible, and
   matching the reference `codetheweb/anylist` client's own behaviour (it never batches
   either). A push of N items is therefore N sequential requests, each individually
   **re-fetch + diff**-confirmed together at the end (an HTTP 200 alone is not proof — spike
   finding #3). `confirmed` / `discrepancies` are recorded and returned.
   **Retry added 2026-09-19** (fault-finding spike mechanism #1,
   [docs/build-status/anylist-fault-finding-spike.md](./build-status/anylist-fault-finding-spike.md)):
   a fraction of `set-list-item-quantity`/`add-shopping-list-item` calls were found to
   intermittently persist nothing at all — a real AnyList-side failure, HTTP 200 either way,
   with no identified trigger on our side. Any item still wrong after the initial confirm-diff
   now gets its exact op resent up to `_MAX_RETRIES` (2) more times, each with its own fresh
   confirm, before it's allowed to become a real discrepancy — see the spike doc's 2026-09-19
   reliability-investigation addendum for what this looked like at realistic scale. `retried`
   (names that needed at least one retry) is recorded on the result alongside
   `confirmed`/`discrepancies` so real-world frequency stays visible without another spike.
5. On completion: set `planning_sessions.status = 'pushed'` + `pushed_at`, stamp
   `usual_items.last_added_at` for any pushed usuals, and write one `shopping_history` row
   (`items_json` snapshot + `anylist_response_json` = the raw response summary +
   discrepancies). The session is marked `pushed` **even if the diff wasn't fully confirmed**
   — otherwise a retry would re-add the items that *did* land as duplicates. A re-push of an
   already-`pushed` session is refused (`409 SESSION_ALREADY_PUSHED`) unless `?force=true`.

### Real push progress UI (2026-09-23)

Like capture (see [Recipe Capture > Real capture progress
UI](./recipe-capture.md#real-capture-progress-ui-2026-09-23)), a push is still one blocking
HTTP request from the frontend's view even though `add_or_increment_items()` internally does
one real HTTP call per item. Chunk 6.3b originally covered that with a client-side-only timer
cycling through the known item-name list. That's replaced with genuine per-item progress: the
frontend sends a `progress_token` on `POST /checklist/{id}/push`;
`anylist_client.add_or_increment_items()` takes an optional `on_item(name, status)` callback
(no `progress_tracker` import in that file itself, keeping the external-integration class's
small stable interface — `checklist.py`'s own `push_to_anylist()` wires the callback to
`progress_tracker`), called `"active"` before an item's op(s) and `"done"` right after they
succeed. `static/js/checklist-push.js` polls `GET /checklist/push/progress/{token}` every
500ms and renders a real per-item step list. Deliberately no `"failed"` callback from
`anylist_client.py` itself — if the whole push dies mid-item, that item simply never gets its
`"done"` call, and the frontend does one final progress fetch on the request's rejection to
find whichever item is still `"active"` and mark that specific one as the failure, rather than
only a generic "push failed" alert.

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

