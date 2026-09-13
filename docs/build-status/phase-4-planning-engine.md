# Build Status — Phase 4: Planning Engine

### Phase 4 — Planning Engine

**Chunked 2026-09-06** (during Phase 3 Chunk 3.7 / the Phase 3 review — Phase 3 is not yet
closed; this list is planning-ahead, no Phase 4 chunk starts until the Phase 3 review is
signed off), per
[Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking), the way Phases 2
and 3 were. Four deferred decisions were resolved at planning time and folded into the
relevant sections rather than left for kickoff:
- **Australian pack-size rounding → calculate exactly** (option 2). Scaling keeps the true
  quantity; whole-pack rounding + overage display happen only in purchase-unit resolution.
  See [Scaling Logic](../scaling-and-consolidation.md#scaling-logic) and its Decision Dialogue.
- **Weekly planner calendar view → moved to Phase 6.** Phase 4 sets `day_of_week` via a plain
  dropdown; the drag-into-a-7-day-grid layout is a Phase 6 polish item.
- **"Mark cooked" (`times_made` / `last_made_at`) → moved to Phase 6.** Closes the flag
  carried from Chunk 2.1/2.4. A real "cooked" event is post-push (Phase 5+), so it lands in
  the Phase 6 pass, not here.
- **"Suggest something" → stays deferred, no phase.** Not on the Phase 4 deliverable path and
  the signal algorithm is still undesigned. See its Decision Dialogue.

The [ingredient substitution](../ingredient-handling.md#ingredient-substitution) and
[duplicate recipe prevention](../duplicate-recipe-prevention.md#duplicate-recipe-prevention) designs are already written up in
full — the chunks below build them, they are not re-opened here.

- [x] **Chunk 4.1 — Migrations + schema groundwork (no behaviour change).** Rides on the
      Alembic bootstrapped in Chunk 3.7a. Migrations + model updates only, nothing wired to
      logic yet: `session_recipes.recipe_id` → nullable and add
      `slot_type TEXT NOT NULL DEFAULT 'recipe'` (`'recipe'`|`'leftovers'`, see
      [`session_recipes`](../data-model.md#session_recipes) Phase 4 note); `product_units` drop
      `UNIQUE(ingredient_name)` → `UNIQUE(ingredient_name, purchase_label)` (SQLite
      batch/table-rebuild, see [`product_units`](../data-model.md#product_units) Phase 4 note); new
      `ingredient_substitutions` table + model (schema already in [Data Model](../data-model.md#data-model)) +
      `models/__init__.py` registration. Verify migrate-up on a throwaway empty DB matches
      `create_all()`; existing suite stays green.
      Done 2026-09-06 (commit `00c8b8d`) — migration `1bc1ac8991f4` (batch table-rebuild).
      `slot_type` added with a temporary `server_default='recipe'` to backfill existing rows
      during the SQLite batch copy, then the default dropped in a second batch op so the
      column matches `create_all()` (project convention: Python-side defaults only —
      `tests/test_migrations.py` guards the parity). `product_units` single-column
      autoindex replaced by the composite unique; `IngredientSubstitution` model added to
      `app/models/catalog.py` (kept with the other Settings-managed reference tables) and
      registered in `models/__init__.py`. `tests/services/test_settings.py` updated for the
      new constraint (same `(name, label)` pair still 409s; a second pack size for the same
      ingredient is now allowed). Verified: `tests/test_migrations.py` green (`upgrade head`
      == `create_all()` on a fresh DB — columns/PKs/FKs+`on_delete`/indexes/uniqueness all
      identical); full suite 139 pass; migration applied to the dev DB with its 24
      `product_units` + 5 recipes intact, `session_recipes` FKs (`recipes.id` NO ACTION,
      `planning_sessions.id` CASCADE) and `PRAGMA foreign_key_check` clean after the rebuild.
- [x] **Chunk 4.2 — Duplicate recipe prevention.** Slotted early — independent of the session
      engine, touches only `services/recipes.py` + both recipe create paths + the
      capture-review / manual-entry UI. `find_possible_duplicates()` (DB-read only, pure,
      unit-testable); `PossibleDuplicateRecipeError` → `409 POSSIBLE_DUPLICATE_RECIPE`
      translated in `main.py` (same raise-in-service / translate-in-`main.py` pattern as
      `DuplicateStapleNameError`); `allow_duplicate=true` override re-submit; URL-capture
      short-circuits before the Claude call on an exact `source_url` match; archived recipes
      are included in the check with a Restore action (`unarchive_recipe()` +
      `POST /recipes/{id}/restore`). Signals and scope per
      [Duplicate Recipe Prevention](../duplicate-recipe-prevention.md#duplicate-recipe-prevention) — ingredient-set overlap
      stays out. Kickoff open items: fuzzy method + threshold; live `check-duplicate` endpoint
      vs submit-time 409 only.
      Done 2026-09-06. **Kickoff decisions locked:** fuzzy = `difflib.SequenceMatcher`
      ratio ≥ 0.85 **OR** token-set Jaccard ≥ 0.8 (tokens lowercased, punctuation-stripped,
      minus a 10-word stopword set), stdlib only; the live `GET /recipes/check-duplicate`
      endpoint **was** built (warns on name-field blur) with the submit-time 409 as backstop.
      Service (`services/recipes.py`): `find_possible_duplicates()` scans all recipes
      (archived included), best signal per recipe, ordered `source_url` → `name_exact` →
      `book_page` → `fuzzy_name`; `_normalise_source_url` lowercases host, drops fragment,
      strips a trailing slash and `utm_*` params (**scheme is NOT normalised** — http vs
      https do not match; conservative per the spec's enumerated list); `_page_numbers`
      expands `"142-143"` / `"142 & 145"` / `"ch. 3"`; `find_recipe_by_source_url()` backs
      the URL short-circuit and prefers a live row over an archived one; `unarchive_recipe()`.
      `allow_duplicate` on `RecipeCreate` / `CaptureConfirmRequest` / `CaptureUrlRequest`;
      `create_recipe` + `create_recipe_from_capture` take `allow_duplicate=` kwarg. Router:
      `GET /recipes/check-duplicate` declared **before** `GET /{recipe_id}` (else "check-
      duplicate" parses as an id); `POST /recipes/{id}/restore`; `capture/url` raises the
      409 before `fetch_and_extract`. `main.py` handler → 409 with `detail` = match list.
      Frontend: new shared `static/js/dup-warn.js` (`DupWarn.panel()` warn-with-override +
      `DupWarn.liveCheck()` on-blur), wired into `recipe-form.js`, `capture-review.js`,
      `capture.js`; `api.js` gains `recipes.restore` / `recipes.checkDuplicate` and
      `captureUrl(url, allowDuplicate)`; `.dup-warn` styles in `app.css`. Verified: full
      suite **159 pass** (+20 new — 15 service, 5 router); existing recipe tests updated for
      the now-active check (`_create_recipe` helper opts out with `allow_duplicate`, 2
      fuzzy-colliding service-test names changed). Live curl pass on a scratch server for
      every signal + `allow_duplicate` bypass + `check-duplicate` + `restore` + the
      `capture/url` short-circuit (409 with no fetch attempted, confirmed via
      `/diagnostics/recent-errors`). Headless-Edge/CDP click-through
      (`scripts/cdp.py` — see below) of the manual-entry and capture-review screens: live
      blur hint, submit-time 409 panel, "Save anyway" → new recipe detail, zero console
      errors. **New verification tooling committed this chunk:** `scripts/cdp.py`
      (stdlib-only headless-Edge CDP driver) + `HEADLESS_VERIFY.md` (the one documented way
      to drive the frontend) — replaces the ad-hoc `websocket-client`-install dance every
      prior frontend chunk reinvented.
- [x] **Chunk 4.3 — Scaling engine (pure service).** `services/scaling.py`, plain data in /
      plain data out, no DB or network — one of the three highest bug-risk modules per
      [Code Architecture](../code-architecture.md#code-architecture--maintainability), so heavy unit tests.
      **Rescoped 2026-09-06 (grilling — see [Decision Dialogue > Scaling: rounding location &
      rules](#scaling-rounding-location--rules-phase-4-kickoff)):** `scaling.py` now *only
      multiplies* — `scaling_factor()` + `scale_quantity()` (unit preserved verbatim,
      `NO_SCALE_UNITS` pass through `scaled=False`). **No rounding, no unit conversion, no
      pack logic** — all of that moved to Chunk 4.6 and runs once on the summed quantity.
      Done 2026-09-06 (commit `4ee99a8`): 14 unit tests (exact multiplication incl. "ugly"
      results, unit preserved incl. `kg`/free-text, discrete *not* rounded here, factor <1 /
      zero qty, `NO_SCALE_UNITS` case-insensitive passthrough, non-positive base raises).
      Full suite green. `DEFAULT_TARGET_SERVINGS = 4` constant lands with Chunk 4.4's form.
- [x] **Chunk 4.4 — Session CRUD + session-recipe management.** `schemas/sessions.py`,
      `services/sessions.py`, flesh out `routers/sessions.py`. Session CRUD (create / list /
      get / update label+status / archive) with `?limit`/`?offset`; add / update / remove /
      reorder session recipes with `scaled_servings`, `day_of_week` (plain dropdown — calendar
      is Phase 6), `sort_order`. Leftovers slot as its own small service function, not an
      `if slot_type == ...` pile ([Code Architecture](../code-architecture.md#file-size-and-scope-discipline)).
      Service unit tests + router smoke tests.
      Done 2026-09-06 (commit `dece4ee`). Endpoints: `POST /sessions`, `GET /sessions`
      (`?limit`/`?offset`/`?status`), `GET|PATCH /sessions/{id}`, `POST /sessions/{id}/archive`
      (status→'archived'; no hard delete), `POST /sessions/{id}/recipes`,
      `POST /sessions/{id}/leftovers`, `PATCH|DELETE /sessions/{id}/slots/{slot_id}`,
      `PUT /sessions/{id}/slots/order` (`{"ordered_ids":[…]}`, must be exactly the session's
      current slot ids → else `422 SLOT_ORDER_MISMATCH`). `add_session_recipe` /
      `add_leftovers_slot` are separate service functions (no `if slot_type` pile); a recipe
      slot defaults `scaled_servings` to `DEFAULT_TARGET_SERVINGS` (4, added to
      `services/scaling.py`) and appends `sort_order`; a leftovers slot pins
      `scaled_servings=0`, `recipe_id=None`, and `update_slot` keeps `scaled_servings` inert
      on it. `SessionRecipe` gains a read-only joined `recipe` relationship so a slot can
      report `recipe_name` without an N+1 (no column, no migration). Unknown recipe on a slot
      reuses `RecipeNotFoundError`→404. `main.py`: `SESSION_NOT_FOUND` /
      `SESSION_SLOT_NOT_FOUND` → 404, `SLOT_ORDER_MISMATCH` → 422. 16 service unit tests + 11
      router smoke tests; full suite **200 pass**.
- [x] **Chunk 4.5 — Ingredient substitution: persistence + Settings management.**
      **⚠️ Partly superseded by Phase 3.9 M4** — the `is_default` / auto-apply / global-rule
      parts are removed; the table becomes `remembered_substitutions` (a quick-pick library),
      the Settings screen is reframed. What was built (below) still ran; M4 reshapes it.
      `schemas/substitutions.py`, `services/substitutions.py` (CRUD; at-most-one-default per
      `original_name` enforced in the service via the 409 pattern, see
      [`ingredient_substitutions`](../data-model.md#remembered_substitutions)); management section in Settings
      (`routers/settings.py` + `static/js/settings.js`). Also re-check the Settings
      `product_units` view still renders sensibly now an ingredient can have several pack-size
      rows ([`product_units`](../data-model.md#product_units) note). The ad-hoc swap + "remember this?" flow
      is Chunk 4.7 — this chunk is the persistence + management half only.
      Done 2026-09-06 (commit `aa3c8d8`). `services/substitutions.py`: names normalised
      lowercase; first substitute for an `original_name` is *forced* default; setting a new
      default **reassigns** (demotes the old — not a 409); `is_default=false` on the last
      default is allowed (group then has no auto-apply); deleting the default does **not**
      auto-promote a sibling; self-substitution → `INVALID_SUBSTITUTION` (422); duplicate
      `(original, substitute)` pair → `DUPLICATE_SUBSTITUTION` (409, `IntegrityError` on the
      composite unique). `get_default_substitution_map(db) -> {original: substitute}` is the
      read helper Chunk 4.6 consolidation will call. Endpoints under
      `/api/v1/settings/substitutions` (POST/GET/PATCH/DELETE), `main.py` translates the 3
      new exceptions. Frontend: new `static/js/settings-substitutions.js` (split from
      settings.js per the file-size guideline — settings.js was already 338 lines), a third
      Settings card grouping rules by original ingredient with a per-row "use" (default)
      checkbox; `api.js` `settings.substitutions.*`; `.sub-group-heading` CSS. 12 service
      unit tests + 6 router smoke tests; full suite **218 pass**. Headless-Edge/CDP verified:
      3 cards render, add-rule works, first substitute auto-defaults, one default per group,
      normalisation applied, zero console errors. `product_units` multi-row Settings display
      re-check deferred to Chunk 4.6 (lands with the eggs/milk/yoghurt seed).
- [x] **Chunk 4.6 — Consolidation + purchase-unit resolution + summary endpoint.**
      **⚠️ Phase 3.9 M4 removes the substitution step** from `consolidation.consolidate()`
      (it becomes pure — reads `resolved_ingredient` / `name` as data); the session-override
      resolution stays in `consolidate_session()`. Rounding / unit / pack rules are unaffected.
      `services/consolidation.py` and `services/purchase_units.py` — both pure, both in the
      high bug-risk trio, both heavily unit-tested. **All the rounding/normalisation rules
      settled in the 2026-09-06 grilling live here** (see
      [Scaling Logic > Rounding & unit rules](../scaling-and-consolidation.md#rounding--unit-rules--the-consolidationpy-half-chunk-46)
      and the Decision Dialogue). Consolidation: resolve substitution rules first (default
      only, silent); call `scaling.py` per recipe (leftovers slots contribute nothing);
      normalise units — **AU conversions** `tsp`=5 ml / `tbsp`=**20 ml** / `cup`=250 ml,
      `kg`=1000 g, `L`=1000 ml, volumes now merge; sum; **round the sum *upward*** to a clean
      step (ceil 25 for g/ml ≥100, ceil 5 below, ceil to whole for counts incl. free-text
      units, `cup` 2-dp trim only, `NO_SCALE_UNITS` → no number); mass-vs-volume for one
      ingredient stays **irreconcilable** → flagged, both parts shown. Purchase units: the
      zero / one / several `product_units` rows algorithm from
      [Scaling Logic](../scaling-and-consolidation.md#scaling-logic) (brute-force small pack combos, minimise overage then
      pack count), producing `purchase_label` / `purchase_qty` / `display_qty`; line **always
      carries the required quantity**, pack breakdown shown *in addition*; **overage shown
      only when > ~half the pack used**. `POST /api/v1/sessions/{id}/consolidate` **upserts**
      `session_checklist_items` keyed by `ingredient_name` (recompute quantities/packs/flags,
      add/remove lines, **preserve** `have_it` / `add_to_list` on lines that persist — never
      a wipe) and returns the consolidated list. Multi-pack seed items (eggs/milk/yoghurt)
      land in `seed_data.py` here (or 4.1's already done — confirm) so the several-rows path
      is exercised.
      Done 2026-09-06 (commit `f7ae0b5`). Migration `3474369f4c79` adds
      `session_checklist_items.needs_review` + `note` (same server-default-then-drop batch
      pattern as 4.1's `slot_type`; parity guarded). `services/purchase_units.py` (pure):
      `resolve_packs(required, options)` — 0 → None, 1 → ceil to a whole pack, several →
      recursive brute-force over small combos, key `(overage, pack_count, counts)`;
      `show_overage = overage > 0.5 × largest chosen pack`. `services/consolidation.py`
      (pure): `IngredientLine[]` + `{original: substitute}` → `ConsolidatedItem[]`; buckets
      each contribution by dimension (mass/volume/count/`unit:<x>`), AU-normalises volumes
      (`tsp` 5, `tbsp` **20**, `cup` 250 ml; `kg`/`L` ×1000), sums, then ceil-to-clean-step
      **upward** (25 at/above 100 g·ml, 5 below; ceil-to-whole for counts + free-text units);
      a *pure-cup* ingredient is shown back in cups 2-dp (honours the earlier explicit call);
      mass+volume mix → `needs_review` with both parts in `review_parts`; `NO_SCALE_UNITS` →
      `quantity=None`, `is_no_scale`; real qty + a "to taste" contribution → `also_to_taste`.
      Orchestrator `sessions_service.consolidate_session(db, id, *, overrides=None)`: scales
      each recipe slot via `scaling.py` (leftovers contribute nothing), merges stored default
      substitutions with session-only `overrides` (overrides win), runs `consolidate()`, then
      per item looks up `product_units` rows, normalises pack sizes to the item's base unit,
      calls `resolve_packs()`, and **upserts** `session_checklist_items` — computed fields
      refreshed, `have_it`/`add_to_list`/`already_on_anylist`/`anylist_item_id` **preserved**
      on surviving lines, gone lines deleted. `note` carries the review breakdown, `"to
      taste"`, `"(+ to taste)"`, or `"<n> <unit> spare"` (overage). `is_staple` set from the
      staples table. `POST /api/v1/sessions/{id}/consolidate` (`{"overrides":[…]}`, optional).
      `seed_data.py`: eggs (½ dozen + dozen), milk (1 L + 2 L), yoghurt (500 g + 1 kg) —
      **seed idempotency key changed to `(ingredient_name, purchase_label)`** so a second
      pack for an existing ingredient still seeds. 26 pure unit tests
      (`test_purchase_units.py` 9, `test_consolidation.py` 17) + 7 orchestrator service
      tests + 4 router smoke tests; full suite **255 pass**; migration parity green.
      **Live curl on a fresh scratch server** exercised: cross-recipe scale+sum → `1.0 kg`
      beef mince + `2 × 500g pack`; `2 tbsp + 100 ml soy sauce` → `250 ml` (merged via the
      20 ml tbsp); `100 g + 150 ml cream` → `needs_review` `"200 g + 300 ml"`; 13 eggs →
      `1 × dozen + 1 × half dozen` (overage 5, not shown, < half a dozen); `pinch` saffron →
      `to taste`, no number; no-pack passata → `400 g`; a `have_it=yes` line survived a
      re-consolidate with a recomputed quantity while a new line defaulted to `unknown`;
      `/diagnostics/recent-errors` clean. Headless-Edge confirmed the Settings `product_units`
      card lists the double rows sensibly (closes the 4.5-deferred check).
- [x] **Chunk 4.7 — Session UI.** **⚠️ Phase 3.9 M4 reworks the swap:** "Remember this
      substitution?" no longer creates a global auto-applying rule — it's a session-only
      override (kept), with an optional "save this swap" → `remembered_substitutions`
      quick-pick (no auto-apply). `consolidation.consolidate()` no longer resolves
      substitutions; the override resolves in `consolidate_session()`.
      `static/js/sessions.js` on `#/plan` (nav already has
      "Plan"), split by sub-feature if it passes ~350 lines. Create / resume a session, add
      recipes from the library, set servings + day, add a leftovers slot; ingredient review
      step with ad-hoc ingredient swap, "Remember this substitution?" prompt (yes → Chunk 4.5
      API; no → session-only override held client-side and passed into the consolidate call),
      quick-pick of existing substitutes; consolidated summary view with resolved purchase
      units, shown before the checklist. **Open item for this chunk's kickoff:** confirm the
      session-only-override transport — leaning toward a client-held list in the
      `consolidate` request payload, matching the "No → writes nothing to the DB" design.
      Done 2026-09-06 (commit `d00e2ae`). **Transport decision locked: client-held
      `overrides` list in the `POST /consolidate` payload** (nothing written on "no"). Split
      into two files per the size guideline: `static/js/sessions.js` (session list + the
      workspace — inline-editable label, per-slot servings 1–12 / day dropdowns, ↑/↓
      reorder via `PUT …/slots/order`, add-recipe library picker with search, add-leftovers,
      remove) and `static/js/session-review.js` (the review screen — an in-memory handoff
      like capture-review, not a route: consolidated list with pack breakdown + "need ~X" +
      staple/overage/review notes, per-line **Swap** with a free-text field, quick-pick
      buttons from `GET /settings/substitutions`, and the "Remember this?" `confirm()` →
      `POST /settings/substitutions` on yes / client-`overrides`-only on no). `router.js`
      `plan` stub replaced with a real route (`#/plan`, `#/plan/<id>`, `#/plan/new`);
      `api.js` gains the full `sessions.*` surface. `consolidation.consolidate()` now
      **follows a substitution chain** (`_resolve_through`, cycle-guarded) so a swap can key
      off the *displayed* (already-substituted) name — +2 unit tests. Full suite **257
      pass**. Headless-Edge/CDP end-to-end: new session → add 2 library recipes → bump one
      to 8 servings → add a leftovers day → Review → correct consolidated list (`beef mince
      1 × 500g pack · need ~500 g`, no-pack `bulgarian feta 400 g`, `eggs 1 × dozen + 1 ×
      half dozen · need ~15`, `olive oil 80 ml (staple)` via the 20 ml tbsp) → swap
      `bulgarian feta` → `regular feta` re-consolidates and the line changes; zero console
      errors.
- [x] **Phase 4 review** — re-check against [Data Model](../data-model.md#data-model) (`planning_sessions`,
      `session_recipes`, `session_checklist_items`, `remembered_substitutions`,
      `product_units`), [Scaling Logic](../scaling-and-consolidation.md#scaling-logic),
      [Ingredient Substitution](../ingredient-handling.md#ingredient-substitution),
      [Duplicate Recipe Prevention](../duplicate-recipe-prevention.md#duplicate-recipe-prevention),
      [Code Architecture](../code-architecture.md#code-architecture--maintainability), and
      [API Conventions](../code-architecture.md#api-conventions), per
      [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      **Done 2026-09-07, folded into the Phase 3.9 M-review** as planned — it was deliberately
      deferred so it wouldn't sign off the pre-M4 global `ingredient_substitutions` design
      that M4 removed. The combined re-check (Data Model, Scaling Logic, Ingredient
      Substitution, Duplicate Recipe Prevention, Code Architecture, API Conventions +
      Phase 3.9's own sections), its findings, and the carried-forward open items are recorded
      on the **M-review** line at the end of the Phase 3.9 chunk list above. Manual
      click-through: all 6 sections PASS (`Phase-4-Test-Plan.md`).

**Deliverable:** User can create a session, add recipes, scale them, substitute an ingredient
they don't want to buy, and see a consolidated shopping list with purchase units resolved.

