# Build Status — Phase 2: Recipe Library

### Phase 2 — Recipe Library

- [x] **Chunk 2.1 — Data layer.** `schemas/recipes.py` (Pydantic request/response models per
      [Code Architecture](../code-architecture.md#code-architecture--maintainability)); `services/recipes.py` covering
      recipe CRUD (delete is soft: sets `archived_at`) and nested `recipe_ingredients` CRUD;
      `seed_data.py` populated with the [Staples Starter List](../data-model.md#staples-starter-list) and
      [Pre-seeded Product Units](../data-model.md#pre-seeded-product-units), run on first startup.
      Verified 2026-09-05: 20 new unit tests (`tests/services/test_recipes.py`, in-memory
      SQLite, no HTTP) all pass; real dev server started twice against `data/mealplanner.db` —
      first run seeded 22 product units + 19 staples (log line confirmed:
      `app.seed_data: Reference data seed: {'product_units_added': 22, 'staples_added': 19}`),
      second run (restart) added zero more, confirming the seed is idempotent as designed.
- [x] **Chunk 2.2 — Recipe & ingredient API.** `routers/recipes.py`: recipe CRUD endpoints plus
      nested ingredient CRUD endpoints, `{"ok": ...}` envelope, `?limit=`/`?offset=` pagination
      on list endpoints (see [API Conventions](../code-architecture.md#api-conventions)). Add `pytest` to
      `requirements.txt` (first phase needing it — see
      [Code Architecture > Tests](../code-architecture.md#code-architecture--maintainability)); unit tests for
      `services/recipes.py` (no DB/network) and a smoke test (happy path + one error path) for
      the router.
      Verified 2026-09-05: `pytest` was already in `requirements.txt` (added ahead of Phase 2 at
      Phase 1). `RecipeNotFoundError`/`IngredientNotFoundError` → 404 translation added as
      dedicated FastAPI exception handlers in `main.py` (keeps routers free of try/except, same
      pattern as the existing global handlers). 15 new router smoke tests added (35 total in
      suite, all pass). Manually exercised every endpoint against the real dev server/DB:
      create, list, get, get-404, patch rating, add/update/delete ingredient,
      delete-ingredient-404, archive (and confirmed it disappears from the default list but
      still shows with `include_archived=true`) — all returned the expected envelope/status,
      diagnostics `/recent-errors` stayed empty throughout, and the manually-created test
      recipe was removed from `data/mealplanner.db` afterwards.
- [x] **Chunk 2.3 — Recipe library UI.** Browse list, search by name, recipe detail view;
      default views filter `archived_at IS NULL`.
      Verified 2026-09-05 with real headless-browser screenshots (Edge `--headless
      --screenshot`, no chromium-cli/Playwright available in this environment — see
      `router.js`/`recipes.js`/`api.js` changes) against the real dev server: browse list
      showed both seeded test recipes with servings/cuisine/protein; search endpoint
      confirmed to filter correctly; both recipe detail views rendered ingredients/notes
      correctly; a recipe-not-found URL showed the friendly "couldn't be found" copy
      (404 path). `router.js` extended to parse an optional `#/recipes/<id>` path segment
      and pass it to `mount()` — it remains the only file that parses `location.hash`,
      per Code Architecture. Along the way this caught a real Phase 1 bug (not
      Phase-2-introduced): `GET /favicon.ico` was throwing `h11.LocalProtocolError` on
      every single page load because `JSONResponse(status_code=204, content=None)`
      serialises a 4-byte `b"null"` body against a declared `Content-Length: 0`. Fixed in
      `app/main.py` (plain `Response(status_code=204)`) and confirmed
      `/api/v1/diagnostics/recent-errors` goes from spammed to clean.
- [x] **Chunk 2.4 — Recipe edit & manual entry UI.** Inline edit of ingredients (name, qty,
      unit, preparation); recipe-level fields `rating`, `notes`, `cuisine`, `protein`; manual
      recipe entry form (new recipe from scratch, no capture involved).
      Flag carried from Chunk 2.1: `times_made`/`last_made_at` ("mark cooked") were NOT built
      here — the Data Model text says Phase 2 onward, but this chunk's own bullet list only
      names `rating`/`notes`/`cuisine`/`protein`, and there's no natural "cooked" event before
      Phase 4 sessions exist. **Resolved 2026-09-06 at Phase 4 kickoff — deferred to Phase 6**
      (a real "cooked" event is post-push, Phase 5+; see [Deferred Decisions](../deferred-decisions.md#deferred-decisions)).
      Verified 2026-09-05 by scripting a real headless-Chromium session over the DevTools
      Protocol (no chromium-cli/Playwright/node in this environment — wrote a small
      scratch-only CDP driver, not part of the app) against the real dev server: filled and
      submitted the manual entry form (2 ingredients, one added via "+ Add another
      ingredient") and confirmed the created recipe's detail page; entered edit mode and
      saved recipe-level field changes (base_servings, rating); added an ingredient and
      edited another's quantity, confirming the UI stays in edit mode after each ingredient
      action rather than bouncing to view mode; deleted one ingredient; deleted (archived)
      the whole recipe and confirmed it drops out of the default list. Cross-checked every
      step against `GET /api/v1/recipes/1` directly rather than trusting the DOM alone, and
      `/api/v1/diagnostics/recent-errors` stayed empty throughout. No console errors in any
      run. Test data and the throwaway `websocket-client` verification dependency were
      removed afterwards; it is not in `requirements.txt`.
- [x] **Chunk 2.5 — Settings UI.** View/add/edit/delete entries in `staples` and
      `product_units` — this is what makes the seeded data from Chunk 2.1 actually editable,
      per the Phase 2 deliverable below.
      Built `app/schemas/settings.py` + `app/services/settings.py` (CRUD for both tables,
      name/ingredient_name normalised lowercase to match `recipe_ingredients.name`, duplicate
      names caught as a 409 rather than a raw `IntegrityError`) + `app/routers/settings.py`,
      following the exact layering already established by recipes in Chunk 2.1/2.2. `is_preseeded`
      is accepted from the DB but never settable through the API — every user-added row is
      `is_preseeded=false`. Frontend: `static/js/settings.js`, wired into `router.js`/`index.html`,
      reusing the ingredient-edit-row list/add-row pattern from `recipes.js`.
      Verified 2026-09-05: picked up from a prior session that broke down mid-chunk — its
      unstaged, already-correct work (finishing the PII redaction pass and the staples-list
      correction) was reviewed, found complete, and committed first (see commit history) before
      starting this chunk's own code. 20 new unit tests (`tests/services/test_settings.py`) +
      21 new router smoke tests (`tests/routers/test_settings.py`), 66 total in the suite, all
      pass. Manually exercised every endpoint against the real dev server/DB: create staple,
      duplicate-name 409, update, delete, delete-404; create product unit, duplicate-name 409,
      reject non-positive `purchase_qty` (422), update, delete, delete-404 — all returned the
      expected envelope/status and `/api/v1/diagnostics/recent-errors` stayed empty throughout.
      Took a real headless-Edge screenshot of `#/settings` against the running dev server and
      confirmed both cards render with the real seeded data (5 staples, 22 product units) and
      the nav bar highlights Settings correctly. Confirmed the real dev DB already matched the
      corrected 5-item staples list (see the PII/staples-correction commit) — no leftover
      over-seeded rows needed cleaning up. Test rows created during verification were deleted
      through the API itself (the feature being verified), leaving the DB exactly as it was
      before.
- [x] **Phase 2 review** — re-check this phase's work against the Data Model (`recipes`,
      `recipe_ingredients`, `product_units`, `staples`), API Conventions, and Code Architecture
      sections, per [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      **Also flag for decision:** Git branching strategy — should we introduce `production` /
      `develop` branches now to prevent breaking the working app, or defer this? (See
      [Deferred Decisions](../deferred-decisions.md#deferred-decisions) for full details.)
      Verified 2026-09-05: `recipes`/`recipe_ingredients`/`product_units`/`staples` ORM models
      match the Data Model section field-for-field; every router response uses the
      `{"ok": ...}` envelope with pagination (`limit`/`offset`) on both list endpoints;
      `SCREAMING_SNAKE_CASE` error codes (`RECIPE_NOT_FOUND`, `DUPLICATE_STAPLE_NAME`, etc.)
      are translated centrally in `app/main.py`'s exception handlers, no raw `HTTPException`
      anywhere in `routers/`/`services/`; `services/` has zero `fastapi` imports; frontend
      feature files never call `fetch` directly (only `api.js` does) and never reach into
      another feature's DOM/state; `router.js` is the only file parsing `location.hash`. Full
      suite re-run clean (66/66) and the real dev server confirmed healthy with an empty
      `/api/v1/diagnostics/recent-errors` throughout.
      Two gaps found and fixed (not just noted): `static/js/recipes.js` had grown to 461
      lines, past the ~300–400 line guideline in
      [Code Architecture & Maintainability](../code-architecture.md#code-architecture--maintainability) — split
      edit-mode + ingredient-row rendering out into a new `static/js/recipe-edit.js`
      (`recipes.js` now 218 lines), following the same precedent as the existing
      `recipe-form.js` split; and `recipes.js`/`recipe-form.js` were setting
      `location.hash` directly to navigate after save/delete, a small breach of "router.js
      is the only file that knows hash routes exist" — added a `Router.navigate(key, param)`
      helper to `router.js` and switched both call sites to it. Verified live via a headless
      Edge + Chrome DevTools Protocol session against the real dev server (temporary
      `websocket-client` dependency, removed afterwards, same as the Chunk 2.4 precedent):
      created a scratch recipe, opened it, clicked Edit, added an ingredient, saved back to
      view mode, confirmed the result via a direct API call, then archived the scratch
      recipe to clean up — zero console errors throughout. Two smaller gaps found via user
      testing before this review (Home tab content, Settings scroll-reset-on-save) were
      already correctly logged as open items rather than fixed or dropped — left as-is here,
      see [Deferred Decisions](../deferred-decisions.md#deferred-decisions).
      Git branching decision made and implemented (not deferred) — see
      [Deferred Decisions > Git branching strategy](../deferred-decisions.md#deferred-decisions) for what was
      decided, built, and verified, and `DEPLOY.md` for the resulting workflow.

**Deliverable:** User can manually add, view, and edit recipes. Staples and product units
table is pre-populated and editable via Settings page.

