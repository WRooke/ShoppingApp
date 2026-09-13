# Duplicate Recipe Prevention

## Duplicate Recipe Prevention

**Status: in scope, Phase 4.** Designed 2026-09-06. The recipe library must not silently
accumulate multiple copies of the same recipe — whether re-added because the user forgot it
was already there, or captured a second time under a slightly different name. None of the
three entry paths (`create_recipe`, `create_recipe_from_capture`, and the URL/photo/manual
capture flows — see [Recipe Capture](./recipe-capture.md#recipe-capture--ai-extraction)) check for an existing
recipe today.

Distinct from [Ingredient Normalisation](./ingredient-handling.md#ingredient-normalisation) and
[Ingredient Substitution](./ingredient-handling.md#ingredient-substitution) above — those operate on *ingredient*
names within/across recipes. This operates on whole *recipes*, at save time.

### Why Phase 4, not Phase 3
Placed with the planning-engine work at Phase 4 kickoff (confirmed 2026-09-06), even though
capture (the main duplicate vector) is a Phase 3 feature. Reasons: it depends on the
`recipes.source_book` / `recipes.source_page` columns from
[Chunk 3.7b](./build-status/phase-3-recipe-capture.md#phase-3--recipe-capture-ai) for one of its match signals, so it can't land
before those; Phase 3's remaining scope is deliberately kept tight (one blocked live-API
chunk plus provenance); and "library hygiene at save time" sits naturally next to
consolidation and substitution. The cost is that duplicates added during Phase 3
verification / early use won't be caught until Phase 4 — accepted. When Phase 4 is chunked,
this becomes one of its checkbox chunks.

### Behaviour: warn-with-override, never a hard block (confirmed 2026-09-06)
Matches the "user reviews and confirms everything" philosophy used throughout this document.
A hard block on save would produce infuriating false positives (two different recipes can
legitimately share a name — "pancakes"). So every match *warns* and offers a way through:

- On save, the service runs a duplicate check. If it finds one or more candidate matches and
  the request did not carry `allow_duplicate=true`, it raises `PossibleDuplicateRecipeError`,
  translated centrally in `app/main.py` to a **409** with error code
  `POSSIBLE_DUPLICATE_RECIPE` and a structured `detail` listing each match (recipe id, name,
  source summary, which signal matched, and whether it is archived). Same
  raise-in-service / translate-in-main.py pattern as the existing `DuplicateStapleNameError`
  → 409, with a richer body and an override flag.
- The frontend catches the 409 and shows "You might already have this:" with each match as a
  link, plus **Open existing** and **Save anyway**. "Save anyway" re-submits the identical
  payload with `allow_duplicate=true`, which suppresses the check for that request only.
- **URL capture short-circuit.** On `POST /recipes/capture/url`, the `source_url` match is
  checked *before* calling Claude. An exact hit returns immediately with the existing
  recipe's id and no extraction call — this also avoids a needless real API call, consistent
  with [Security §0c](./security.md#0c-api-enable-switch--offline-development-highest-priority)'s
  minimise-real-calls intent. The UI offers "Open recipe #N" or "Capture again anyway".
- **Archived recipes are included in the check.** A match against a recipe the user
  previously archived is among the most useful catches. It is shown with **Restore existing**
  (clears `archived_at` via a small `unarchive_recipe()` + `POST /recipes/{id}/restore`)
  instead of "Open".

### Match signals (strongest / cheapest first)
1. **`source_url` exact, normalised** — lowercase host, drop fragment, strip a trailing
   slash, strip `utm_*` query params. Strong signal; checkable before extraction.
2. **`source_book` + `source_page` overlap** — same cookbook and an overlapping page
   reference. Depends on the Chunk 3.7b columns.
3. **Normalised `name` exact** — `strip().lower()` with internal whitespace collapsed.
4. **Fuzzy `name`** — conservative, stdlib only (`difflib` ratio and/or token-set Jaccard on
   lowercased word sets minus a tiny stopword list), high threshold. This is the signal that
   catches "same recipe, different name". Threshold is tuned during Phase 4 verification —
   start strict, loosen only if real near-dupes slip through. **No new dependency.**
5. **Ingredient-set overlap** — deliberately *not* in the Phase 4 build. Expensive (loads
   every recipe's ingredients) and the four signals above should cover the real cases.
   Parked as a [Deferred Decision](./deferred-decisions.md#deferred-decisions) — revisit only if near-dupes are
   still getting through after Phase 4.

### Layering (per [Code Architecture](./code-architecture.md#code-architecture--maintainability))
- **`services/recipes.py`** — `find_possible_duplicates(db, *, name, source_url=None,
  source_book=None, source_page=None, exclude_id=None) -> list[DuplicateMatch]`: DB reads
  only, no network, unit-testable, returns matches ranked by signal strength.
  `PossibleDuplicateRecipeError(matches)`. `allow_duplicate: bool = False` parameter on both
  `create_recipe` and `create_recipe_from_capture`. `unarchive_recipe(db, recipe_id)`.
- **`schemas/`** — `DuplicateMatch` response model; `allow_duplicate` field on `RecipeCreate`
  (`schemas/recipes.py`) and `CaptureConfirmRequest` (`schemas/capture.py`).
- **`routers/recipes.py`** — URL pre-check branch; `POST /recipes/{id}/restore`; optional
  `GET /api/v1/recipes/check-duplicate?name=…&source_url=…` so the review and manual-entry
  screens can warn live (on name-field blur) rather than only on a submit-and-bounce.
- **`app/main.py`** — `PossibleDuplicateRecipeError` → 409 / `POSSIBLE_DUPLICATE_RECIPE`.
- **Frontend** — `capture-review.js`, `recipe-form.js`, `api.js`: the warning panel, the
  Open / Restore / Save-anyway actions, and (if built) the live check on name blur.

### Open items for Phase 4 kickoff
- Final fuzzy-match threshold and whether token-set, `difflib` ratio, or both.
- Whether the live `check-duplicate` endpoint is worth building or the submit-time 409 is
  enough on its own.
- Ingredient-set overlap signal — still deferred (above).
- Relationship to the deferred **bulk ingredient rename/merge** item: a "these two really are
  the same recipe, merge them" action is a natural follow-on but is not part of this design —
  the flow here stops at "open / restore the existing one instead".

---

