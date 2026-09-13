# Scaling Logic & Consolidation

## Scaling Logic

When a recipe is scaled from its base servings to requested servings.

> **Where rounding lives — resolved 2026-09-06 at Phase 4 kickoff (grilling with the
> maintainer; supersedes the earlier "round inside `scaling.py`" wording).** `scaling.py`
> does **one thing: multiply**. No rounding, no unit conversion, no pack-size logic. It takes
> `(quantity, unit, factor)` and returns `(quantity × factor, unit)` with the unit preserved
> verbatim; `"pinch"` / `"to taste"` style units pass straight through untouched
> (`scaled=False`). **Every** rounding and unit-normalisation decision happens *once*,
> downstream, in `consolidation.py` + `purchase_units.py` (Chunk 4.6) — after quantities from
> all recipes in the session have been summed. Rounding per-recipe and then summing would
> round twice and let drift compound across a session. Rationale in full:
> [Decision Dialogue > Scaling: rounding location & rules](./decision-history.md#scaling-rounding-location--rules-phase-4-kickoff).

### Scaling — the `scaling.py` half (Chunk 4.3)
- `scaling_factor(base_servings, target_servings)` → `target / base` (raises on non-positive base).
- `scale_quantity(quantity, unit, factor)` → multiply; unit kept exactly as given (so `kg`
  stays `kg`, free-text `"can"` stays `"can"`); `NO_SCALE_UNITS` (`pinch`, `to taste`,
  `taste`, `splash`, `drizzle`, `dash` — extensible) pass through with `scaled=False`.
- **Default target servings = 4** — the household is two adults, each taking a serving as
  next-day lunch (2 people × 2 meals). Used as the pre-fill when a recipe is added to a
  session (Chunk 4.4), always overridable per recipe. It's a constant
  (`DEFAULT_TARGET_SERVINGS`), not yet a Settings field — see
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions).
- Scaling is **rare** in practice (most recipes are `base_servings=4`, target 4, factor 1.0).

### Rounding & unit rules — the `consolidation.py` half (Chunk 4.6)
Applied to the **summed** quantity for each consolidated ingredient, in this order:

1. **Unit normalisation (Australian conversions — confirmed 2026-09-06).** Volume↔volume
   only; there is no density data so weight↔volume is never converted.
   - `tsp` → 5 ml, **`tbsp` → 20 ml** (the Australian tablespoon, *not* 15), `cup` → 250 ml
   - `kg` → 1000 g, `L` → 1000 ml
   After this, quantities for one ingredient are either all-mass (g) or all-volume (ml), or
   they are irreconcilable (see 4).
2. **Sum** the normalised quantities across the session's recipes (a substituted ingredient
   is already resolved to its target name before this — see
   [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution)).
3. **Round the sum** — always **upward** to a clean step, never to nearest, so a shopping
   quantity is tidy but is **never short** ("tolerances, not round-to-x, remove admin"):
   - discrete / countable (no unit, or a free-text unit like `can`/`bunch`/`clove`) →
     **ceil to a whole number** (`1.5 eggs` → `2`; applies when scaling *down* too;
     `½ onion` → `1`)
   - g / ml, value ≥ 100 → **ceil to nearest 25**
   - g / ml, value < 100 → **ceil to nearest 5**
   - `tbsp` / `tsp` → ceil to nearest 0.5 — applies whenever every volume contribution for
     an ingredient is a spoon/cup measure and **none** is a literal `ml`/`L` (a literal
     ml/L contribution signals a genuine liquid, where normal ml/L rounding is correct
     instead). **Fixed 2026-09-10** (hand-testing: a bulky/leafy ingredient measured only in
     spoons, e.g. "2 tbsp baby spinach", was showing as a nonsensical ml figure like
     "175 ml baby spinach") — this bullet had been vestigial since Phase 3.9 (the code
     unconditionally normalised every tbsp/tsp to ml before this branch could ever run,
     per the M-review note that used to sit here); `consolidation.py` now actually reaches
     it, choosing the largest spoon/cup unit that was used across the session's recipes.
   - `cup` → 2-decimal trim, **no** clean-rounding (a scaled cup value is almost always < 1,
     where a "nearest 5" rule would destroy it) — same "no literal ml/L present" condition
     as the tbsp/tsp case above; a cup contribution takes priority over tbsp/tsp when both
     appear for the same ingredient (e.g. `1 cup + 2 tbsp` baby spinach → shown in cups).
   - `NO_SCALE_UNITS` ("to taste") → shown on the list **with no number** (e.g.
     `saffron — to taste`)
4. **Irreconcilable** — mass + volume for the same ingredient (e.g. `100 g cream` +
   `200 ml cream`), or a count + a unit (`3 onions` + `200 g onions`). Not merged: the line
   is **flagged** and both parts are shown (`cream — 100 g + 200 ml (needs review)`). The
   review UI for resolving these is Phase 5; Phase 4 only flags it on the API response.
5. **kg / L for display** — after summing in g/ml, a total ≥ 1000 is shown back in kg/L
   (`1030 g` → `1.03 kg`).

### Free-text units (`can`, `bunch`, `clove`, `sprig`, …) — 2026-09-06
Manual entry allows any unit string. Anything not in {`g`,`kg`,`ml`,`L`,`tsp`,`tbsp`,`cup`}
and not in `NO_SCALE_UNITS` is treated as **discrete** — scaled, then ceil-to-whole
("2 cloves" ×1.5 → 3). This scaling behaviour is unchanged and still the pragmatic default,
not a confident one — what real use actually surfaced as broken wasn't this rule but
**reconciliation** ("2 clove" and "3 cloves" landing in different, unmergeable buckets),
fixed by [Ingredient Unit Handling](./ingredient-handling.md#ingredient-unit-handling)'s dynamic unit-spelling
canonicalisation (Layer A) — that section is also where the "some ingredients shouldn't be
measured this precisely at all" case (Layer D, `coarse_ingredients`) lives.

### Consolidation across recipes
Each ingredient's effective name is its `recipe_ingredients.resolved_ingredient` if set,
else its `name` — so a recipe whose "bulgarian feta" the user resolved to "regular feta"
consolidates onto the same line as another recipe's "regular feta". **The pure
`consolidation.consolidate()` does no substitution *resolution*** (Phase 3.9 M4 — see
[AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39)):
it is handed already-resolved names as plain data. A **session-only** planning swap (the
Chunk 4.7 ad-hoc swap) is applied one layer up, in the `consolidate_session()` orchestrator,
which computes each ingredient's effective name (resolved_ingredient → session override)
before feeding `consolidate()`. The per-ingredient sum → normalise → round → flag pipeline
is the "Rounding & unit rules" list above.

**Substitution quantity/unit transform (Phase 3.9 M8).** A substitution may also change the
*amount and unit*, not just the name — "2 whole corn cobs" → "2 cans of corn", "500 g fresh
spinach" → "250 g frozen". This resolves in the same `consolidate_session()` /
`_scaled_lines()` layer, never in the pure `consolidate()`. Per ingredient: if
`resolved_ingredient` is set **and** `resolved_quantity` is not NULL, `scaling.py` is fed
`(resolved_quantity, resolved_unit)` in place of `(quantity, unit)` — so the swap's amount
scales with servings like any other. A session-only override may carry the equivalence-pair
ratio instead (it spans every recipe using that name); it's applied to the *scaled* quantity,
and only when the override's `original_unit` matches the line's unit (else that line falls
back to name-only). The transform is skipped when the effective source unit is a
`NO_SCALE_UNITS` ("to taste") value. `consolidate()` still just receives a finished line
(`6 can canned corn`) and groups it — a free-text unit like `can` buckets as a discrete
count and ceils to whole, exactly as today. No cross-unit conversion table exists; the
number the user entered is the equivalence. A consolidated line always carries the **required quantity** (the rounded sum);
purchase-unit resolution below may *add* a pack breakdown next to it but never replaces it —
so a no-pack-size ingredient still shows an amount (`passata — 1.05 kg`), and a pack-size
ingredient shows both (`passata — 2 × 750 g jars · need ~1.05 kg`).

### Purchase unit resolution (design confirmed 2026-09-05, PARTIALLY DEFERRED — build at Phase 4)
When an item exists in `product_units`, calculate how many purchase units are needed to cover
the required quantity, and display as e.g. "2 × 500g packs" or "1 dozen eggs".

**Multiple pack sizes per ingredient are the normal case, not an edge case** — confirmed
2026-09-05 after checking real household usage patterns. An ingredient like yoghurt commonly
comes in more than one pack size (e.g. 500g and 1kg tubs); resolving purely against a single
seeded size and rounding up (2 × 500g to cover 750g) gives the wrong answer when a 1kg tub
would do. This is what `product_units` moving to one-row-per-pack-size in Phase 4 (see the
[`product_units`](./data-model.md#product_units) schema note) is for. The resolution algorithm, to build when
Phase 4 starts — documented now so the shape doesn't need re-deriving then:

1. Look up all `product_units` rows for the ingredient (there may be zero, one, or several).
2. **Zero rows:** no pack breakdown — the consolidated line is just the rounded required
   quantity (`passata — 1.05 kg`).
3. **One row:** round the required quantity **up** to the nearest whole multiple of that pack.
4. **Several rows:** choose the combination of available pack sizes (repeats allowed) whose
   total meets or exceeds the required quantity, minimizing total overage first and pack count
   second as a tiebreaker (e.g. need 750g, options {500g, 1kg} → one 1kg pack, not two 500g).
   The search space is tiny (a handful of pack sizes, realistically no more than 2-3 packs
   deep to reach any plausible household quantity) — brute-force over small combinations is
   fine, no general knapsack/DP solver needed.
5. This generalises rather than replaces the existing "countable item purchase unit thresholds"
   deferred item below (eggs: need 6, buy a dozen?) — once an ingredient like eggs has more
   than one pack size seeded (e.g. half-dozen and dozen), step 4 already covers it. No separate
   special case for countable vs weight/volume items.

**Display (confirmed 2026-09-06 grilling):**
- The consolidated line **always shows the required quantity**; a pack breakdown is shown
  *in addition*, never instead: `passata — 2 × 750 g jars · need ~1.05 kg`. This is the
  resolution to the maintainer's worry about a bare `passata` line hiding "how much".
- **Overage** (spare amount beyond what the recipes need) is shown **only when it exceeds
  roughly half of one pack of the size used** — `need 750 g → 1 × 1 kg tub` (250 g over, a
  quarter-pack) says nothing; `need 550 g → 2 × 500 g packs` (450 g over, ~a pack) shows it.

**Multi-pack, seeded from day one (2026-09-06 — deliberate small departure from the
"don't pre-enumerate pack sizes" note below).** The maintainer wants the several-rows path
exercised in real use immediately rather than shipping dormant. `seed_data.py` seeds a
handful of genuine multi-pack items — **eggs (½ dozen + dozen), milk (1 L + 2 L), yoghurt
(500 g + 1 kg)** — and the algorithm + Settings multi-row display get real test coverage in
Phase 4, not "later". Every *other* ingredient still stays single-pack; a second option is
added via Settings opportunistically, as originally intended:

Most ingredients stay single-pack, as seeded. A second/third option gets added — via Settings
(see [Chunk 2.5](./build-status/phase-2-recipe-library.md#phase-2--recipe-library)) — opportunistically, only for specific ingredients
where it's actually been noticed to matter. Chunk 4.5 re-checks that the Settings
`product_units` view still displays sensibly now an ingredient can have more than one row.

**Re-running consolidation is a merge, not a rebuild (2026-09-06).**
`POST /sessions/{id}/consolidate` upserts `session_checklist_items` keyed by
`ingredient_name`: quantities / pack breakdowns / `is_staple` / irreconcilable flags are
recomputed, new lines are added and lines no longer needed are removed, but per-item
**state is preserved** for lines that persist — `have_it`, `add_to_list`, and (Phase 5)
`already_on_anylist` / `anylist_item_id`. So adding a recipe and re-consolidating never
discards checklist progress.

**A manually-resolved `needs_review` conflict is also preserved, as long as the underlying
conflict is still there (2026-09-10 hand-testing fix — "doesn't remember amounts under
review").** Without this, every re-consolidate (adding another recipe, changing servings,
simply re-opening the review screen) recomputed a `needs_review` line from scratch and
silently threw away a total the user had just manually picked via
`services/checklist.py > resolve_item()`. `session_checklist_items.review_resolved_by_user`
tracks this: `resolve_item()` sets it when the user commits a manual total; the
`consolidate_session()` upsert skips recomputing `total_quantity`/`total_unit`/`needs_review`
for a line where it's set **and** the ingredient still conflicts, leaving the user's choice
alone. Once the conflict is actually gone (a substitution or alias resolved it, say), the
flag is cleared and the line falls through to a normal recompute — a stale manual pick from
an earlier, unrelated conflict is never silently reused for a fresh one.

---

## Which Recipe Is This Ingredient From

**Status: in scope, built 2026-09-11.** Raised as a "hey, what did we need this for?" check
on the ingredient-review screen, before the checklist and pushing to AnyList: tap a
consolidated line's name to expand it into a per-recipe breakdown. No record of this ever
being designed or built before it was raised — checked CLAUDE.md, the full git history, and
session memory first, rather than assume it existed.

### Design (confirmed 2026-09-11)

- **Ephemeral, review-screen-only — nothing persisted.** Computed fresh on every
  `POST /sessions/{id}/consolidate`, the same call that already runs the whole pipeline; not
  written to `session_checklist_items` or anywhere else. It doesn't need to survive to the
  checklist screen or into `shopping_history` — the ingredient-review step is the one place
  this check makes sense, right before the household commits to "do I have this?" and pushes.
- **One row per contributing recipe *slot*, never merged — even two slots of the same
  recipe.** If a recipe is slotted into a session twice (e.g. meal-prepped for two different
  nights, at different serving sizes), the breakdown shows both occurrences separately rather
  than a combined total, since the two occurrences can genuinely need different amounts.
  Disambiguated by day when one is set (`"Bolognese (Mon)"`, `"Bolognese (Thu)"`); two
  same-recipe slots with no day set show as identical, indistinguishable labels — accepted,
  not solved further (a rare case, and the underlying `recipe_id` still links each one to the
  right recipe page even if the labels read the same).
- **Shows each recipe's own final, already-scaled amount** — i.e. exactly the `IngredientLine`
  that recipe contributed to consolidation, post-substitution and post-alias resolution (so a
  recipe that said "canola oil" shows under "vegetable oil"'s breakdown labelled with its own
  recipe name, not "canola oil"). This is deliberately **not** re-derived from the recipe's
  raw, unscaled ingredient data — it's whatever this specific session actually asked for.
  Amounts are shown in each line's own unit, not converted to the consolidated total's
  display unit, so if two recipes contributed in different-but-mergeable units (say `g` and
  `kg`) the breakdown reads naturally per-recipe even though the numbers don't visually
  re-sum without doing that conversion yourself — the "why do I need this much" answer is in
  each recipe's own terms, not a second arithmetic exercise.
- **Each row links to the recipe** (`#/recipes/<id>`) — free to add since `recipe_id` is
  already on hand from the session's recipe slots.
- **Implementation stays out of the pure `consolidation.consolidate()`'s reasoning** — same
  discipline as the Ingredient Aliases conversion notes: `IngredientLine` carries an opaque
  `recipe_id`/`recipe_label` (a ready-made display string built by
  `services/session_consolidation.py > _recipe_label()`, which is the only place that knows
  about slots/days), and `_resolve_group()` just collects one `RecipeContribution` per line
  into `ConsolidatedItem.recipe_breakdown` — it has no idea what a "recipe" is, same as it has
  no idea what an "alias" is.
- **Threading it to the API without changing `consolidate_session()`'s signature** — that
  function is called from many places (the checklist load/push path, most of the test suite)
  that have no use for this and shouldn't need updating. `consolidate_session()` stays exactly
  as it was, now a thin wrapper around a shared internal `_consolidate_session_impl()`; a new
  `consolidate_session_with_breakdown()` (used only by the one router endpoint that needs it)
  reads the breakdown map off the SAME already-computed `ConsolidatedItem`s the upsert loop
  iterates, so there's no second consolidation pass. Wire format:
  `ChecklistItemRead.recipe_breakdown` (`list[RecipeContribution]`, always `[]` on any other
  endpoint that returns a `ChecklistItemRead` — populated only by the consolidate endpoint via
  `model_copy()` after validation, since it isn't a real `session_checklist_items` column).
- **UI**: `session-review.js` — the ingredient name becomes a tappable toggle (▾/▴) only when
  a breakdown actually exists; expands to a small list of "Recipe name — amount" rows, each
  linking to its recipe. Collapsed by default. No change to the checklist screen
  (`checklist.js`) — this is deliberately review-screen-only, per the design above.

---

