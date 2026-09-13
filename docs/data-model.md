# Data Model

## Data Model

All tables use SQLite via SQLAlchemy. Alembic for migrations — intended from Phase 2 onward,
actually bootstrapped at Phase 3 Chunk 3.7 (the first change to an existing table); see
[Code Architecture > Migrations](./code-architecture.md#migrations) for that history. `Base.metadata.create_all()`
still runs on startup as the fresh-DB fast path.

**Audit columns (Schema & Planning Addendum #5, build now):** `created_at` / `updated_at` are
added to every *mutable* table below — trivial to add now, effectively impossible to backfill
onto existing rows later. `shopping_history`, `api_usage`, and `api_usage_resets` are
append-only logs that are never updated after insert, so they keep their existing single
timestamp (`pushed_at` /
`timestamp`) instead of a redundant pair.

### `recipes`
```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL
source_type     TEXT NOT NULL  -- 'url', 'photo', 'manual' — how the ingredients got INTO the app
source_url      TEXT           -- nullable
source_image_path TEXT         -- nullable, path to stored image file
base_servings   INTEGER NOT NULL DEFAULT 4

-- Source provenance (added Phase 3 Chunk 3.7, 2026-09-06). Where the recipe ORIGINALLY
-- came from, in a human-meaningful form — orthogonal to source_type (a photographed or
-- hand-typed recipe can still cite a book; a URL recipe can too). Not mutually exclusive
-- with source_url and not enforced as such. source_page is TEXT not INTEGER so "142-143",
-- "142 & 145", "ch. 3" all work. Both nullable; shown on the recipe detail view, editable
-- from edit mode and the capture review screen. See CLAUDE.md > Recipe Capture and
-- > Build Phases > Phase 3 > Chunk 3.7.
source_book     TEXT            -- nullable, e.g. "Ottolenghi SIMPLE"
source_page     TEXT            -- nullable, e.g. "142" or "142-143"
notes           TEXT           -- nullable, free text for the recipe overall (see note below)
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP

-- Recipe history (Schema & Planning Addendum #2). Build now (Phase 1 schema),
-- logic wired up from Phase 2 onward (increment on "mark cooked", editable rating/note
-- from the recipe detail view).
times_made      INTEGER NOT NULL DEFAULT 0
last_made_at    DATETIME        -- nullable
rating          TEXT            -- nullable: 'up' | 'down' | NULL=unrated. Tri-state, not 5-star.

-- "Suggest something" schema prep (Addendum #3). Fields only — no suggestion logic or UI yet.
cuisine         TEXT            -- nullable, freetext or small controlled list
protein         TEXT            -- nullable, freetext or small controlled list

-- Soft-delete (Addendum #5). Build now (Phase 1 schema).
archived_at     DATETIME        -- nullable; set instead of hard DELETE. Default library views
                                 -- filter WHERE archived_at IS NULL (Phase 2 logic).

-- AI capture status (Phase 3.9 M6). JSON array of still-outstanding AI sub-tasks for this
-- recipe, e.g. ["flag_substitutions","suggest_sections"]. NULL or "[]" => nothing pending
-- (manual recipes, or a capture fully processed). Drives the "Pending AI processing" badge.
ai_tasks_pending TEXT           -- nullable
```
> **Resolved at kickoff:** the addendum proposed a second freetext `note` field
> ("used half the chilli next time") alongside the above. Confirmed this is the same purpose
> as the existing `notes` column — no second field was added.

### `recipe_ingredients`
```
id              INTEGER PRIMARY KEY
recipe_id       INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE
name            TEXT NOT NULL       -- normalised lowercase, e.g. "beef mince". This is the
                                     -- ORIGINAL ingredient (merge decision #2 — no separate
                                     -- original_ingredient column).
quantity        REAL NOT NULL
unit            TEXT               -- nullable for unitless items (e.g. "eggs", "onions")
preparation     TEXT               -- nullable, e.g. "finely diced", "at room temperature"
sort_order      INTEGER NOT NULL DEFAULT 0
-- Substitution (Phase 3.9 M4 — see AI Provider Migration > Ingredient Substitution Flagging).
-- The swap THIS recipe actually uses, set only by explicit per-recipe user confirmation
-- (capture review or recipe editor). NULL = no substitution, use `name`. Clearing it reverts
-- to the original. Consolidation reads resolved_ingredient (fallback `name`) as plain data.
resolved_ingredient TEXT           -- nullable
substitution_note   TEXT           -- nullable, freetext — why the swap works
-- Substitution quantity/unit transform (Phase 3.9 M8 — see AI Provider Migration >
-- Ingredient Substitution Flagging, and Scaling Logic > Consolidation across recipes). The
-- ABSOLUTE amount this recipe's swap actually buys, e.g. "2 whole corn cobs" -> resolved
-- "canned corn" at 2 / "can". Only meaningful alongside resolved_ingredient; both NULL =
-- name-only swap, keep this row's own quantity/unit. When set, consolidation scales
-- (resolved_quantity, resolved_unit) instead of (quantity, unit). Clearing
-- resolved_ingredient clears these too. No cross-unit conversion is attempted — the number
-- the user entered IS the equivalence.
resolved_quantity   REAL           -- nullable
resolved_unit       TEXT           -- nullable
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### `product_units`
```
id              INTEGER PRIMARY KEY
ingredient_name TEXT NOT NULL UNIQUE  -- normalised lowercase, matches recipe_ingredients.name
purchase_label  TEXT NOT NULL          -- e.g. "dozen", "500g pack", "2L bottle"
purchase_qty    REAL NOT NULL          -- numeric quantity in purchase_unit
purchase_unit   TEXT                   -- unit of purchase_qty, e.g. "g", "L", "each"
notes           TEXT                   -- nullable
is_preseeded    BOOLEAN NOT NULL DEFAULT 0
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```
> **Phase 4 note (multi-pack-size purchase units, confirmed 2026-09-05):** `ingredient_name
> UNIQUE` is a Phase 1 simplification that assumes one purchase pack size per ingredient. Real
> usage doesn't hold that assumption — some ingredients are genuinely sold in more than one
> pack size (e.g. a 500g tub and a 1kg tub of the same product), and resolving a required
> quantity against only the smaller size produces the wrong answer (buying two 500g tubs to
> cover 750g instead of one 1kg tub). At Phase 4 kickoff, ship an Alembic migration that drops
> the `UNIQUE(ingredient_name)` constraint and replaces it with `UNIQUE(ingredient_name,
> purchase_label)` instead — a `product_units` row becomes one of possibly several pack-size
> options for that ingredient, rather than the only one. No other column changes. See
> [Purchase unit resolution](./scaling-and-consolidation.md#scaling-logic) for the selection algorithm this enables, and
> [Deferred Decisions](./deferred-decisions.md#deferred-decisions). Do not implement before Phase 4 — this is a plan,
> not a build-now item, and most ingredients will keep exactly one seeded pack size regardless
> (a second option only gets added, via Settings, for the specific items where it's been
> noticed to matter — there's no requirement to pre-enumerate pack sizes for every ingredient
> in the seed data).

### `staples`
```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL UNIQUE  -- normalised lowercase
notes           TEXT                  -- nullable
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### `remembered_substitutions`

**Phase 3.9 M4** — the Phase 4 `ingredient_substitutions` table, reshaped: **`is_default`
dropped** (no silent auto-apply anywhere), `note` and `last_used_at` added. It is now a
**pure quick-pick library** — it never applies a swap; it only pre-fills / top-ranks the
suggestion in a per-recipe confirm UI (see
[AI Provider Migration > Ingredient Substitution Flagging](./ingredient-handling.md#ingredient-substitution-flagging--the-merged-spec)).
A row is created only when the user ticks "save this swap" at capture-review, in the recipe
editor, or (optionally) after a planning-session swap.

```
id              INTEGER PRIMARY KEY
original_name   TEXT NOT NULL       -- normalised lowercase, matches recipe_ingredients.name
substitute_name TEXT NOT NULL       -- normalised lowercase (a single freetext string; 1:many
                                     -- like "milk + lemon juice" is stored verbatim — see
                                     -- Deferred Decisions)
note            TEXT               -- nullable, freetext — pre-fills recipe_ingredients.substitution_note
-- Quantity/unit equivalence (Phase 3.9 M8 — see AI Provider Migration > Ingredient
-- Substitution Flagging). "original_qty original_unit ≈ substitute_qty substitute_unit",
-- e.g. 2 "cob" ≈ 2 "can". A ratio the quick-pick uses to PRE-FILL recipe_ingredients'
-- resolved_quantity/resolved_unit for whatever amount that recipe calls for; the user
-- still confirms. All four NULL = a name-only quick-pick (unchanged from M4). Never
-- auto-applied. original_qty must be > 0 when set.
original_qty     REAL              -- nullable
original_unit    TEXT              -- nullable
substitute_qty   REAL              -- nullable
substitute_unit  TEXT              -- nullable
last_used_at    DATETIME           -- nullable, for quick-pick ordering (most-recent first)
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
UNIQUE(original_name, substitute_name)
```
Multiple substitutes per `original_name` are allowed; **none is a "default"** — they are all
just quick-picks, ordered by `last_used_at`. Never pre-seeded. Deleting a row never touches
any recipe's `resolved_ingredient` or any past session (reversibility is recipe-level).
Managed in Settings (`settings-substitutions.js`, reframed at M4). The equivalence pair is
shown/edited per row from M8 (e.g. "2 cob ≈ 2 can").

### `ingredient_aliases`

**Added 2026-09-10** — see [Ingredient Aliases](./ingredient-handling.md#ingredient-aliases) for the full design.
A flat `alias_name -> canonical_name` map; any number of aliases may share one canonical
target. **Not** the same concept as `remembered_substitutions` above — see that section for
the distinction.
```
id              INTEGER PRIMARY KEY
alias_name      TEXT NOT NULL UNIQUE   -- normalised lowercase, matches recipe_ingredients.name
canonical_name  TEXT NOT NULL          -- normalised lowercase; not required to exist
                                        -- anywhere else — a household can invent a bucket
                                        -- label no recipe ever literally uses
note            TEXT                   -- nullable, freetext, e.g. "roughly 3 tbsp per lemon"

-- Quantity/unit equivalence (added 2026-09-10, second kickoff — "lemon juice should be put
-- on the list as a lemon"). Same idea as remembered_substitutions' M8 pair
-- ("alias_qty alias_unit ~= canonical_qty canonical_unit"), but canonical_unit may be NULL —
-- the canonical side is very often a bare discrete count ("1 lemon"), unlike a substitution's
-- substitute which is always some purchasable product with a real unit. Both-or-neither on
-- the two quantities; alias_qty must be > 0 when set. All four NULL = a name-only alias
-- (unchanged from the original 2026-09-10 oil-variant design).
alias_qty       REAL              -- nullable
alias_unit      TEXT              -- nullable
canonical_qty   REAL              -- nullable
canonical_unit  TEXT              -- nullable

created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```
`canonical_name` is indexed (not unique — many aliases can point at it). Chains are flattened
at write time (`services/ingredient_aliases.py`) — a row's `canonical_name` is always a final
target, never itself an `alias_name` elsewhere in the table; the service re-points any row
that *was* pointing at a name which has just become an alias, so the whole table stays flat,
not just the newly-written row (a row's own equivalence pair is untouched by this re-pointing —
it describes that alias's own conversion, independent of which canonical name it currently
resolves to). Resolved dynamically at consolidation time
(`services/session_consolidation.py`), never written into `recipe_ingredients.name` — a
recipe's own stored ingredient name is never touched, and a newly-added group benefits every
existing recipe immediately. When the equivalence pair is set and the recipe line's own unit
matches `alias_unit`, the amount is converted too and the consolidated line's `note` records
what it was converted from ("from 4 tbsp lemon juice") — shown, not silent, because (unlike a
plain rename) it's an approximation. A unit mismatch skips the conversion and falls back to a
name-only rename, same precedent as the M8 substitution transform. Seeded
(`app/seed_data.py > INGREDIENT_ALIAS_SEEDS`) with the oil-variant group plus lemon/lime
juice and zest → whole fruit — see [Ingredient Aliases](./ingredient-handling.md#ingredient-aliases).

### `unit_synonyms`

**Built 2026-09-12** — see [Ingredient Unit Handling](./ingredient-handling.md#ingredient-unit-handling)
for the full design. A flat `alias_unit -> canonical_unit` map, structurally the plainer
sibling of [`ingredient_aliases`](#ingredient_aliases) — same "warn/merge, not block, no
admin" spirit, but for the *spelling* of a unit rather than the *identity* of an ingredient,
and with no equivalence pair (a unit doesn't need a quantity conversion to its own synonym —
"tablespoon" just *is* "tbsp", not "N tablespoon ≈ M tbsp").
```
id              INTEGER PRIMARY KEY
alias_unit      TEXT NOT NULL UNIQUE   -- normalised lowercase, after the generic
                                        -- pluralisation-strip (see below) has already run
canonical_unit  TEXT NOT NULL          -- normalised lowercase; one of the app's standard
                                        -- units (g, kg, ml, L, tsp, tbsp, cup) or any other
                                        -- free-text unit already in genuine use — NOT
                                        -- constrained to the metric set
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```
Resolved **dynamically** at consolidation time (`services/session_consolidation.py`), the
same architectural point and reasoning as `ingredient_aliases` — a save-time rewrite was
considered and rejected specifically *because* this table is Settings-editable: a synonym
added later should retroactively fix recipes already saved before it existed, which a
save-time rewrite can't do. Plurals of discrete units (`clove`/`cloves`, `bunch`/`bunches`,
`sprig`/`sprigs`) are handled by a generic, tableless pluralisation-strip rule that runs
*before* this map is consulted (same idea as `checklist.py`'s `_singularise()`, applied to
unit strings instead of ingredient names) — this table only needs entries for genuine
word-form differences the strip rule can't derive (`gram`/`grams` → `g`, `tablespoon`(`s`)/
`tbs` → `tbsp`, `millilitre`(`s`)/`milliliter`(`s`) → `ml`, and so on), which is why it's a
small, one-time, *universal* seed rather than per-household admin.

### `coarse_ingredients`

**Built 2026-09-12** — see [Ingredient Unit Handling](./ingredient-handling.md#ingredient-unit-handling)
for the full design, raised by "10g + 1 tbsp of parsley is probably just a bunch, I'm not out
shopping for parsley by the gram and tablespoon." An ingredient in this table skips the
normal sum → normalise → round pipeline entirely — precision is pointless for it, so none is
attempted.
```
id                INTEGER PRIMARY KEY
name              TEXT NOT NULL UNIQUE   -- normalised lowercase; checked against the FINAL
                                          -- resolved name (after substitution + ingredient-
                                          -- alias resolution), same point `is_staple` checks
purchase_label    TEXT                   -- nullable, e.g. "bunch" -- shown as "2 × bunch";
                                          -- NULL = the line just shows "needed", no pack count
recipes_per_pack  INTEGER NOT NULL DEFAULT 3  -- how many contributing recipe SLOTS (not
                                          -- summed quantity) one pack is assumed to cover
notes             TEXT                   -- nullable
created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```
Seeded with parsley, coriander, mint, basil (`purchase_label="bunch"`, default
`recipes_per_pack=3`) — the maintainer's own motivating example plus its obvious siblings,
same "exercise it immediately rather than ship dormant" call as the oil-variant and
lemon/lime alias seeds. Deliberately its own table rather than a flag on `product_units` —
a coarse ingredient's "pack" concept (a plain purchase label + a recipe-count divisor) is
simpler than and orthogonal to `product_units`' precise weight/volume pack-size resolution,
which a coarse ingredient never runs.

### `planning_sessions`
```
id              INTEGER PRIMARY KEY
label           TEXT               -- nullable, e.g. "Week of 14 Jul"
status          TEXT NOT NULL DEFAULT 'active'  -- 'active', 'pushed', 'archived'
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
pushed_at       DATETIME           -- nullable, set when pushed to AnyList
```

### `session_recipes`
```
id              INTEGER PRIMARY KEY
session_id      INTEGER NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE
recipe_id       INTEGER NOT NULL REFERENCES recipes(id)
day_of_week     INTEGER            -- nullable, 1=Monday..7=Sunday
scaled_servings INTEGER NOT NULL
sort_order      INTEGER NOT NULL DEFAULT 0
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```
> **Phase 4 note (leftovers, Addendum #1):** the weekly planner needs a slot type that is *not*
> a recipe — "leftovers from [session/day]" — which pulls no ingredients into consolidation.
> No new table: `recipe_id` becomes nullable and a `slot_type` flag (`'recipe'` | `'leftovers'`)
> is added to this table **when Phase 4 build starts**, not now — do not implement speculatively.

### `session_checklist_items`
```
id              INTEGER PRIMARY KEY
session_id      INTEGER NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE
ingredient_name TEXT NOT NULL       -- consolidated, normalised
total_quantity  REAL               -- nullable (some items are unitless)
total_unit      TEXT               -- nullable
is_staple       BOOLEAN NOT NULL DEFAULT 0
already_on_anylist BOOLEAN NOT NULL DEFAULT 0  -- populated at checklist load time
have_it         TEXT NOT NULL DEFAULT 'unknown'  -- 'yes', 'no', 'partial', 'unknown'
add_to_list     BOOLEAN NOT NULL DEFAULT 0
purchase_label  TEXT               -- nullable, from product_units
purchase_qty    REAL               -- nullable, resolved purchase quantity
display_qty     TEXT               -- nullable, human-readable e.g. "2 × 500g packs"
anylist_item_id TEXT               -- nullable, AnyList item ID if already on list
needs_review    BOOLEAN NOT NULL DEFAULT 0  -- Phase 4 Chunk 4.6: irreconcilable units (mass+volume
                                            -- for one ingredient) — total_quantity/unit left NULL,
                                            -- see `note`. Review UI is Phase 5.
note            TEXT               -- nullable, Phase 4 Chunk 4.6: display-only hint —
                                    -- "100 g + 200 ml" (review breakdown), "to taste",
                                    -- or "450 g spare" (overage, shown only when > ~half a pack)
review_resolved_by_user BOOLEAN NOT NULL DEFAULT 0  -- 2026-09-10 hand-testing fix, added
                                    -- without a CLAUDE.md update at the time (closed at the
                                    -- Phase 5 review, 2026-09-12). Set by
                                    -- `services/checklist.py > resolve_item()` when the user
                                    -- manually picks a total for a needs_review line. See
                                    -- Scaling Logic > "Re-running consolidation is a merge,
                                    -- not a rebuild" below for what it protects against.
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### `shopping_history`
```
id              INTEGER PRIMARY KEY
session_id      INTEGER NOT NULL REFERENCES planning_sessions(id)
pushed_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
items_json      TEXT NOT NULL       -- JSON snapshot of what was pushed
anylist_response_json TEXT          -- nullable, raw AnyList response for diagnostics
```

### `usual_items`

**Phase 5 Chunk 5.4** — "the usuals": recurring non-recipe household items (laundry powder,
dish soap) bought on a schedule independent of meal planning. Distinct from
[`staples`](#staples) (which are recipe ingredients assumed on-hand, surfaced only when a
recipe in the session needs them). Managed in Settings; surfaced on the checklist as its own
group only when *due*. Seeded empty. See
[Checklist Screen Logic > "The usuals"](./checklist-and-shopping.md#the-usuals--household-recurring-items).
```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL UNIQUE   -- normalised lowercase
notes           TEXT                   -- nullable
cadence_days    INTEGER NOT NULL       -- "buy roughly every N days"; days, not sessions —
                                        -- an ad-hoc single-recipe session is an unreliable clock
last_added_at   DATETIME               -- nullable; set when this item is pushed to AnyList.
                                        -- due when NULL or last_added_at + cadence_days < now
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### `ai_call_log`

**Phase 3.9 M5** — replaces `api_usage` + `api_usage_resets` (both dropped in the same
migration; there is no real data — Chunk 3.6 never made a live call). Gemini's free tier has
no per-call dollar cost, so there is no cost column and no "reset spend tracker". One
append-only row per **attempted** Gemini call:

```
id              INTEGER PRIMARY KEY
timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
task            TEXT NOT NULL       -- 'extract' | 'flag_substitutions' | 'suggest_sections'
model           TEXT NOT NULL       -- 'gemini-2.5-flash' | 'gemini-2.5-flash-lite'
outcome         TEXT NOT NULL       -- 'success' | 'quota' | 'error'  ('quota' = 429; a task
                                     -- that then went to the queue also gets a 'queued' row —
                                     -- see capture_queue)
input_tokens    INTEGER            -- nullable (unknown on a pre-response failure)
output_tokens   INTEGER            -- nullable
error_detail    TEXT               -- nullable
context_id      TEXT               -- nullable, e.g. recipe id / capture_queue id for traceability
```
The diagnostics quota indicator counts rows per `model` since local midnight; the attempt
log shows the most recent N. Append-only — never edited or deleted.

### `capture_queue`

**Phase 3.9 M3** — a capture task deferred because both `gemini-2.5-flash` and
`gemini-2.5-flash-lite` returned `429`. Retried ~hourly by a lifespan background poller (not
on an assumed fixed reset). On success the task runs through the normal capture pipeline and
its row is deleted.

```
id              INTEGER PRIMARY KEY
task            TEXT NOT NULL       -- 'extract_url' | 'extract_photo' | 'flag_substitutions' | 'suggest_sections'
payload_json    TEXT NOT NULL       -- JSON: {url|text} or {image_path}; plus {recipe_id} for the
                                     -- post-extraction enrichment tasks (flag/suggest)
recipe_id       INTEGER            -- nullable REFERENCES recipes(id) ON DELETE CASCADE — set for
                                     -- enrichment tasks (the recipe already exists); NULL for a
                                     -- still-pending extraction
queued_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
attempt_count   INTEGER NOT NULL DEFAULT 0
last_attempt_at DATETIME           -- nullable
last_error      TEXT               -- nullable
```

### `stores`, `store_sections`, `product_sections`

From the [Shopping List Store Layout](./checklist-and-shopping.md#shopping-list-store-layout) design. Build now
(Phase 1 schema) — see that section for the rationale. **Resolved at kickoff:**
`product_sections` keys off `ingredient_name` (text), matching the existing
`product_units.ingredient_name` convention, rather than a `product_id` FK — there is no
separate numeric "product" entity anywhere else in this schema, so the addendum's original
`product_id` FK didn't resolve to anything.

```
-- stores
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL UNIQUE
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP

-- store_sections  (this store's walking-order position for each section)
id              INTEGER PRIMARY KEY
store_id        INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE
section_name    TEXT NOT NULL       -- matches the canonical section vocabulary, see below
sort_order      INTEGER NOT NULL DEFAULT 0   -- position in this store's walk order
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
UNIQUE(store_id, section_name)

-- product_sections  (store-independent: which section an ingredient belongs to)
id              INTEGER PRIMARY KEY
ingredient_name TEXT NOT NULL UNIQUE   -- matches product_units.ingredient_name / recipe_ingredients.name
section_name    TEXT NOT NULL
source          TEXT NOT NULL DEFAULT 'user_confirmed'  -- 'ai_suggested'|'user_confirmed'|'user_corrected'
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

The canonical section vocabulary itself (produce, dairy, etc.) is **not** a database table — it's
a small fixed Python constant (`SECTION_VOCABULARY` in `app/seed_data.py`) used to populate
dropdowns in the store-setup and section-tagging UI once those are built. See
[Section Vocabulary Starter List](#section-vocabulary-starter-list).

---

## Pre-seeded Product Units

Seed the `product_units` table on first run with Australian common grocery items. Mark all
as `is_preseeded = 1`. User can edit/delete/add entries. Suggested starter list (implement
as a Python dict in a `seed_data.py` file):

```python
PRODUCT_UNIT_SEEDS = [
    # Dairy & eggs
    {"ingredient_name": "eggs", "purchase_label": "dozen", "purchase_qty": 12, "purchase_unit": "each"},
    {"ingredient_name": "milk", "purchase_label": "2L bottle", "purchase_qty": 2, "purchase_unit": "L"},
    {"ingredient_name": "butter", "purchase_label": "250g block", "purchase_qty": 250, "purchase_unit": "g"},
    {"ingredient_name": "cream", "purchase_label": "300ml carton", "purchase_qty": 300, "purchase_unit": "ml"},
    {"ingredient_name": "sour cream", "purchase_label": "200g tub", "purchase_qty": 200, "purchase_unit": "g"},
    # Meat
    {"ingredient_name": "beef mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "pork mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken breast", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken thigh", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "bacon", "purchase_label": "175g pack", "purchase_qty": 175, "purchase_unit": "g"},
    # Pantry
    {"ingredient_name": "plain flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "self-raising flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "white sugar", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "brown sugar", "purchase_label": "500g bag", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "basmati rice", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "pasta", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "diced tomatoes", "purchase_label": "400g can", "purchase_qty": 400, "purchase_unit": "g"},
    {"ingredient_name": "coconut cream", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "coconut milk", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "chicken stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
    {"ingredient_name": "beef stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
    # Produce — no purchase unit (buy what you need)
]
```

Items not in this table display raw scaled quantity on the shopping list (e.g. "340g passata").

---

## Staples Starter List

Seed a default staples list. User edits via Settings. **Deliberately minimal — confirmed
2026-09-05.** An earlier draft seeded anything vaguely pantry-shaped (garlic, sugar, soy sauce,
vinegars, dried herbs/spices, tomato paste, dijon mustard) without confirming any of it matched
what this household actually treats as "assume we have it, don't put it on the shopping list."
Only these five are confirmed:
```
salt, black pepper, olive oil, vegetable oil, plain flour
```
This list is expected to grow as more recipes go through the system and a genuine staple gap
turns up — add via Settings at that point rather than pre-guessing the rest of it now. Item
seeded as a starter default here, not a staple: **tomato paste** — explicitly ruled out as a
staple (used too situationally to assume it's always on hand); it has no `product_units` entry
either at the moment, since it isn't yet clear whether it should be resolved as a purchase-unit
item or left as raw scaled quantity — revisit if it comes up as a real gap.

---

## Section Vocabulary Starter List

Canonical, fixed, store-independent section names for
[Shopping List Store Layout](./checklist-and-shopping.md#shopping-list-store-layout). Lives as a Python constant
(`SECTION_VOCABULARY` in `app/seed_data.py`), not a database table — `section_name` columns are
free text, so this only drives dropdown choices in the (not-yet-built) store-setup and
section-tagging UI. Starter list, **provisional — confirm/adjust before the Phase 6
UI is built**:
```
produce, dairy, meat & seafood, bakery, frozen, pantry, household, deli, drinks, other
```

---

