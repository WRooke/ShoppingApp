# Nutrition & MyFitnessPal Export

## Nutrition & MyFitnessPal Export

**Status: post-MVP, unscheduled.** Raised 2026-09-06 — a secondary user wants recipes in
MyFitnessPal (MFP) for calorie/macro tracking. Designed here so the shape is on record;
**do not implement speculatively.** There is no reserved phase — it is picked up only if the
household still wants it once the core app is in daily use. When it does come up, re-verify
the MFP-API situation below first (this note may be a year or more old by then).

### The MyFitnessPal API reality (checked 2026-09-06)
MFP has **no usable API for a project like this, in either direction:**
- The official diary/food API has been approved-partner-only for years (fitness-device makers
  and similar), with no self-serve key. Under Armour closed it to general developers; Francisco
  Partners (current owner) has not reopened it.
- There is therefore no supported way to **push** a recipe into MFP, nor to **read** MFP's food
  database or a recipe's computed nutrition back out.
- Community reverse-engineered libraries (e.g. `python-myfitnesspal`) scrape the logged-in web
  UI. Same fragility class as the AnyList connector — breaks on site changes and bot-protection
  — but with a stricter ToS and no derisking spike behind it. Not used in the in-scope design
  below; considered only in the deferred item.

### In scope (when built): recipe export for MFP's Recipe Importer
MFP has a built-in **Recipe Importer** that takes a recipe URL or pasted ingredient text,
matches each line against MFP's own food database, and computes per-serving macros inside MFP.
That feature does the nutrition work; the app's only job is to hand it a clean recipe.

- New `services/` module (e.g. `nutrition_export.py`) that renders a saved recipe as
  MFP-importer-friendly output: the ingredient lines (quantity + unit + name, one per line,
  from `recipe_ingredients`) plus the serving count (`recipes.base_servings`). Plain data
  formatting, no external calls, unit-testable with no DB — fits the `services/` purity norm in
  [Code Architecture](./code-architecture.md#code-architecture--maintainability).
- One endpoint (e.g. `GET /api/v1/recipes/{id}/mfp-export`), `{"ok": ...}` envelope.
- One button on the recipe detail view ("Export to MyFitnessPal") that shows the formatted
  text to copy, and surfaces the recipe's `source_url` directly if it has one (MFP's importer
  accepts a URL; Chunk 3.7 makes `source_url` reliably available and displayed).
- **No schema change.** Everything needed already exists on `recipes` / `recipe_ingredients`.
- **No macros stored or shown in the app.** MFP holds the nutrition data; the app does not try
  to mirror it. Confirmed 2026-09-06.

### Deferred: reading nutrition back into the app
Whether the app should ever hold per-recipe macros — for a per-planning-session nutrition
summary, say — is left open. The only realistic source is scraping MFP (no API, as above), so
this needs its own decision with the fragility/ToS trade-off in view, and a derisking spike
like AnyList had if adopted. Independent alternatives (an in-app estimate from USDA FoodData
Central, Claude estimation, or a hand-maintained `ingredient_nutrition` table) were considered
and set aside 2026-09-06 — the ask is specifically to use MFP, and a parallel estimate that
doesn't match MFP's numbers is two sources of truth. See [Deferred Decisions](./deferred-decisions.md#deferred-decisions)
and the Decision Dialogue.

If this is ever built, expect roughly: an `ingredient_nutrition` reference table keyed by
`ingredient_name` (per-100g / per-unit macros, user-correctable — same pattern as
[`product_units`](./data-model.md#product_units) / [`product_sections`](./data-model.md#stores-store_sections-product_sections)),
per-recipe cached totals, and ingredient-level weight/density data to convert
tsp/tbsp/cup/"each" into the grams nutrition data is quoted in (partly overlapping
`product_units.purchase_qty`). That unit conversion is the genuinely hard part and the main
reason this is not a small feature.

### Out of scope (unchanged)
Cost/budget tracking stays out ([Explicitly Out of Scope](./project-overview.md#explicitly-out-of-scope)); this does
not reopen it. Nutrition display, if it ever lands, is a reference readout — not a calorie-goal
or diet-tracking feature inside the app. MFP is that tool.

---

