# Checklist, AnyList Push & Shopping List Layout

## Checklist Screen Logic

At checklist screen load:
1. Fetch current AnyList items (names + quantities)
2. For each consolidated ingredient in `session_checklist_items`:
   a. Check if it appears in current AnyList list (fuzzy name match — normalised lowercase,
      strip plurals if needed)
   b. If found: set `already_on_anylist = True`, `have_it = 'yes'` by default
   c. Check if it is in `staples` table: set `is_staple = True`
3. Present checklist to user:
   - Items already on AnyList: pre-ticked, shown in a distinct style (user can untick)
   - Staples (only if used in this session's recipes): shown with a checkbox
   - All other items: unchecked by default
4. User taps each item: cycles through have_it states: unknown → yes → no → (partial if
   applicable)
5. Items marked 'no' or where `add_to_list` is True get pushed to AnyList

### "The usuals" — household recurring items

Raised 2026-09-05, **designed at the Phase 5 kickoff (2026-09-07)**: alongside the
recipe-driven checklist above, a pass over recurring non-recipe household items — laundry
powder, dishwashing liquid, and similar things bought periodically regardless of what's being
cooked. Distinct from [`staples`](./data-model.md#staples) — staples are recipe ingredients assumed on-hand,
surfaced only when a recipe in the session needs them; "the usuals" have no recipe link at
all and are offered on their own schedule.

**Resolved design** (Decision Dialogue → option 2, day-based cadence, checklist group):
- **Own table** — [`usual_items`](./data-model.md#usual_items) (`name` / `notes` / `cadence_days` /
  `last_added_at`), not a flag on `staples`.
- **Day-based cadence.** Each item carries `cadence_days` ("buy roughly every N days"). It is
  *due* when `last_added_at IS NULL` or `last_added_at + cadence_days` has passed. Days rather
  than "every N sessions" because ad-hoc single-recipe sessions make a session an unreliable
  clock. `last_added_at` is stamped when the item is actually pushed to AnyList (Chunk 5.6),
  not merely offered.
- **Checklist group, not a separate screen.** Due usuals render as the final group on the
  existing checklist screen, each with a checkbox; ticked ones ride the same push as the
  recipe items. Non-due items don't appear.
- **Managed in Settings** (`settings-usuals.js`), same CRUD shape as staples/product-units.
  Seeded empty — no pre-guessing, same call as the [Staples Starter List](./data-model.md#staples-starter-list).

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

