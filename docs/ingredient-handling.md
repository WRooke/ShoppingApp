# Ingredient Handling — Normalisation, Substitution, Aliases & Units

## Ingredient Normalisation

**Status: base mechanical normalisation built 2026-09-27 (the ingredient-name-matching plan) —
supersedes the original "do not implement automatic synonym matching" note below, which is
stale and kept only for history.**

`app/services/text_normalize.py::normalise_ingredient_name()` is the single shared
grouping/matching key used everywhere an ingredient name is compared for equality: base
consolidation grouping (`consolidation.py`), every Settings-managed reference table's own
matching (`product_units`, `coarse_ingredients`, `ingredient_aliases`, `remembered_substitutions`,
`usual_items`), and the checklist's AnyList fuzzy-match. It is deliberately **mechanical only** —
lowercasing, whitespace-collapse, hyphen/dash-folding to a space, and a conservative
pluralisation-strip (including an `-us` guard so asparagus/couscous/hummus/citrus are never
mistaken for a plural, and a small explicit whitelist for the `leaf`/`leaves`,
`loaf`/`loaves`-style irregular plural — never a blind "-ves" suffix rule, which would corrupt
"cloves"/"olives"/"gloves"). It never resolves genuine word-choice differences ("stock" vs
"broth", "capsicum" vs "red capsicum", dialect spelling) — those stay `ingredient_aliases`'
job, a household judgement call, never guessed at mechanically.

Because this is now the shared key everywhere, `recipe_ingredients.name`/`resolved_ingredient`
are deliberately **not** rewritten through it (see `app/services/recipes.py`'s
`_normalise_ingredient_name()`/`_norm_resolved()` docstrings) — a recipe's own detail page must
always show exactly what it said, and every consolidation pass re-derives the matching key
fresh from that raw value, so nothing needs to be pre-computed or stored.

Existing rows in the 5 reference tables above, written before this module existed, were
backfilled onto the new normalised form by a one-time Alembic data migration
(`bcaf5b44af53`) — CLAUDE.md's non-negotiable rule 3 (no data loss on the prod database) meant
that migration never deletes a row: a collision between two existing rows leaves the "losing"
row's value completely untouched rather than merging or dropping it, printing a report line for
the maintainer to reconcile by hand via the existing Settings CRUD. See
[Deferred Decisions](./deferred-decisions.md#deferred-decisions) for the tracked follow-up
(reconciling any such left-behind rows, and any other pre-existing data that would benefit from
this and the alias/AI-assisted-grouping mechanisms below but predates them).

**Original 2026-09-05 rules, kept for history — the "do not implement automatic synonym
matching" line no longer holds, superseded above:**
- Store all names in lowercase
- Strip leading/trailing whitespace
- Canonical forms: "beef mince" not "minced beef", "spring onion" not "green onion"
- On first capture, names are stored as Claude returns them (after lowercasing)
- The user can edit names in the recipe editing UI

---

## Ingredient Substitution

**Status: in scope, manual only.** Design = the MERGE of the Phase 4 approach and the
addendum's capture-time flagging, confirmed 2026-09-06, built in Phase 3.9 chunk M4. **The
AI-flagging half was removed 2026-09-30** — the maintainer judged the Gemini call that
*suggested* a substitute added too little value for the call it cost ("I know what I'm doing
when substituting"). Everything else described below — the recipe-level swap, the
`remembered_substitutions` quick-pick library, the quantity/unit transform, the session-only
ad-hoc override during planning, and Settings management — is **unaffected and stays fully
in place**; only the AI *suggestion* layer is gone. The full, authoritative spec is
[Substitution — the current spec](#substitution--the-current-spec) and the merge table just
above it (kept as a historical record of the 2026-09-06 merge decision — read its "Who
proposes a swap" row with the 2026-09-30 removal in mind).

Distinct from [Ingredient Normalisation](#ingredient-normalisation) above: normalisation
recognises two names as *the same thing* ("green onion" = "spring onion"). Substitution
treats two *different* products as interchangeable for shopping, because one is obscure or
hard to find — e.g. "bulgarian feta" → "regular feta".

> **Note (2026-09-27, F0):** the `plain yoghurt` → `greek yoghurt` `remembered_substitutions`
> row is superseded, not deleted. The household's own prod data showed this exact pair already
> recorded as a substitution, confirming it's a settled preference rather than a per-recipe
> judgement call — so it was promoted to a silent `ingredient_aliases` row instead (see
> [Ingredient Aliases](#ingredient-aliases)). The old substitution row is deliberately **left in
> place** (CLAUDE.md non-negotiable rule 3 — no dropped row holding real household data) rather
> than deleted: it's functionally inert now (substitution resolution runs before alias
> resolution, and a remembered substitution never auto-applies on its own regardless), so it can
> only ever resurface as a redundant-but-harmless "from your saved swaps" quick-pick if someone
> manually reopens the swap UI for "plain yoghurt" again. If a future session finds this row and
> wonders why it looks stale, this is why — it isn't a bug, and removing it is a normal,
> reversible Settings deletion for the maintainer to do if they want it gone, not something a
> migration or this doc should do unilaterally.

### Summary of the merged design

- **Entered manually** — at capture-review time (per recipe), *and* editable later in the
  recipe editor, *and* swappable session-only during planning. No AI proposes a candidate any
  more (removed 2026-09-30); the entry field and quick-picks are always there, just never
  pre-suggested.
- **Stored** on the ingredient record: `recipe_ingredients.resolved_ingredient` (nullable —
  the swap this recipe uses) + `substitution_note`, and (Phase 3.9 M8) optional
  `resolved_quantity` / `resolved_unit` when the swap also changes the amount/unit ("2 corn
  cobs" → "2 cans"). `name` stays the original. Clearing `resolved_ingredient` clears all of
  it and reverts.
- **Confirmed per recipe, always.** No silent auto-apply, no `is_default`.
- **Remembered** in [`remembered_substitutions`](./data-model.md#remembered_substitutions) *only* as a
  quick-pick accelerator — it pre-fills / top-ranks the suggestion in the per-recipe entry
  field under a "from your saved swaps" label; the user still confirms.
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
  applied to the [`product_units`](./data-model.md#product_units) multi-pack-size note (and,
  formerly, to the now-retired [`staples`](./data-model.md#staples) starter list): don't
  pre-guess, wait for a real gap to show up in use. The *only* way an
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
| **Who proposes a swap** | ~~Both: a dedicated Gemini call flags candidates per recipe at capture~~ — **the AI half was removed 2026-09-30**; the user swaps manually at capture-review time, in the recipe editor, or session-only during planning. |
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
**Added, then removed again:** the capture-time AI flagging call and its "Pending AI
processing" badge contribution were added in Phase 3.9 M4, then removed 2026-09-30 (manual
value judged not worth the AI call). **Still in place:** per-ingredient confirm/decline (now
always a manual pick, never AI-prefilled), `recipe_ingredients.resolved_ingredient` /
`substitution_note`.

### Substitution — the current spec

Supersedes the addendum's stricter "no memory at all" wording and the Phase 4
"global auto-applying rules" design — see the merge table above. **If existing code
disagrees with the rules below, the code is wrong** (this feature has drifted before). This
section used to be titled "Ingredient Substitution Flagging" and centred on the AI call that
proposed a candidate; that call was removed 2026-09-30 (renamed from
`#ingredient-substitution-flagging--the-merged-spec` — old links to that anchor should be
updated). Everything below describes the manual-only mechanism that remains.

**What it IS:**
- A manual swap, entered per recipe via the swap control (`ingredient-swap.js`) on the
  capture-review screen or the recipe editor — a free-text "use instead" field, an optional
  short note, and quick-pick buttons for any saved swaps. Nothing suggests a candidate; the
  user always types or picks one.
- The entered swap is **per-recipe, per-ingredient, confirmed by construction** — there's no
  separate confirm/decline step because nothing is pre-filled to accept or reject. Filling
  the field and saving the recipe → `recipe_ingredients.resolved_ingredient` +
  `substitution_note` set on *that* recipe. Leaving it blank → `resolved_ingredient` stays
  NULL (falls back to `name`).
- On save, an optional **"save this swap"** tick writes/updates a
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
- **Entirely manual, always was for the numbers** (decided M8, before the AI half even
  existed) — nothing has ever suggested the amount/unit; the user always types it. Revisit
  only if hand-entry proves tedious — [Deferred Decisions](./deferred-decisions.md#deferred-decisions).
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
- If `remembered_substitutions` has entries for an ingredient's `name`, they're offered as
  **quick-pick buttons** beneath the swap field, under a visible "saved" label — a single
  saved swap also pre-fills the field, so the common case ("I always sub this one thing") is
  one tap, not retyping. The user still has to save the recipe for it to take effect.

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
- ❌ **No AI involvement at all, as of 2026-09-30.** No Gemini call, no candidate suggestion,
  nothing to fail/queue/retry for this feature — it's ordinary form data now, same trust
  level as any other manually-typed field. (Historical note, no longer true: this section used
  to describe a dedicated Gemini call here, its own place in the Flash → Flash-Lite → queue
  chain, and a "substitution" step in the "Pending AI processing" badge — all removed.)

**Where it lives in the app:**
- **Capture review screen** (`capture-review.js`) — the manual swap field + quick-picks +
  "save this swap" tick, after extraction, before the recipe is saved.
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
- **Downstream matching (product_units, AnyList fuzzy-match) needs no separate change** —
  because resolution happens before grouping, every consolidated
  `session_checklist_items.ingredient_name` is already the canonical name by the time a
  `product_units` pack lookup checks it.
- **Chains are flattened at write time, not followed at read time** — `create_alias` /
  `update_alias` always resolve a new `canonical_name` to its final target before storing
  (and re-point any existing row that was pointing at a name which just became an alias
  itself), so `alias_map()`/consolidation only ever need a single dict lookup, never a
  chain-walk.
- **Complements, doesn't replace, the extraction-prompt canonicalisation.** Originally a
  hardcoded, extraction-only mechanism (well-known universal synonyms an LLM can recognise on
  its own, e.g. "kosher salt" → "salt"), separate from this table (household-specific groupings
  no generic model could know are meant to merge — canola vs vegetable oil is genuinely
  contextual — and, applied at consolidation time, also covers manually-typed ingredients the
  prompt never touches). Building this table resolved the older
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions) "Ingredient synonym
  normalisation" item's Settings-managed-alias-table half at the time (2026-09-10). **Fully
  resolved 2026-09-27 (Fix 2, F2.3)**: the extraction prompt no longer hardcodes any pairs as
  literal prose — the 3 legacy pairs (plain-salt group, "minced beef"→"beef mince",
  "green onion"/"scallion"→"spring onion") are now `source='system'` rows in *this* table,
  seeded once by migration `62a354151f0d`, and every real capture's system prompt is built
  dynamically (`app/services/ai_extraction/calls.py::build_extraction_system_prompt()`) from
  both those `system` rows and the household's own `user` rows — so a capture-review screen now
  shows the canonical name immediately for a household preference too (e.g. "heavy cream" →
  "thickened cream"), not only at the final shopping list. See [Recipe
  Capture](./recipe-capture.md#claude-extraction-prompt-system)'s 2026-09-27b note for the exact
  mechanism (the two hint sections, the character cap, the §0a wrapping).
- **Seeded with one starter group** (`app/seed_data.py > INGREDIENT_ALIAS_SEEDS`): "canola
  oil" and "oil spray" → "vegetable oil" — these three read as the same product to most
  households. "olive oil" is deliberately **not** included — a household commonly wants it kept
  distinct from a neutral oil (dressing vs frying), and this is exactly the kind of pair that
  shouldn't be auto-merged without a deliberate choice. Add more groups via Settings only as a
  real gap shows up — same "don't pre-guess" rule as product_units/usuals/substitutions.
- **Finding real gaps beyond hand-testing (Fix 5, 2026-09-27)**: dialect/product-naming pairs
  like "stock"/"broth" share no characters in common, so string-similarity matching can't find
  them — only world knowledge (an LLM, or unbounded manual review) can. `scripts/
  suggest_ingredient_groupings.py` runs a one-off, maintainer-triggered AI audit against a
  household's own real, not-yet-aliased ingredient names (`services/recipes.py::
  distinct_ingredient_names()`), printing suggested groups for manual review — never
  auto-applied, never a permanent endpoint. See
  [Deferred Decisions](./deferred-decisions.md#deferred-decisions) for the reusable-on-demand
  follow-on this could grow into.
- **Managed in Settings** (`settings-ingredient-aliases.js`, card title "Ingredient groups") —
  rows grouped by canonical name (same list-grouped-by-target trick as
  `settings-substitutions.js`), add a new alias by typing both names, delete to ungroup.
  `alias_name` isn't editable after creation (delete + recreate); `canonical_name` can be
  changed (re-grouping), same convention as `RememberedSubstitution`'s immutable
  `original_name`. **Resolved 2026-09-27/28 (Fix 3, then Fix 4)** — the checklist's own merge
  action (below) offers "always treat these as the same ingredient?" inline when a mismatch is
  noticed at shopping-list time (Fix 3); the on-the-fly alias nudge (`static/js/
  ingredient-name-hints.js`, mirroring Ingredient Unit Handling's Layer C) catches it even
  earlier, right where a name is first typed — recipe entry, recipe editing, and capture-review
  all offer "keep both, treat as one shopping item" the moment a close-but-not-identical name is
  noticed (Fix 4). Settings remains the only place to *edit* an existing group's canonical name
  or delete one.
  **Redesigned 2026-09-23 (mockup-approved — cluttered/unclear grouping was
  flagged in review):** each canonical group is now one `.settings-group-card` with a visible
  alias count in its heading; each alias row shows its (still immutable) name as a labelled
  disabled field — "Ingredient name (fixed — delete and re-add to rename)" — instead of a
  bare unexplained span; the 4-field qty/unit equivalence pair sits under an "Amount
  conversion (optional)" sub-heading so it reads as one concept; Delete is a de-emphasised
  underlined text button, separated from the primary Save action. Layout only — no change to
  the add/edit/delete/reload flow described above.

### Session-scoped merges — the ephemeral counterpart (Fix 3, 2026-09-27)

A durable alias is the right tool when a household is confident two names are *always* the same
shopping item. Sometimes that confidence isn't there yet — a one-off mismatch between two
recipes this week, or a household member who wants to try folding two lines together without
committing every future recipe to it. The checklist's merge action (see [Checklist Screen Logic >
Checklist-time ingredient merge](./checklist-and-shopping.md#checklist-time-ingredient-merge-fix-3-2026-09-27))
answers "always treat these as the same ingredient?" with **no** by writing a
`session_ingredient_merges` row instead of an `ingredient_aliases` one:

- Same shape as an alias's own equivalence pair (`member_name`/`canonical_name` +
  optional `alias_qty`/`alias_unit`/`canonical_qty`/`canonical_unit`), scoped by `session_id`,
  cascade-deleted when the session is deleted — no manual cleanup, no trace left behind once the
  session is gone.
- Resolved in `session_consolidation.py::_scaled_lines()` as the step immediately *after* alias
  resolution — a session merge can fold together two names that are each already resolved
  through an alias, but an alias can never see or undo a session merge (the reverse would let a
  one-off, this-session-only choice leak into every other session).
- `services/session_merges.py` deliberately reuses `ingredient_aliases.AliasResolution`'s exact
  shape rather than a bespoke dataclass, so the same equivalence-matching code serves both
  tables.
- **Never a Settings-managed concept** — it exists only to be created and consumed within one
  session's lifetime; there is nothing to list, edit, or delete outside of it.

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
- New table [`coarse_ingredients`](./data-model.md#coarse_ingredients): a flat set of ingredient names, each
  with a `purchase_label` (e.g. "bunch") and a `recipes_per_pack` divisor (default 3).
- At consolidation, an ingredient in this table (checked against its final resolved name, after
  substitution/alias resolution finishes) **skips the normal sum → normalise → round pipeline
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
`coarse_ingredients` / `remembered_substitutions` / `product_units` / `usual_items` (`staples`
at the time this was raised, since retired — see [Decision History > Staples — usefulness
assessment](./decision-history.md#staples--usefulness-assessment-raised-2026-09-27)) — be
reduced further with some "intelligent" automation, with an explicit, permission-granting
caveat: if it's too much of a code burden to do this well, plain manual entry is a perfectly
acceptable fallback.

**Verdict: `unit_synonyms` is the one strong candidate; everything else stays manual.** The
dividing line is objective fact vs. household preference:
- `usual_items` ("buy this on a schedule") and `ingredient_aliases` / `coarse_ingredients`
  ("is X the same shopping item as Y for us" / "do we track this ingredient coarsely") are all
  judgment calls about *this* household's kitchen. An AI can only guess at them — automating
  these would just move the guessing from the household to the model, which the household would
  still need to check, and would quietly undo the "don't pre-guess, wait for a real gap to show
  up in use" discipline every other reference list in this file already follows deliberately
  (product_units and usuals were both seeded minimal on purpose — see their own sections). Not
  built. If typing these
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

