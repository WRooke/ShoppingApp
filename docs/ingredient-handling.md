# Ingredient Handling — Normalisation, Substitution, Aliases & Units

## Ingredient Normalisation

Ingredient names must be consistent across recipes for consolidation to work. Rules:
- Store all names in lowercase
- Strip leading/trailing whitespace
- Canonical forms: "beef mince" not "minced beef", "spring onion" not "green onion"
- On first capture, names are stored as Claude returns them (after lowercasing)
- The user can edit names in the recipe editing UI
- **Do not implement automatic synonym matching in early phases** — the user reviews and
  confirms all extractions, which provides sufficient normalisation for now. Flag for future.

---

## Ingredient Substitution

**Status: in scope. Design = the MERGE of the Phase 4 approach and the addendum's
capture-time flagging, confirmed 2026-09-06. Built in Phase 3.9 chunk M4.** The full,
authoritative spec is
[AI Provider Migration > Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec)
and the merge table just above it. This section is now a summary + the history.

Distinct from [Ingredient Normalisation](#ingredient-normalisation) above: normalisation
recognises two names as *the same thing* ("green onion" = "spring onion"). Substitution
treats two *different* products as interchangeable for shopping, because one is obscure or
hard to find — e.g. "bulgarian feta" → "regular feta".

### Summary of the merged design

- **Proposed** by a dedicated Gemini call at capture time (per recipe), *and* editable later
  in the recipe editor, *and* swappable session-only during planning.
- **Stored** on the ingredient record: `recipe_ingredients.resolved_ingredient` (nullable —
  the swap this recipe uses) + `substitution_note`, and (Phase 3.9 M8) optional
  `resolved_quantity` / `resolved_unit` when the swap also changes the amount/unit ("2 corn
  cobs" → "2 cans"). `name` stays the original. Clearing `resolved_ingredient` clears all of
  it and reverts.
- **Confirmed per recipe, always.** No silent auto-apply, no `is_default`.
- **Remembered** in [`remembered_substitutions`](./data-model.md#remembered_substitutions) *only* as a
  quick-pick accelerator — it pre-fills / top-ranks the suggestion in the per-recipe confirm
  UI under a "from your saved swaps" label; the user still confirms. The AI flagging call is
  never told about past choices.
- **Consolidation** reads `resolved_ingredient` (fallback `name`) as plain data — no
  substitution logic in the pure `consolidate()`. A session-only planning swap resolves in
  the `consolidate_session()` orchestrator.
- **1:many** ("buttermilk" → "milk + lemon juice") is a single freetext string for now — see
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions). Distinct from the M8 quantity/unit transform,
  which is one substitute at a different amount.
- **Quantity/unit transform (M8)** — recipe-level absolute (`resolved_quantity` /
  `resolved_unit`, scaled with servings); library-level equivalence pair that pre-fills it;
  session override carries the pair too. Resolved in `consolidate_session()`, never in pure
  `consolidate()`. No conversion table — the entered ratio is the equivalence. Full spec in
  [AI Provider Migration > Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec).

> **Note (added during the 2026-09-12 CLAUDE.md split):** the superseded 2026-09-05 and
> 2026-09-06(a) designs for this feature — kept "for the record" in the original document —
> now live in [Decision Dialogues & Historical Record](./decision-history.md#history-superseded-designs-kept-for-the-record).

### Two situations, not one
- **Genuinely one-off** — "I'm out of basil this week, using oregano instead." Applies to this
  session's shopping list only. Never remembered, never affects the recipe or any future session.
- **Worth remembering** — once a substitute is confirmed to work, the user shouldn't have to
  re-confirm it every time that ingredient comes up in a future planning session.

### Scope decisions (confirmed 2026-09-06)
- **Not the same as recipe editing.** If a recipe's ingredient text is simply wrong (a typo, a
  bad AI extraction), that's fixed via the existing recipe editor
  ([Chunk 2.4](./build-status/phase-2-recipe-library.md#phase-2--recipe-library), already built) — a correction, not a substitution.
  Substitution is for ingredients that are correctly captured but undesirable to actually buy.
- **No proactive tagging UI.** A rule is never created speculatively — same reasoning already
  applied to [Staples](./data-model.md#staples-starter-list) and the [`product_units`](./data-model.md#product_units)
  multi-pack-size note: don't pre-guess, wait for a real gap to show up in use. The *only* way an
  `ingredient_substitutions` row gets created is reactively, from an actual ad-hoc swap during
  planning (see below). There is no standalone "tag this ingredient as substitutable" screen.
- **Rules apply by ingredient name, not by recipe.** A rule for "bulgarian feta" applies to
  every recipe using that name, not only the recipe it was first created from. This is what
  makes a rule better than editing recipes individually once the same obscure ingredient turns
  up in more than one recipe — handled for free, no extra design needed.
- **One ingredient can have more than one known substitute**, e.g. "bulgarian feta" → both
  "regular feta" and "goat cheese" might be acceptable. Only one is the default (auto-applied);
  the rest are offered as quick-pick alternatives rather than retyped from scratch each time.
- **No repeated confirmation.** The core decision everything else follows from: a remembered
  substitution auto-applies silently at consolidation time, every time, with no "are you sure?"
  interruption. The cost of a substitution the user no longer wants is paid for by reversibility
  (below), not by asking up front every session.
- **Easily reversible, by construction.** A substitution is a separate record layered on top of
  a recipe, not an edit to the recipe itself — switching back to the original ingredient is
  disabling or deleting the rule in Settings. The recipe's own stored data is never touched, so
  there's nothing to retype from memory.
- **No recipe-level opt-out/kill switch.** Considered and dropped: once nothing interrupts the
  user uninvited, there's nothing left for a kill switch to protect against.

### Where this lives in the app (Phase 4)
- **Creation.** During planning session ingredient review — exact screen/placement is a Phase 4
  kickoff detail, but conceptually this happens after recipes are added to a session and before
  the consolidated list is finalised. The user can swap any ingredient for another, freely,
  whether or not a rule already exists for it. After a swap, the app asks *"Remember this
  substitution?"*:
  - **Yes** — creates or updates an `ingredient_substitutions` row. If this is the first
    substitute recorded for that ingredient, it becomes the default. If substitutes already
    exist for that ingredient, the new one is added as a non-default option unless explicitly
    marked as the new default.
  - **No** — applies to this session's shopping list only; nothing is written to the database.
  - If known substitutes already exist for the ingredient being swapped, they're offered as
    quick-pick options rather than requiring the user to retype a previously-used substitute.
- **Application.** Resolved during Phase 4, **before consolidation runs** — not at checklist
  time (Phase 5). This is what lets an accepted substitute merge correctly with any other line
  in the session needing the same resolved ingredient: if one recipe needs "bulgarian feta"
  (substituted to "regular feta") and another recipe separately needs "regular feta", they
  consolidate into one shopping-list line, not two. For each ingredient pulled from the
  session's recipes: look up `ingredient_substitutions` for a matching `original_name`; if a
  default exists, resolve to the substitute's name for consolidation purposes; otherwise use the
  ingredient's name as-is. **The recipe's own stored ingredient name is never modified** by this
  process — only the resolved name used for that session's consolidation and shopping list. See
  [Scaling Logic > Consolidation across recipes](./scaling-and-consolidation.md#scaling-logic), which this step feeds into.
- **Management.** Settings ([Chunk 2.5](./build-status/phase-2-recipe-library.md#phase-2--recipe-library), already built) gains a
  section listing existing substitution rules — view, change which substitute is the default,
  add/remove substitute options for an ingredient, delete a rule entirely. This is the only
  place a rule can be edited or reversed after creation; there is no separate creation path here
  (see "No proactive tagging UI" above).

### Open item
Handled for free by rules applying at the ingredient-name level: the same obscure ingredient
showing up in more than one recipe needs no extra design, since one rule already covers every
recipe using that name. What's *not* covered: if the same ingredient needs correcting in the
recipe data itself (a genuine fix, not a substitution) across several recipes at once, there's
no bulk rename/merge utility — each recipe is edited individually via the existing editor. Real
enough to flag, not real enough to build speculatively — see
[Deferred Decisions](./deferred-decisions.md#deferred-decisions).

---

### The substitution merge — Phase 4 design + capture-time flagging

The Phase 4 [Ingredient Substitution](#ingredient-substitution) design (global
`ingredient_substitutions` rules, an `is_default` that auto-applies **silently** at
consolidation, cross-session memory, resolution inside the pure `consolidation.consolidate()`)
and the addendum's capture-time flagging idea are **merged** (decisions confirmed 2026-09-06):

| Axis | Merged behaviour |
|---|---|
| **Who proposes a swap** | Both: a dedicated Gemini call flags candidates per recipe at capture; the user can also swap later in the recipe editor, or session-only during planning. |
| **Source of truth** | The **ingredient record**. `recipe_ingredients` gains `resolved_ingredient` (nullable — the swap this recipe actually uses) and `substitution_note` (freetext why). `name` stays the *original* (merge decision #2 — reuse `name`, no separate `original_ingredient` column). **M8:** also `resolved_quantity` / `resolved_unit` — the swap's *absolute* amount when it differs ("2 cob" → "2 can"). Only meaningful with `resolved_ingredient` set; both NULL = name-only. |
| **Quantity/unit transform (M8)** | A swap can change the amount and unit, not just the name. Recipe-level: absolute `resolved_quantity`/`resolved_unit`, scaled by servings at consolidation. Library-level: an equivalence pair (`original_qty`/`original_unit`/`substitute_qty`/`substitute_unit`) the quick-pick uses to pre-fill the recipe-level absolute — user still confirms. Session override: the same pair, applied to the scaled quantity. Resolved in `consolidate_session()` / `_scaled_lines()`, never in pure `consolidate()`. No cross-unit conversion table — the entered number is the equivalence. See [Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec). |
| **Auto-apply** | **Never silent.** `is_default` and `get_default_substitution_map()` are removed. Every swap is confirmed per recipe. |
| **Memory** | A remembered swap is a **suggestion accelerator, not an action** (merge decision #1). `ingredient_substitutions` → `remembered_substitutions` (drop `is_default`; add `note`, `last_used_at`). When an ingredient is confirmed and a remembered swap exists for its name, that swap is **pre-selected / top-ranked** in the confirm UI under a visible "from your saved swaps" label — the user still clicks confirm. The AI *flagging* call is never told about past choices; only the UI pre-fill uses memory. |
| **Reversibility** | Recipe-level: clear `resolved_ingredient` in the editor → back to `name`. The original is never lost. Deleting a `remembered_substitutions` entry never cascades to recipes or past sessions. |
| **Consolidation** | `consolidation.consolidate()` becomes **pure again** — it reads `resolved_ingredient` (fallback `name`) as plain data, no substitution logic. Session-only planning swaps resolve in the `consolidate_session()` orchestrator *before* the pure function runs (merge decision #3 — the plumbing built in Chunk 4.7 stays, the resolution point moves). "Also remember" from a planning swap may add a `remembered_substitutions` row (merge decision #4). |
| **1-to-many** | Out of scope for now (merge decision #5). `substitute_name` stays a single freetext string; `buttermilk → "milk + lemon juice"` is one string the user splits by hand if they want. 1:many is a [Deferred Decision](./deferred-decisions.md#deferred-decisions). Note this is a *different* axis from the M8 quantity/unit transform — M8 is one substitute with a different amount, not several substitute ingredients. |

**Kept from Phase 4:** the library table (as `remembered_substitutions`), multiple
substitutes per ingredient, Settings management (reframed as a quick-pick library),
the planning-time ad-hoc swap + `ConsolidateRequest.overrides` plumbing, `substitution_note`.
**Removed:** `is_default` + its reassign/enforce logic, silent auto-apply,
`get_default_substitution_map()`, substitution resolution inside `consolidate()`.
**Added:** the capture-time AI flagging call, per-ingredient confirm/decline,
`recipe_ingredients.resolved_ingredient` / `substitution_note`, the "Pending AI processing"
badge.

### Ingredient Substitution Flagging — the merged spec

Supersedes both the addendum's stricter "no memory at all" wording and the Phase 4
"global auto-applying rules" design — see the merge table above. **If existing code
disagrees with the rules below, the code is wrong** (this feature has drifted before).

**What it IS:**
- At capture time, a dedicated Gemini call flags ingredients *in this specific recipe* that
  could be substituted, each with a suggested substitute + an optional short note (e.g.
  `buttermilk` → `"milk + lemon juice"`, note "acidulate the milk and rest 10 min").
  **Tightened 2026-09-07** (Capture-Fixes-Staged.md issue 4 — hand-testing found the model
  volunteering "why this works" rationale the maintainer didn't want, e.g. *"Regular butter
  contains milk solids that brown and burn faster than ghee, so watch the heat"*): the note
  is null on a straight 1:1 swap and, when present, is capped at ~10 words / a real
  method-or-quantity change only — never an explanation of why the two items are similar.
  `SUBSTITUTIONS_SYSTEM_PROMPT` carries the exact wording; `flag_substitutions()` also drops
  (not truncates) any note over 120 chars server-side as a backstop against the model
  ignoring the prompt.
- Each flag is surfaced for **per-recipe, per-ingredient confirm/decline** before anything is
  stored. Confirm → `recipe_ingredients.resolved_ingredient` + `substitution_note` set on
  *that* recipe. Decline → `resolved_ingredient` left NULL (falls back to `name`); the flag
  is dismissed, not hidden from history.
- On confirm, an optional **"save this swap"** tick writes/updates a
  [`remembered_substitutions`](./data-model.md#remembered_substitutions) row (name → name + note). Unticked
  = one-off, this recipe only.

**Quantity/unit transform (M8):**
- The confirm control also takes an optional **amount + unit** for the substitute — for when
  the swap isn't 1:1 in the recipe's own unit ("2 whole corn cobs" → "2 cans of corn",
  "500 g fresh spinach" → "250 g frozen spinach"). Confirm with these set →
  `recipe_ingredients.resolved_quantity` / `resolved_unit` (the absolute amount for *this*
  recipe). Left blank → name-only swap, the recipe's own `quantity` / `unit` carry through
  as before.
- **Only valid alongside a name change.** "Buy this in a different unit without changing the
  item" is a [`product_units`](./data-model.md#product_units) concern, not a substitution. Both fields are
  cleared whenever `resolved_ingredient` is cleared. Schema enforces both-or-neither.
- **The AI does not suggest the numbers** (decided M8) — `flag_substitutions` stays
  name + note only; extending its structured output would be fresh
  [§0a](./security.md#0a-prompt-injection-hardening-highest-priority) number/unit-validation surface for
  values the user has to sanity-check anyway. Revisit if hand-entry proves tedious —
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions).
- **Library rows** ([`remembered_substitutions`](./data-model.md#remembered_substitutions)) store it as an
  *equivalence pair* (`original_qty original_unit ≈ substitute_qty substitute_unit`), not an
  absolute — an absolute makes no sense across recipes. On quick-pick, the UI multiplies by
  the current recipe line's quantity to pre-fill `resolved_quantity` (when `original_unit`
  matches that line's unit; otherwise it pre-fills the name only and leaves the amount for
  the user). "Save this swap" records the pair as "this recipe's amount ≈ what you entered".
- **Consolidation** reads only the finished `resolved_quantity`/`resolved_unit` (scaled by
  servings in `_scaled_lines()`); the pure `consolidate()` is unchanged. See
  [Scaling Logic > Consolidation across recipes](./scaling-and-consolidation.md#consolidation-across-recipes).

**Memory — accelerator, never an action:**
- If `remembered_substitutions` has entries for a flagged ingredient's `name`, they are
  **pre-selected / top-ranked** in the confirm UI beneath a visible "from your saved swaps"
  label. The user still clicks confirm — nothing is applied without that per-recipe action.
- The Gemini flagging call is **never** given past choices — every recipe's AI flags are
  independent. Only the UI pre-fill consults memory.

**What it is NOT:**
- ❌ No silent auto-apply anywhere. No `is_default`.
- ❌ No substitution *resolution* inside the pure `consolidation.consolidate()` — it reads
  `resolved_ingredient` (fallback `name`) as plain data. (A session-only planning swap
  resolves one layer up, in the `consolidate_session()` orchestrator — that's retained.)
- ❌ No 1-to-many split as structured data yet (`substitute_name` is one freetext string).
- ❌ No cross-unit conversion table (M8). The quantity/unit transform is a straight multiply
  by the user-supplied ratio and a unit-label swap — the app never tries to compute
  "cob → can" or "g → can" itself. It also does not do pack resolution across a unit change:
  a line resolved to "6 can" with a `product_units` row seeded in grams gets no pack
  breakdown (shows "6 can"). Known limitation — seed a `can`-unit `product_units` row if
  pack resolution is wanted there.

**Call behaviour:** its own Gemini call; same Flash → Flash-Lite → queue chain; if it
fails/queues, extraction still completes and the recipe is usable — flags are enrichment,
not a blocker. The "Pending AI processing" badge names *which* sub-task (extraction /
substitution / section) is still outstanding.

**Where it lives in the app:**
- **Capture review screen** (`capture-review.js`) — the per-ingredient confirm/decline +
  quick-picks + "save this swap" tick, after extraction, before the recipe is saved.
- **Recipe editor** (`recipe-edit.js`) — the same per-ingredient controls, so a swap can be
  added / changed / cleared later. Clearing `resolved_ingredient` reverts to `name`.
- **Planning session review** (`session-review.js`) — the existing ad-hoc swap, now a
  **session-only override** (client-held, passed in `ConsolidateRequest.overrides`, resolved
  in `consolidate_session()` before `consolidate()`). From M8 an override may also carry the
  equivalence pair (`SessionOverride` gains `original_qty`/`original_unit`/`substitute_qty`/
  `substitute_unit`), applied to the scaled quantity for every line using that name — only
  where `original_unit` matches the line's unit. Optional "also save this swap" →
  `remembered_substitutions` row; never edits recipe data.
- **Settings** (`settings-substitutions.js`) — reframed: view / edit note / delete
  `remembered_substitutions` entries. A pure quick-pick library. No default toggle. Deleting
  never touches recipes or past sessions.

## Ingredient Aliases

**Status: in scope, built 2026-09-10.** Generalised from hand-testing feedback about oil
("oil vs oil spray vs vegetable oil vs canola oil is stupid, needs to be consolidated") into a
plain, reusable, **not oil-specific** mechanism — see [Data Model >
ingredient_aliases](#ingredient_aliases), `services/ingredient_aliases.py`,
`routers/settings.py`, `static/js/settings-ingredient-aliases.js`.

### Not the same feature as Ingredient Substitution — read this before touching either file
This has bitten before (the substitution design itself went through two superseded drafts —
see its History section) so it's spelled out explicitly:

| | [Ingredient Substitution](#ingredient-substitution) | Ingredient Aliases (this section) |
|---|---|---|
| What it means | "I don't want to buy X, buy Y instead" — a genuinely *different* product | "X and Y are *the same thing* to my household" |
| Confirmation | Required, every time, per recipe | Never — no per-instance decision to make |
| Where it's recorded | On the specific `recipe_ingredients` row (`resolved_ingredient`) | Nowhere on the recipe — a recipe keeps showing exactly what it said |
| Applies to | Just that recipe, unless separately confirmed elsewhere | Every recipe using that name, retroactively, the moment the group exists |
| Reversibility | Clear the recipe's own `resolved_ingredient` | Delete the alias row — nothing else to undo |
| Motivating example | "bulgarian feta" → "regular feta" (hard to find) | "canola oil" / "oil spray" → "vegetable oil" (same thing, different wording) |

If a swap changes what's actually bought (a real product decision someone might want to
reconsider), it's a substitution. If two names are just different ways of saying the same
shopping-list item, it's an alias. When genuinely unsure, default to substitution — it asks
for confirmation, which is the safer failure mode (asking once when it wasn't needed is a
minor annoyance; auto-merging two things that weren't actually interchangeable means silently
under-buying one of them).

### Design

- **Flat `alias_name -> canonical_name` map**, any number of aliases per canonical target
  (a "group" is just every row sharing one canonical name — there's no separate groups
  table). One privileged canonical label per group, chosen by whoever creates the alias, not
  inferred (e.g. alphabetically or by recency) — asking "what should this be called on your
  list" is clearer than the app guessing.
- **Resolved dynamically, at consolidation time, not written into recipe data** (confirmed
  2026-09-10 — the alternative, rewriting `recipe_ingredients.name` to the canonical form on
  save, was considered and rejected): a recipe's own detail page always shows exactly what it
  said ("canola oil" stays "canola oil"), and adding a new group benefits **every existing
  recipe immediately** — no need to re-save anything, and no bulk-rename tool required
  (closing part of the gap the [Duplicate Recipe Prevention](./duplicate-recipe-prevention.md#duplicate-recipe-prevention)
  "Open item" flags, for the aliasing case specifically). Resolution happens in
  `services/session_consolidation.py > _scaled_lines()`, as the **last** normalisation step —
  after a recipe's own `resolved_ingredient` (substitution) and any session-only override are
  already applied — so an alias folds together names arrived at by any path uniformly. The
  pure `services/consolidation.py` is untouched: it still just receives finished lines.
- **Silent merge for a plain (name-only) alias** (confirmed 2026-09-10) — a merged line looks
  exactly like any other consolidated line, the same as the existing salt-group prompt-based
  canonicalisation already behaves. No "(includes canola oil, oil spray)" annotation. **Not**
  the case when an alias carries a quantity/unit transform — see below.
- **Downstream matching (staples, product_units, AnyList fuzzy-match) needs no separate
  change** — because resolution happens before grouping, every consolidated
  `session_checklist_items.ingredient_name` is already the canonical name by the time staple
  membership or a `product_units` pack lookup checks it. A staple named "vegetable oil"
  correctly catches a recipe that said "canola oil", with no extra code.
- **Chains are flattened at write time, not followed at read time** — `create_alias` /
  `update_alias` always resolve a new `canonical_name` to its final target before storing
  (and re-point any existing row that was pointing at a name which just became an alias
  itself), so `alias_map()`/consolidation only ever need a single dict lookup, never a
  chain-walk.
- **Complements, doesn't replace, the existing salt-group prompt-based canonicalisation**
  ([Recipe Capture](./recipe-capture.md#recipe-capture--ai-extraction) extraction prompt). That mechanism is for
  well-known universal synonyms an LLM can recognise on its own ("kosher salt" → "salt") and
  only ever fires on AI-extracted content. This is for household-specific groupings no
  generic model could know are meant to merge (canola vs vegetable oil is genuinely
  contextual — plenty of households would *not* want those grouped) and — because it's
  applied at consolidation time, not extraction time — it also covers manually-typed
  ingredients, which the prompt never touches. Building this also resolves the older
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions) "Ingredient synonym normalisation" item's
  Settings-managed-alias-table half; feeding the alias table into the extraction prompt
  itself (so the capture-review screen already shows the canonical name, not just the final
  shopping list) is a small possible follow-on, not built now — see
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions).
- **Seeded with one starter group** (`app/seed_data.py > INGREDIENT_ALIAS_SEEDS`): "canola
  oil" and "oil spray" → "vegetable oil" (already a `STAPLE_SEED` — see [Staples Starter
  List](#staples-starter-list)). "olive oil" (also already a staple) is deliberately **not**
  included — a household commonly wants it kept distinct from a neutral oil (dressing vs
  frying), and this is exactly the kind of pair that shouldn't be auto-merged without a
  deliberate choice. Add more groups via Settings only as a real gap shows up — same
  "don't pre-guess" rule as staples/product_units/usuals/substitutions.
- **Managed in Settings** (`settings-ingredient-aliases.js`, card title "Ingredient groups") —
  rows grouped by canonical name (same list-grouped-by-target trick as
  `settings-substitutions.js`), add a new alias by typing both names, delete to ungroup.
  `alias_name` isn't editable after creation (delete + recreate); `canonical_name` can be
  changed (re-grouping), same convention as `RememberedSubstitution`'s immutable
  `original_name`.

### Quantity/unit equivalence transform (added 2026-09-10, second kickoff)

Raised by "lemon juice should be put on the list as a lemon, same thing with limes" — a
plain rename isn't enough here, since "2 tbsp lemon juice" needs to become "1 lemon", not
"2 tbsp lemon". Two mechanisms already do half of this each — substitutions already support
exactly this shape of equivalence pair but require confirming the swap on every recipe;
aliases apply silently everywhere but only rename. **Resolved: extend aliases with an
optional pair, not a new third mechanism** — this is squarely "a kitchen fact, not a
judgement call" (unlike a substitution), so no per-recipe confirmation makes sense.

- **Same pair shape as `remembered_substitutions`' M8 transform**
  (`alias_qty`/`alias_unit ~= canonical_qty`/`canonical_unit`), with one deliberate
  difference: `canonical_unit` may be blank. A substitution's substitute is always some
  purchasable product with a real unit; an alias's canonical target is very often a bare
  discrete count ("1 lemon", no unit — same as `recipe_ingredients.unit` being NULL for
  unitless produce). This is why aliases have their own validator
  (`schemas/ingredient_aliases.py > _validate_alias_pair`) instead of reusing
  `schemas.substitutions.validate_equivalence_pair` verbatim — both-or-neither and positive
  on the two *quantities* only, no unit required on either side.
- **Resolved in the same place as a plain alias** — `session_consolidation.py > _apply_alias`
  mirrors `_apply_session_override`'s M8 logic exactly: converts `qty / alias_qty *
  canonical_qty` only when `alias_unit` matches the line's own unit (case-insensitive) and
  the line is a real scalable quantity (not "to taste"); a unit mismatch falls back to a
  name-only rename rather than guessing across units — same precedent, same reasoning, as
  the M8 substitution transform. No cross-unit conversion table here either.
- **Shown, not silent — the maintainer's call, 2026-09-10.** Unlike a plain rename, a
  quantity conversion is an approximation (a lemon's juice yield varies), so the consolidated
  line's `note` records what it was converted from: "from 4 tbsp lemon juice". Multiple
  aliased contributions to the same canonical name sum into one fragment per distinct
  (source ingredient, source unit) pair — two recipes each needing "2 tbsp lemon juice" show
  as one "from 4 tbsp lemon juice", not two. Mechanically: `IngredientLine` carries an
  optional pre-conversion `(source_qty, source_unit, source_name)`, which the pure
  `consolidation.py` treats as opaque display metadata — it just sums matching triples per
  group into `ConsolidatedItem.conversion_notes`, with no idea *why* a line has one.
  `session_consolidation.py` appends `"from " + ", ".join(conversion_notes)` to the line's
  `note`, combining with (not replacing) a needs_review breakdown / overage hint / "to taste"
  marker if one is also present.
- **Fixed alongside this**: `checklist.js`'s `qtyText()` never showed `item.note` for a
  normally-resolved line (only for a needs_review conflict, or when the quantity was null
  entirely) — `session-review.js`'s equivalent function already did. This meant a
  conversion note (or an overage hint, or "(+ to taste)") was visible on the review screen
  but invisible on the checklist screen right before push. Both screens now match.
- **Seeded** (`app/seed_data.py > INGREDIENT_ALIAS_SEEDS`): "lemon juice" (3 tbsp ≈ 1 lemon)
  and "lemon zest" (3 tsp ≈ 1 lemon) → "lemon"; "lime juice" (2 tbsp ≈ 1 lime) and "lime
  zest" (2 tsp ≈ 1 lime) → "lime". Deliberately in whichever unit a recipe is more likely to
  actually use (zest in tsp, not tbsp, even though "1 tbsp per lemon" is the same ratio) —
  2026-09-10 live verification caught a tbsp-seeded zest ratio silently failing to match a
  tsp-based recipe, falling back to a name-only rename that then hit an unrelated real
  mass/volume-style conflict with a juice contribution and got flagged `needs_review` instead
  of converting cleanly. **"orange juice" deliberately NOT seeded** — flagged by the
  maintainer as genuinely recipe-dependent (sometimes a real ingredient in its own right,
  e.g. a marinade base bought as a carton, not always a fresh-squeeze stand-in), so guessing
  would be wrong often enough not to attempt automatically. Ratios are rough kitchen
  approximations, documented as such via each seed's `note`.

### Shared-source combining — juice + zest from the same fruit (raised 2026-09-10, designed
and built 2026-09-12)

A recipe needing both "2 tbsp lemon juice" and "1 tsp lemon zest" realistically needs **one**
lemon (you zest it, then juice it) — but each alias converted and summed independently, so
the result was roughly `lemons-for-juice + lemons-for-zest` (additive), not
`max(lemons-for-juice, lemons-for-zest)` (shared-source). The failure direction was safe
(bought somewhat more fruit than strictly necessary, never less) but a real inaccuracy, not
just cosmetic.

**The distinguishing signal, found on a second planning pass**: this can only ever happen
when **two or more *different* alias sources, each carrying an M8-style quantity/unit
transform, resolve to the same `canonical_name`** — a plain rename alias with no transform
(the oil-variant case) is never affected by this and shouldn't be; those genuinely are the
same interchangeable substance and correctly keep summing across recipes unchanged. That
combination — 2+ transform-carrying aliases sharing a canonical target — is *only* ever the
result of the household having deliberately configured it that way, so it needed **no new
table, no new Settings screen, no per-group toggle**: the mechanism is implicit in how
aliases already get set up. If a future third extraction (e.g. "lemon slices", consumed
whole and not available for zest/juice afterward) shouldn't pool with the other two, the
existing escape hatch already covers it — alias it to a *different* canonical name (e.g.
"lemon (whole)") instead, and it's automatically excluded.

**Scope: per recipe, not per session.** Combining only makes real-world sense within one
recipe's own cooking act (zest then juice the same physical lemon in one go) — two
*different* recipes, plausibly cooked on different days, wouldn't share a partially-used
lemon between them. So: within one recipe, 2+ transform-alias sources sharing a canonical
name combine via `max`; across different recipes, their own (already-combined) totals still
sum normally, exactly as before.

**"Take the max" is a deliberate, accepted trade-off, not a certainty** — confirmed with the
maintainer 2026-09-12. A recipe explicitly meaning "zest of 3 lemons for one component,
*separately* juice of 1 fresh lemon for another" (the zested fruit not actually available
for juicing) would still combine down to 3 here, one short of the true 4 needed — genuinely
ambiguous from ingredient-list data alone (there's no method/step data to know whether the
zested fruit stays available). Accepted because the common case (same fruit, zest then
juice) is overwhelmingly more frequent, and under-buying by one cheap, commonly-available
item is a trivial in-store fix — same "safe-direction approximation, not a precise model"
standing as `coarse_ingredients`' `recipes_per_pack` guess.

**Mechanism** (`services/session_consolidation.py > _apply_shared_extraction_adjustment()`,
called once per recipe slot in `_scaled_lines()`, right after that slot's own ingredient
lines are built): group the slot's own alias-transform lines by which alias they came from
(the existing `source_name` field), sum within each group, and — whenever 2+ distinct
sources contributed — add ONE synthetic negative-quantity `IngredientLine` (`recipe_id`/
`recipe_label` left `None` so it never appears in the "which recipe" breakdown;
`source_name` left `None` so it's never picked up by the conversion-notes aggregation)
equal to `max(group sums) - sum(group sums)`. That single correction nets the group's total
down to the max once summed with everything else in `consolidation.consolidate()` — every
real line, and everything the breakdown/conversion-notes show, is completely untouched, so
the transparency work already done for both features (CLAUDE.md > "Which recipe is this
ingredient from" and > Ingredient Aliases' conversion notes) still shows the real, honest,
per-recipe, per-source amounts. `consolidation.py`'s pure summing logic needed **no
changes** — it has no idea this happened, same discipline as every other extension to this
pipeline (aliases, coarse ingredients).

---

## Ingredient Unit Handling

**Status: in scope, built 2026-09-12** — designed across two rounds of Decision Dialogue with
the maintainer, then all six chunks built and verified the same day (see chunk list below).
Resolves both the
["Free-text unit scaling" and "Ingredient-specific unit vocabulary" Deferred
Decisions](#deferred-decisions) rows, and the
[Decision Dialogue](./decision-history.md#ingredient-specific-unit-vocabulary-raised-2026-09-10-hand-testing--not-yet-scoped)
below. Raised by 2026-09-10/11 hand-testing: "free text input for units causes issues,"
compounded by real recipes genuinely needing several different units for the same ingredient
(garlic: clove, head, spoon, or gram, all legitimate depending on the recipe) and by pure
spelling variance ("clove" vs "cloves", "g" vs "grams") already causing false
`needs_review` conflicts between recipes that mean the same thing.

### Distinct from Ingredient Aliases — a different axis entirely
[Ingredient Aliases](#ingredient-aliases) resolves two *names* being the same shopping item
("canola oil" = "vegetable oil"). This resolves problems with the *unit*, given a correctly-
identified, correctly-named ingredient — a different axis, addressed by a different pair of
mechanisms below. The two are independent and can both apply to the same ingredient line
(a line's name resolves through substitution → alias; its unit resolves through the synonym
map below; the two resolutions don't interact).

### Why this needed a full re-plan, not just "restrict units to a fixed list"
The maintainer's own framing after the first pass of questions (2026-09-11) is worth keeping
verbatim, because it's the reason the design below has four distinct, independently-scoped
layers instead of one "unit vocabulary" table:

> There are an incredible amount of units... you can't have a one size fits all approach for
> a given ingredient, garlic can be measured in spoons, heads, cloves or grams... It's also a
> problem when entering recipes manually, eg clove vs cloves, g vs grams etc which all
> produce entries the system considers unreconcilable... 10g + 1tbsp of parsley is probably
> just a bunch, I'm not out shopping for parsley by the gram and tablespoon... Blocking an
> entry is not a good idea... I'd prefer not to do all of this crap manually as well, I don't
> want to spend hours inputting "legitimate" units for ingredients, this is the admin I'm
> trying to remove.

Four genuinely different problems fell out of that: (A) the same unit spelled two ways is
treated as two different units (the actual cause of most real `needs_review` false
positives); (B) one ingredient legitimately has several valid units, so there is no single
"correct" unit to restrict an ingredient to; (C) a near-duplicate unit should be nudged
toward the existing one, never blocked; (D) some ingredients shouldn't have their quantity
summed at all, because the real-world purchase granularity is coarser than any recipe's
stated amount. Layers A-C fix the actual reconciliation bug with **zero manual admin**
(everything is either a small one-time universal seed or derived live from existing recipe
data); Layer D is a distinct mechanism, included in this same design pass at the maintainer's
request rather than parked separately.

### Layer A — unit spelling canonicalisation (fixes the real `needs_review` bug)
- New table [`unit_synonyms`](./data-model.md#unit_synonyms): `alias_unit -> canonical_unit`, resolved
  **dynamically** at consolidation time in `services/session_consolidation.py`, at the same
  point and for the same reason `ingredient_aliases` is — a Settings-editable synonym added
  later should retroactively fix recipes saved before it existed, which a save-time rewrite
  of `recipe_ingredients.unit` couldn't do.
- A generic, **tableless** pluralisation-strip rule runs first and handles the common
  discrete-unit case (`clove`/`cloves`, `bunch`/`bunches`, `sprig`/`sprigs`, `can`/`cans`) —
  same small heuristic idea as `checklist.py`'s `_singularise()`, applied to unit strings.
  `unit_synonyms` only needs entries for genuine word-form differences the strip rule can't
  derive on its own (`gram`(`s`) → `g`, `tablespoon`(`s`)/`tbs` → `tbsp`,
  `millilitre`(`s`)/`milliliter`(`s`) → `ml`, `litre`(`s`)/`liter`(`s`) → `L`,
  `teaspoon`(`s`) → `tsp`, `kilogram`(`s`) → `kg`, `cup`s already matches itself under the
  strip rule) — a small, finite, **universal** seed (not per-ingredient, so not the admin
  burden the maintainer is avoiding), Settings-editable ("Unit spellings" card,
  `static/js/settings-unit-synonyms.js`) for anything the seed and the strip rule both miss.
- Applied to every `IngredientLine`'s unit, right alongside (but independently of) ingredient
  alias resolution — same layer, orthogonal axis. `consolidation.py`'s pure dimension
  bucketing needs no change: it already groups by whatever unit string it's handed, so
  feeding it the canonical spelling instead of the raw one is enough to fix the false
  conflicts on its own.

### Layer B — per-ingredient known units, derived live (zero new admin)
- **No new table.** "What units has garlic been used with before?" is a plain query against
  existing `recipe_ingredients` data (pooled across an ingredient's alias group — typing
  "vegetable oil" surfaces units seen under "canola oil" too, matching the "same shopping
  item" philosophy). New endpoint `GET /api/v1/recipes/ingredient-units?name=…`.
  household-scale data, no caching needed.
- Surfaced as quick-pick buttons on the unit input in manual entry (`recipe-form.js`),
  editing (`recipe-edit.js`), and the capture review screen (`capture-review.js`) — reduces
  the chance of a fresh typo-variant ever being typed, with zero setup, because it's built
  entirely from what's already in the library.

### Layer C — duplicate-unit nudge (warn, never block)
- When a typed unit doesn't exactly match anything in that ingredient's own known-units list
  (Layer B) but is fuzzy-close to one, show a dismissible inline hint — "did you mean
  'clove', already used 3 times for this ingredient?" — using the same `difflib`-based
  approach [Duplicate Recipe Prevention](./duplicate-recipe-prevention.md#duplicate-recipe-prevention) already uses for
  near-duplicate recipe names (exact threshold tuned during this feature's own verification,
  not assumed to transfer unchanged from recipe-name matching to short unit strings). Never
  blocks — accepting the suggestion is one click, dismissing it and keeping the typed unit is
  free.

### Layer D — coarse ingredients (the parsley problem)
A genuinely different mechanism from A-C: not a unit-spelling fix, but an escape hatch from
quantity math entirely for ingredients where precision is pointless.
- New table [`coarse_ingredients`](./data-model.md#coarse_ingredients): a flat set of ingredient names (same
  shape as `staples`), each with a `purchase_label` (e.g. "bunch") and a `recipes_per_pack`
  divisor (default 3).
- At consolidation, an ingredient in this table (checked against its final resolved name,
  same point `is_staple` checks) **skips the normal sum → normalise → round pipeline
  entirely** — its contributing lines' quantities and units are never summed or compared.
  Instead: count how many recipe **slots** (not summed quantity) use it this session,
  `packs_needed = ceil(slot_count / recipes_per_pack)`, displayed as
  `"{packs_needed} × {purchase_label}"` (or just "needed", no count, if `purchase_label` is
  NULL). This scales with how many recipes actually call for the ingredient, without
  reintroducing the cross-unit precision tracking the feature exists to avoid.
- **Accepted approximation, documented not solved further**: `recipes_per_pack` is a rough,
  per-ingredient, Settings-editable guess, not derived from anything — a session with more
  parsley-heavy recipes than the default accounts for will under-count until the household
  either bumps the checklist quantity by hand that week or tunes `recipes_per_pack` down for
  that ingredient. Same standing as the [juice + zest over-count
  limitation](#ingredient-aliases) above: a safe-direction approximation, not a precise model.
- **The [per-recipe "which recipe is this from" breakdown](./scaling-and-consolidation.md#which-recipe-is-this-ingredient-from)
  needs no special-casing for coarse items** — it's independent of how the total is computed,
  and still shows each contributing recipe's own raw (uncanonicalised-by-Layer-D) quantity
  and unit, which is exactly the "why do I need this" transparency the feature exists for.
- Mechanically: `consolidation.py`'s pure `consolidate()` never sees a coarse ingredient's
  lines at all — the orchestrator (`session_consolidation.py`) partitions lines by name
  before calling it, builds coarse `ConsolidatedItem`s by hand (two new optional fields,
  `is_coarse` / `coarse_packs_needed` / `coarse_purchase_label`, added to the existing
  dataclass but only ever populated by the orchestrator — `consolidate()`'s own logic is
  unchanged), and merges both sets of items before the upsert loop. The pack-resolution step
  (`session_pack_resolution.pack_options_for()` / `purchase_units.resolve_packs()`) is skipped entirely for coarse
  items — that machinery is precision-driven (brute-force pack-size combinations against a
  precise required quantity), which is exactly what "coarse" means opting out of.

### Admin reduction — auto-learning new unit spellings (raised 2026-09-12, built same day)

Once Layers A–D above fixed the actual reconciliation bug, the maintainer asked a broader
question: could the *remaining* manual Settings admin — noticing a new unit misspelling and
adding a `unit_synonyms` row by hand, and by extension `ingredient_aliases` /
`coarse_ingredients` / `remembered_substitutions` / `staples` / `product_units` /
`usual_items` — be reduced further with some "intelligent" automation, with an explicit,
permission-granting caveat: if it's too much of a code burden to do this well, plain manual
entry is a perfectly acceptable fallback.

**Verdict: `unit_synonyms` is the one strong candidate; everything else stays manual.** The
dividing line is objective fact vs. household preference:
- `staples` / `usual_items` ("do we always have this on hand" / "buy this on a schedule") and
  `ingredient_aliases` / `coarse_ingredients` ("is X the same shopping item as Y for us" / "do
  we track this ingredient coarsely") are all judgment calls about *this* household's kitchen.
  An AI can only guess at them — automating these would just move the guessing from the
  household to the model, which the household would still need to check, and would quietly
  undo the "don't pre-guess, wait for a real gap to show up in use" discipline every other
  reference list in this file already follows deliberately (staples, product_units, usuals
  were all seeded minimal on purpose — see their own sections). Not built. If typing these
  ever proves genuinely tedious, an AI-*suggests*/household-*confirms* flow (the same shape as
  the existing capture-time substitution flagging) is the fallback worth reaching for, not
  full automation — see [Deferred Decisions](./deferred-decisions.md#deferred-decisions).
- `unit_synonyms` is different in kind: whether "tablespoon" means "tbsp" is a fact about
  English, not a preference — no household could reasonably want it resolved any other way,
  so it's safe to resolve silently, with no confirmation step, the same standing as the
  static seed itself.

**What was built:**

1. **Expanded the static seed** (`app/seed_data.py > UNIT_SYNONYM_SEEDS`) with a few more
   universal cooking-measurement word-forms the original pass missed: `gramme` → `g`,
   `kilogramme` → `kg`, `kilo` → `kg`, `tspn` → `tsp`, `tbspn` → `tbsp`, `ltr` → `l`. Their
   plurals (`grammes`, `kilogrammes`, `kilos`, `ltrs`) all resolve for free once
   `strip_plural()` reduces them to these singular forms — same cascade the original seed's
   own comment describes — verified with the same throwaway check-script approach as Chunk 1,
   confirming no dead/unreachable rows. Deliberately **not** added: a bare `c` for cup (too
   ambiguous a single letter to seed blind) or anything imperial (`oz`, `lb`, `pint`, `quart`)
   — those aren't spelling variants, they're a different magnitude that would need a real
   conversion, exactly what this table must never attempt (see [Data
   Model > unit_synonyms](#unit_synonyms)).
2. **A new, fourth Gemini call** — `services/ai_extraction.py > classify_units()` — alongside
   the existing three (`extract_recipe`, `flag_substitutions`, `suggest_sections`), same §0c
   gates (`AI_EXTRACTION_ENABLED` / `AI_EXTRACTION_FAKE_MODE`), same
   allow-list-validate-the-output discipline as `suggest_sections()`. Given a batch of raw
   unit strings, it asks only "is this a common alternate spelling of `g`/`kg`/`ml`/`l`/
   `tsp`/`tbsp`/`cup` — the exact same unit, not merely similar or convertible — or something
   else?" and returns a match only for a confident, same-magnitude spelling variant; anything
   else (a genuinely different/discrete unit, or the model unsure) comes back unmatched, same
   as today's behaviour. **Deliberately not wrapped in the §0a untrusted-content delimiter**
   — unlike the other three calls, its input is a unit the household itself typed into the
   ingredient form, not scraped or photographed content, so it isn't the untrusted-content
   scenario §0a exists for. The output is still allow-list validated regardless (never trust
   a model's output just because it parsed) — that's a general habit here, not one specific
   to §0a.
3. **The trigger** — `services/unit_synonyms.py > learn_new_units()`, called after an
   ingredient is saved (manual entry, editing, or an edit made on the capture-review screen)
   with whichever raw unit(s) it introduced. A unit is only worth spending a call to classify
   at all when it (a) doesn't already resolve to a standard unit via the existing
   `strip_plural()` / `unit_synonyms` map, **and** (b) has never appeared as any
   `recipe_ingredients.unit` value anywhere before. Condition (b) is the load-bearing one: a
   real, established discrete unit (`clove`, `bunch`, `pinch`, …) only ever gets asked about
   **once**, the very first time it's ever typed anywhere in the app — the moment that first
   (correctly negative) classification happens, it becomes an "already-used" unit like any
   other and is never asked about again, at zero further cost. A confident match writes a
   normal, Settings-editable `unit_synonyms` row through the existing `create_synonym()` —
   from then on Layer A resolves it silently and for free, indistinguishable from a
   manually-added row.
- **Never blocks or slows down a save on failure.** Disabled/quota/parse/network failures are
  all caught and logged; the unit is simply left as its own distinct unit — exactly today's
  behaviour with the feature turned off. No retry queue: if the same spelling is ever typed
  again, condition (b) above now sees it (the just-saved row is itself a use of it) and skips
  straight past re-asking — the failure mode degrades cleanly to "add it by hand once, same
  as before this feature existed," never to a repeated wasted call or a blocked save.
- **Scope, deliberately narrow for now**: only `recipe_ingredients.unit`, the primary
  quantity unit. `recipe_ingredients.resolved_unit` (a substitution's swapped-to unit) isn't
  covered — the same mechanism could extend there later if it ever proves a real gap; not
  built speculatively, same standing as everything else in this file.

> **Note (added during the 2026-09-12 CLAUDE.md split):** the "Build chunks" checklist that
> used to follow directly here (chunks 1-6, all done and verified) is live status/progress
> tracking, not spec — it now lives in
> [Build Status — Ingredient Unit Handling Chunks](./build-status/ingredient-unit-handling-chunks.md).

