# Build Status — Ingredient Unit Handling Chunks

### Build chunks
- [x] **Chunk 6 — this documentation pass.** Data Model entries, this section, Deferred
      Decisions + Decision Dialogue updates, Project Directory Structure entries. Done
      2026-09-12, before any code — the maintainer's explicit ask, so the full design is on
      record before implementation starts.
- [x] **Chunk 1 — `unit_synonyms`.** Migration, model, schema, service (CRUD + the
      pluralisation-strip helper + `synonym_map()`), router endpoints under
      `/api/v1/settings/unit-synonyms`, Settings card, seed data, tests.
      Done 2026-09-12. Migration `e7f2c9a4d6b8` (shared with Chunk 3, one table each, both
      brand-new so plain `create_table`). `strip_plural()` lives in `services/unit_synonyms.py`
      (same heuristic as `checklist.py`'s `_singularise()`, applied to unit strings); a check
      script against every real seed row + spot-check inputs (grams/kgs/mls/litres/
      teaspoons/tablespoons/tbsps/cloves/bunches/sprigs/cans) confirmed no dead/unreachable
      seed rows and every real-world spelling resolves correctly. One real gap the tests
      caught: `canonical_unit` is normalised lowercase the same as `alias_unit` (consistent
      with every other normalised field in the app) — an original seed entry ("l" -> "L")
      would have been rejected as a self-alias once case-folded, and was dead weight anyway
      (consolidation.py's volume-display branch already hardcodes "L"/"ml" regardless of
      input casing) — removed; the `liter`/`litre` -> `l` entries fixed to lowercase.
      14 service tests + 9 router tests; suite 447 pass. Headless-Edge verified: "Unit
      spellings" card renders 6 canonical groups (g/kg/l/ml/tbsp/tsp) from the real seed,
      zero console errors.
- [x] **Chunk 2 — wire Layer A into consolidation.** Resolve unit synonyms in
      `_scaled_lines()`, same layer as ingredient alias resolution, applied to every line's
      unit before `consolidation.consolidate()` buckets it.
      Done 2026-09-12. Applied *earlier* than originally described — right after
      `_effective_source()` returns the raw (quantity, unit), before scaling and before any
      substitution/override/alias matching runs — not merely as a final pass alongside
      alias resolution. Reason found while implementing: an alias's or session override's own
      `alias_unit`/`original_unit` is compared against the line's unit for its equivalence-
      pair match; canonicalising the line's unit only *after* that comparison would make a
      recipe spelling a unit differently ("tablespoons" vs a configured "tbsp") spuriously
      fail to match. Canonicalising first means every downstream comparison already sees a
      consistent spelling. 2 new integration tests (`test_sessions.py`): "gram"+"g" flour
      across two recipes merges instead of `needs_review`; a `clove`/`cloves` plural mismatch
      reconciles via the tableless strip rule alone (no synonym row needed). Verified live
      against a scratch server + headless Edge: 200 g + 300 "gram" flour merged to `500 g`,
      confirmed in both the API response and the rendered ingredient-review row.
- [x] **Chunk 3 — `coarse_ingredients`.** Migration, model, schema, service, router endpoints
      under `/api/v1/settings/coarse-ingredients`, Settings card, seed data, tests.
      Done 2026-09-12 (migration `e7f2c9a4d6b8`, shared with Chunk 1). CRUD only in this
      chunk — the counting/`packs_needed` resolution logic is Chunk 4, in
      `session_consolidation.py`, not here. Seeded parsley/coriander/mint/basil, all
      `purchase_label="bunch"`, `recipes_per_pack=3`. 10 service tests + 8 router tests;
      suite 447 pass. Headless-Edge verified: "Coarse ingredients" card lists all 4 seeded
      rows with editable label/recipes-per-pack fields, zero console errors.
- [x] **Chunk 4 — wire Layer D into consolidation.** Partition lines into coarse/normal in
      the orchestrator; build coarse `ConsolidatedItem`s by hand; merge into the upsert loop
      with its own display-string branch, bypassing pack resolution.
      Done 2026-09-12. Three new fields on `ConsolidatedItem` (`is_coarse` /
      `coarse_packs_needed` / `coarse_purchase_label`) — `consolidate()`'s own logic is
      completely untouched, only ever populated by `session_consolidation.py._coarse_items()`
      constructing items by hand for the lines it partitions out before `consolidate()` is
      even called. `recipe_breakdown` is still built via the same `consolidation._recipe_breakdown()`
      helper `consolidate()` itself uses, confirming it really is independent of how the total
      is computed. Real frontend bug found and fixed along the way:
      `session-review.js`'s `renderItemRow()` unconditionally appended
      `" · need ~" + fmtQty(item)` after `display_qty`, which for a coarse item (display_qty
      set, total_quantity always null by design) rendered a dangling "1 × bunch · need ~"
      with nothing after it — `checklist.js`'s equivalent already guarded this correctly,
      `session-review.js` didn't; now both do. 6 new integration tests covering: mass+volume
      contributions that would normally be `needs_review` instead resolving to a pack count;
      the count scaling with the number of contributing recipes (`ceil(4/3) = 2` packs); no
      `purchase_label` configured showing plain "needed" with no count; the recipe breakdown
      still showing each contributor's own raw, un-coarsened quantity and unit. Suite 453
      pass. Verified live end-to-end (curl + headless Edge): parsley in "10 g" + "1 tbsp"
      across two recipes — which would otherwise flag `needs_review` — instead shows
      `1 × bunch` with the breakdown correctly expanding to each recipe's own contribution,
      zero console errors.
- [x] **Chunk 5 — Layers B+C, the known-units endpoint + frontend.** New
      `GET /api/v1/recipes/ingredient-units` endpoint; quick-picks + the duplicate-unit
      nudge wired into `recipe-form.js`, `recipe-edit.js`, `capture-review.js`'s unit inputs.
      Done 2026-09-12. `known_units_for_ingredient()` (Layer B) lives in
      `services/unit_synonyms.py`, not `services/recipes.py` — despite querying
      `recipe_ingredients`, it's fundamentally a "what units..." question and needs
      `resolve_unit()` to de-duplicate its own results, and `recipes.py` was already at its
      file-size guideline. A plain `GROUP BY unit` query, pooled across an ingredient's
      `ingredient_aliases` group (typing "vegetable oil" also surfaces units seen under
      "canola oil"), most-frequent first, zero new table. Layer C (the duplicate-unit nudge)
      is entirely client-side — `static/js/unit-hints.js` re-implements the exact same
      `strip_plural()` heuristic in JS (so the duplicate check agrees with what the backend
      will actually resolve to) plus a small from-scratch Levenshtein distance for genuine
      typos ("clve" → suggest "clove"), threshold tight for short units (1 char) and looser
      for longer ones (2 chars) — tuned by hand-testing rather than reusing Duplicate Recipe
      Prevention's name-matching thresholds unchanged, per that chunk's own kickoff note.
      One shared module (`UnitHints.attach(nameInput, unitInput)`, same precedent as
      `dup-warn.js`) wired into all three ingredient-row builders (including
      `recipe-edit.js`'s two separate ones — existing rows and the add-new row). 12 new
      backend tests (6 service, 2 router, plus the pooling/frequency-order/empty/unitless
      cases). Suite 461 pass. Verified live end-to-end (headless Edge): typing "garlic"
      surfaces a "clove" quick-pick from a real seeded recipe; typing the exact plural
      "cloves" correctly shows no nudge (already reconciled by the tableless strip rule, no
      table entry needed); typing a genuine typo "clve" surfaces "did you mean 'clove'?",
      and clicking "use it" correctly fills the unit field and dismisses the nudge — zero
      console errors throughout.
- [x] **Chunk 7 — Admin reduction: auto-learn unit spellings.** Documented above, same day,
      before any code, per the maintainer's explicit ask.
      Done 2026-09-12. `services/ai_extraction.py > classify_units()` — the 4th Gemini call,
      same §0c gates (`AI_EXTRACTION_ENABLED`/`AI_EXTRACTION_FAKE_MODE`) and
      allow-list-validate-the-output discipline as `suggest_sections()`, but — uniquely
      among the four — does **not** wrap its input in the §0a untrusted-content delimiter,
      since it's classifying the household's own typed unit strings, not scraped/
      photographed content (module docstring spells this out explicitly so it isn't
      mistaken for an oversight later). `services/unit_synonyms.py > learn_new_units()` —
      the "genuinely new" gate (doesn't already resolve to a standard unit, AND has never
      appeared as any `recipe_ingredients.unit` value before, excluding the row(s) just
      saved) + auto-write via the existing `create_synonym()`; deferred-imports
      `ai_extraction` so an ordinary save with nothing novel never pays for that import;
      catches `AiExtractionDisabledError` (the expected default — no WARNING/traceback),
      `AiExtractionError` (already logged in detail upstream), and a belt-and-braces bare
      `Exception` — never blocks or fails the caller's save. Wired into all 4 of
      `services/recipes.py`'s ingredient-save paths (`create_recipe`,
      `create_recipe_from_capture`, `add_ingredient`, `update_ingredient` — the last only
      when `unit` is actually part of the change). 6 new `UNIT_SYNONYM_SEEDS` rows
      (`gramme`/`kilogramme`/`kilo`/`tspn`/`tbspn`/`ltr`), each verified via a throwaway
      `strip_plural()` check script to confirm their plurals cascade for free, same as
      Chunk 1's own check. 18 new tests (7 in `test_ai_extraction.py`, 11 in
      `test_unit_synonyms.py`, incl. an end-to-end `create_recipe` test confirming the
      just-saved ingredient row is correctly excluded from its own "already used" check).
      Suite 479 pass; no migration (writes through the existing `unit_synonyms` table and
      `create_synonym()`, no schema change). Verified live against a scratch server (fake
      mode): a recipe saved with `"flour" 200 "grms"` auto-added `grm -> g` to
      `unit_synonyms` (confirmed via `GET /settings/unit-synonyms`); a genuinely novel
      discrete unit (`"wug"`, standing in for a real thing like `clove`/`bunch`, not in the
      fake fixture's answer set) correctly got **no** row and no error; re-using `"wug"` in
      a second recipe produced **zero** further classification calls (confirmed via the
      server log's `AI classify_units` line count staying at 1 across both saves) — the
      "ask once, never again" behaviour working exactly as designed.

**Chunks 1–7 complete 2026-09-12.** Status line above and the `unit_synonyms` /
`coarse_ingredients` Data Model entries updated from "designed, build starting" to built —
see those sections for the finished design. Chunk 7 (admin reduction) was raised, designed,
and built the same day, documented ahead of its own build per the maintainer's ask.

---

