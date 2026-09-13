# Build Status — Phase 3.9: AI Provider Migration

### Phase 3.9 — AI Provider Migration (Anthropic Claude → Google Gemini) + substitution merge

**Added 2026-09-06.** Full spec, rationale and all resolved decisions:
[AI Provider Migration](../recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39).
Runs on top of the completed Phase 4 chunks 4.1–4.4 / 4.6; **M4 removes** the substitution
parts of Chunks 4.5 / 4.6 / 4.7 and replaces them with the merged design. The Phase 4 review
is folded into this phase's M-review.

- [ ] **M0 — Decisions + CLAUDE.md fold-in.** Done 2026-09-06 (this edit). No code.
- [x] **M1 — Config + `google-genai` SDK + fake-mode skeleton.** Done 2026-09-06.
      `requirements.txt`: `anthropic==1.4.0` out, `google-genai==2.22.0` in (also uninstalled
      from the venv). `config.py` + `.env.example`: `ANTHROPIC_API_KEY`→`GEMINI_API_KEY`,
      `CLAUDE_API_ENABLED`→`AI_EXTRACTION_ENABLED`, `CLAUDE_API_FAKE_MODE`→
      `AI_EXTRACTION_FAKE_MODE`; `settings.anthropic_configured`→`gemini_configured`; summary
      keys renamed. `services/claude_client.py` → `services/ai_extraction.py`: `genai.Client`
      + `types.GenerateContentConfig(response_mime_type="application/json",
      response_schema=_GeminiExtraction, system_instruction=…)`, `Part.from_text` /
      `Part.from_bytes`; `usage_metadata.prompt_token_count` / `candidates_token_count`.
      `ClaudeExtractionError`→`AiExtractionError`, `ClaudeApiDisabledError`→
      `AiExtractionDisabledError`; `main.py` error code `CLAUDE_API_DISABLED`→
      `AI_EXTRACTION_DISABLED`. `MODEL_ID = "gemini-2.5-flash"` (fallback chain is M3). §0c
      gates + §0a hardening (delimiter, `MAX_INPUT_TEXT_CHARS`, `suggested_section`
      allow-list) + fake fixtures carried over **verbatim**. `capture_url.py` /
      `capture_photo.py` / `routers/recipes.py` / `routers/diagnostics.py` call-site renames;
      diagnostics still exposes the `claude_api` block + spend fields (M5 replaces it).
      `api_usage._PRICING_USD_PER_MTOK` gains the two Gemini models at $0 so `log_api_usage()`
      keeps working until M5. `tests/services/test_claude_client.py` →
      `test_ai_extraction.py` (20 tests, `genai.Client` mocked); capture / diagnostics /
      recipe-capture test refs renamed. Full suite **257 pass**, still fully offline
      (fake mode + mocks, no key).
- [x] **M2 — Split into 3 per-task calls.** Done 2026-09-06. `services/ai_extraction.py`:
      `extract_recipe()` (call 1 — ingredients + cuisine/protein, **no** section suggestion),
      `flag_substitutions()` (call 2 — per-recipe substitution candidates), `suggest_sections()`
      (call 3 — per-ingredient section, allow-list validated), and `capture_recipe()` — the
      orchestrator that runs all three and merges sections + flags into `ExtractionResult`.
      Call 1 failure propagates; **calls 2 & 3 are enrichment** — an `AiExtractionError` from
      either is logged and swallowed (recipe still usable; M3 turns a swallowed *quota*
      failure into a queued retry). Each call: own system prompt (section suggestion left the
      extraction prompt), own `response_schema`, own fake fixture path
      (`_FAKE_SUBSTITUTION_FLAGS`, `_FAKE_SECTION_MAP`); shared `_call_gemini()` does
      client + config + error-wrap + usage-log. `schemas/capture.py`: `CaptureResult` gains
      `substitution_flags: list[SubstitutionFlagOut]` (review UI ignores it until M4).
      `capture_url` / `capture_photo` call `capture_recipe()`.
      `tests/services/test_ai_extraction.py` rewritten (23 tests). Full suite **260 pass**,
      offline; fake-mode 3-call orchestration verified against a scratch server.
- [x] **M3 — Fallback chain + `capture_queue`.** Done 2026-09-06.
      `ai_extraction._call_gemini` iterates `(gemini-2.5-flash, gemini-2.5-flash-lite)`: a
      `429` on one → try the next; `429` on both → `AiQuotaExhaustedError` (subclass of
      `AiExtractionError`). Non-quota errors don't fall back. Usage logged against the model
      that answered. Migration `285e886712e0` adds `capture_queue`; `models/queue.py`
      `CaptureQueueItem`. `services/capture_queue.py`: `enqueue` / `due_items` /
      `record_attempt` / `remove` / `run_once` — `run_once` drives `extract_url` /
      `extract_photo` end-to-end (a successful retry **auto-saves** the recipe with a
      placeholder name — user renames/reviews after); `flag_substitutions` /
      `suggest_sections` enrichment tasks are left for M4/M6. `app.main` lifespan runs an
      hourly `asyncio` poll loop (`POLL_INTERVAL_SECONDS=3600`), cancelled on shutdown.
      `capture_photo` split `store_image()` + `extract_stored()` so the endpoint keeps the
      filename when the AI call queues. `capture/url` + `/photo` catch `AiQuotaExhaustedError`
      → enqueue + return `{"ok": true, "data": {"queued": true, …}}`. +10 tests; full suite
      **270 pass**; migration parity green.
- [x] **M4 — Substitution redesign (the merge).** Done 2026-09-06 (commit `cb9ef89`).
      Migration `173367a2aab2`: `recipe_ingredients` += `resolved_ingredient` /
      `substitution_note`; `ingredient_substitutions` → `remembered_substitutions`
      (`is_default` **dropped**, `note` / `last_used_at` added). `services/substitutions.py`
      reworked — no default logic; `create` / `update` (name + note) / `delete` / `list`
      (by original, then `last_used_at`) / `quick_picks_for()` / `touch()`;
      `get_default_substitution_map()` **removed**. `consolidation.consolidate()` is **pure**
      again — no `substitution_map`; it groups by the name it's given.
      `sessions.consolidate_session()`: `_scaled_lines` resolves the effective name per
      ingredient (`resolved_ingredient` → session-only override) **before** the pure
      `consolidate()`. `recipes.py` create / from-capture / add / update-ingredient pass
      `resolved_ingredient` (normalised) + `substitution_note`; from-capture calls
      `substitutions.touch()` for confirmed swaps. Schemas: `RecipeIngredient*` +
      `CaptureIngredientConfirm` gain the two fields; `RememberedSubstitution*` replace
      `IngredientSubstitution*`. Frontend: `settings-substitutions.js` → "Saved ingredient
      swaps" (no default toggle, note per row); new `static/js/ingredient-swap.js`
      (per-ingredient collapsed swap control — AI-flag pre-fill + saved-swap quick-picks +
      note + "save this swap"); `capture-review.js` wires it per row + POSTs a remembered
      row on a ticked swap; `recipe-edit.js` gets `resolved_ingredient`/note inputs per row;
      `recipes.js` detail shows "→ using X (note)"; `session-review.js` "remember" prompt
      reworded (quick-pick, not auto-apply). Tests reworked; full suite **267 pass**;
      migration parity green; headless + curl verified end-to-end.
- [x] **M5 — Diagnostics rework.** Done 2026-09-06 (commit `9811036`). Migration
      `b6e557ca6088` drops `api_usage` + `api_usage_resets`, creates `ai_call_log` (task /
      model / outcome `success|quota|error` / nullable token counts / `error_detail` /
      `context_id`). `services/api_usage.py` → `services/ai_call_log.py` (all cost math
      removed): `log_ai_call`, `today_counts_by_model` (since local midnight),
      `recent_calls`, `last_success_at`, `task_for`. `ai_extraction._call_gemini` logs
      **every** outcome — a `quota` row per model on 429, an `error` row with detail
      otherwise, a `success` row (tokens, model that answered) on success.
      `routers/diagnostics.py`: `claude_api` block → `ai_extraction`
      (`today_by_model` / `recent_calls` / `last_success` / `dashboard_url`); `POST
      /reset-spend` removed. `static/js/diagnostics.js`: quota-by-model line + recent-attempt
      mini-log + AI Studio link; reset-spend button + `api.diagnostics.resetSpend` gone.
      Tests reworked (`test_ai_call_log.py`); full suite **262 pass**; migration parity green;
      diagnostics page headless-verified.
- [x] **M6 — "Pending AI processing" badge.** Done 2026-09-06 (commit `396af2f`). Migration
      `15b1aab757ac`: `recipes.ai_tasks_pending` (nullable TEXT, JSON array; NULL/`[]` =
      nothing); `Recipe.ai_pending_tasks` property parses it; `RecipeListItem`/`RecipeRead`
      expose it. `capture_recipe` reports `pending_tasks` — a swallowed `suggest_sections`
      failure → `["suggest_sections"]` (a failed `flag_substitutions` is **not** tracked —
      interactive-only, no post-capture retry). `capture_queue._process_extract` writes the
      pending list + enqueues a `suggest_sections` follow-up; `_process_suggest_sections`
      retries for the saved recipe → tags `product_sections` + clears the flag; orphan /
      `flag_substitutions` tasks are dropped. `routers/diagnostics.py` `ai_extraction` block
      gains a `queue` `{depth, items[]}` summary. Frontend: `recipes.js` badge in list +
      detail; `diagnostics.js` "Capture queue: N item(s)" line. +tests; full suite **267
      pass**; migration parity green; badge headless-verified.
- [x] **M7 — Live Gemini verification.** Done 2026-09-07 with the maintainer's explicit
      in-conversation go-ahead (test recipe:
      `recipetineats.com/satay-chicken-legs-with-peanut-sauce`). One real end-to-end URL
      capture against the real dev DB: all three Gemini calls
      (`extract` 5716/1007 tok, `suggest_sections` 235/222, `flag_substitutions` 308/56)
      returned `success`; structured output parsed against `_GExtraction` /
      `_GSections` / `_GFlags` first time, no parser tweak needed; 15 ingredients extracted
      faithfully (cuisine `thai`, protein `chicken`), 11 `product_sections` rows written
      `source='ai_suggested'`, 1 substitution flag (`dark soy sauce` → regular soy sauce).
      `ai_call_log` has the `success` rows; `/diagnostics/status` → `ai_extraction.state:
      green`, `last_success` populated, `queue` empty. Recipe **kept** (id 6, not archived).
      **Model-ID fix folded in:** the spec's pinned `gemini-2.5-flash` was retired by Google
      between M0 and M7 (`404` "no longer available to new users") — switched primary +
      fallback to the floating `gemini-flash-latest` / `gemini-flash-lite-latest` aliases at
      the maintainer's direction. See the note under
      [Provider & model selection](../recipe-capture.md#provider--model-selection). `429` handling itself is
      still covered only by unit tests (`test_ai_extraction.py` fallback-chain tests) — the
      live call did not hit quota. Free-tier-data-usage deferred decision still open — carry
      to the M-review.
- [x] **M8 — Substitution quantity/unit transform.** Added 2026-09-07 from a planning
      session — a substitution can change the *amount and unit*, not just the name
      ("2 whole corn cobs" → "2 cans of corn", "500 g fresh spinach" → "250 g frozen"). No
      real API involvement — build/verify entirely offline; runs before the M-review so the
      review signs off the finished shape.
      **Done 2026-09-07 (commit — this).** Migration `c199ab55bf1e` (batch `add_column`, all
      six columns nullable / no server default — `tests/test_migrations.py` parity held).
      `RecipeIngredient` += `resolved_quantity`/`resolved_unit`; `RememberedSubstitution` +=
      the four pair columns. Schemas: a shared `_validate_resolved_transform`
      (`schemas/recipes.py`) enforces both-or-neither + `resolved_ingredient`-required +
      positive on the recipe-level pair; a shared `validate_equivalence_pair`
      (`schemas/substitutions.py`, imported by `schemas/sessions.py`) enforces all-four-or-none
      + positive on the library / `SessionOverride` pair. `services/substitutions.py` carries
      + unit-normalises the pair (create + update, incl. clear). `services/recipes.py`
      `_resolved_transform` gates the pair on a name swap on both create paths + `add_ingredient`,
      and `update_ingredient` drops it when the swap is cleared. `services/sessions.py`:
      `_effective_source` feeds `(resolved_quantity, resolved_unit)` to `scaling.py` when set;
      `_apply_session_override` renames always, applies the ratio to the *scaled* quantity
      only when `original_unit` matches the line's unit and the line isn't "to taste";
      `override_map` is now name→`SessionOverride`. `consolidation.consolidate()` unchanged
      (docstring only — it receives finished lines). Frontend: `ingredient-swap.js`
      (amount+unit inputs, live preview, quick-pick ratio pre-fill), `capture-review.js`
      (threads the pair through + saves it as an equivalence pair when "save this swap" is
      ticked and the line has a unit), `recipe-edit.js` (swap amount/unit inputs),
      `settings-substitutions.js` (`pairInputs()` — the "N unit ≈ M unit" row, add + edit +
      clear), `session-review.js` (ratio inputs on the ad-hoc swap form, override + "remember"
      carry the pair, `knownSubs` holds full rows), `recipes.js` detail ("→ using 2 can
      canned corn"). `api.js` unchanged — the extra fields pass through opaquely. +16 tests
      (`test_substitutions.py`, `test_sessions.py` orchestrator: recipe-level transform,
      scales up/down + ceils, merges with a plain same-name line, session-override ratio,
      unit-mismatch → name-only, "to taste" skip; `test_recipes.py` clear-on-revert;
      `test_settings.py` router). Full suite **293 pass**; migration parity green;
      headless-Edge + curl verified end-to-end offline (fake mode, no live call).
      Full design folded into
      [Data Model](../data-model.md#recipe_ingredients) (`recipe_ingredients`, `remembered_substitutions`),
      [AI Provider Migration > Ingredient Substitution Flagging](../ingredient-handling.md#ingredient-substitution-flagging--the-merged-spec),
      [Ingredient Substitution](../ingredient-handling.md#ingredient-substitution), and
      [Scaling Logic > Consolidation across recipes](../scaling-and-consolidation.md#consolidation-across-recipes). Decided
      at planning: **(a)** recipe-level stores the *absolute* (`resolved_quantity` /
      `resolved_unit`), library stores an *equivalence pair* (`original_qty`/`original_unit`/
      `substitute_qty`/`substitute_unit`) that pre-fills it; **(b)** the AI `flag_substitutions`
      call is *not* extended — user types the ratio; **(c)** its own chunk, before M-review.
      - **Migration** — `recipe_ingredients` += `resolved_quantity REAL NULL` /
        `resolved_unit TEXT NULL`; `remembered_substitutions` += the four pair columns
        (all `NULL`). SQLite batch; `tests/test_migrations.py` parity held.
      - **Models / schemas** — new fields on `RecipeIngredient*`, `RememberedSubstitution*`,
        `CaptureIngredientConfirm`, `SessionOverride`. Validators: both-or-neither on each
        pair; recipe-level qty/unit only valid with `resolved_ingredient` set;
        `original_qty` / `original_unit` require a positive qty.
      - **`services/sessions.py`** (`_scaled_lines`) — when `resolved_ingredient` set **and**
        `resolved_quantity` not NULL, feed `(resolved_quantity, resolved_unit)` to
        `scaling.py` instead of `(quantity, unit)`. Session-override pair applied to the
        *scaled* quantity, only where `original_unit` matches the line's unit (else
        name-only for that line). Transform skipped when the effective source unit is a
        `NO_SCALE_UNITS` value. `override_map` becomes name → small object, not name → name.
      - **`services/consolidation.py`** — no logic change (it receives finished lines);
        comment only.
      - **`services/substitutions.py`** — carry + validate the pair; guard divide-by-zero.
      - **`services/recipes.py`** — passthrough on both create paths + ingredient add/update;
        clearing `resolved_ingredient` nulls `resolved_quantity`/`resolved_unit`.
      - **`services/ai_extraction.py`** — untouched (decision (b)).
      - **Frontend** — `ingredient-swap.js` gets amount + unit inputs and a live preview
        ("4 cob → ~4 can"); quick-pick fills the ratio and computes the pre-fill.
        `capture-review.js` / `recipe-edit.js` / `settings-substitutions.js` (show/edit
        "2 cob ≈ 2 can" per row) / `session-review.js` / `api.js` thread it through.
      - **Known limitation (documented, not solved):** a line resolved to a new free-text
        unit ("6 can") gets no `product_units` pack breakdown unless a matching-unit pack row
        is seeded — no cross-unit pack matching.
      - **Tests** — `test_substitutions.py`, `test_sessions.py` (orchestrator: cob→can
        transform, scaled up/down, "to taste" skip, session-override ratio, unit mismatch
        fallback), `test_recipes.py` (clear-on-revert), router smoke tests, migration parity.
      - **Verify:** headless + curl end-to-end, offline (fake mode). No live call.
- [x] **M-review** — full re-check of Phase 3.9 **and** the deferred Phase 4 review, together,
      per [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      **Done 2026-09-07.** Full suite **293 pass**; `alembic heads` == `alembic current` on the
      dev DB (`c199ab55bf1e`); `/diagnostics/recent-errors` clean on a fresh dev-server start;
      M8 headless + curl verified offline (fake mode, no live call). Manual Phase 4
      click-through recorded separately — all 6 sections PASS (`Phase-4-Test-Plan.md`,
      commit `9166468`).
      **Checked and confirmed implemented:**
      - **Data Model** — `planning_sessions` / `session_recipes` (`recipe_id` nullable +
        `slot_type`) / `session_checklist_items` (incl. 4.6 `needs_review` / `note`) match the
        spec field-for-field; `remembered_substitutions` has no `is_default`, carries `note` /
        `last_used_at` + the M8 pair columns, `UNIQUE(original_name, substitute_name)`;
        `product_units` is `UNIQUE(ingredient_name, purchase_label)`; audit columns on every
        mutable table. `tests/test_migrations.py` green (`upgrade head` == `create_all()`).
      - **Scaling Logic** — `scaling.py` only multiplies (`NO_SCALE_UNITS` pass through);
        `consolidation.py` does AU normalisation (`tbsp`=20 ml), sums, ceil-25/ceil-5 upward,
        cup-only → 2-dp un-rounded, mass+volume → `needs_review` with both parts, kg/L display
        ≥ 1000; `purchase_units.py` is the 0 / 1 / several-pack algorithm (minimise overage
        then pack count), overage shown only > ½ the largest chosen pack; re-consolidation is
        an upsert preserving `have_it` / `add_to_list`. *Note:* the spec's "pure `tbsp`/`tsp`
        → ceil 0.5" bullet is vestigial — the code always normalises `tbsp`/`tsp` to ml first,
        so that branch never triggers; left as-is (self-consistent, the hedge case can't
        arise).
      - **Ingredient Substitution (M4 + M8)** — `consolidate()` is pure (no substitution
        resolution); per-recipe `resolved_ingredient` and session-only overrides resolve in
        `session_consolidation._scaled_lines`; `remembered_substitutions` is a quick-pick
        library only; the capture-time `flag_substitutions()` Gemini call exists; M8 adds
        `resolved_quantity` / `resolved_unit` (recipe-level absolute, scales with servings)
        and the four-column equivalence pair (library + `SessionOverride`), resolved never in
        `consolidate()`.
      - **Duplicate Recipe Prevention** — `find_possible_duplicates` (4 signals, archived
        included, strongest-first), `PossibleDuplicateRecipeError` → 409
        `POSSIBLE_DUPLICATE_RECIPE`, `allow_duplicate` bypass, `GET /recipes/check-duplicate`,
        `POST /recipes/{id}/restore`, URL-capture short-circuit before the AI call. Now in
        `services/recipe_duplicates.py`.
      - **Code Architecture** — zero `fastapi` imports in `app/services/`; routers use the
        `{"ok": ...}` envelope and go through services; `schemas/` kept separate from
        `models/`; `router.js` is the only hash-parser; `tests/` mirrors `app/`, AI + AnyList
        mocked. Two of the three flagged oversized files split at this review
        (`recipe_duplicates.py`, `session_consolidation.py`); `ai_extraction.py`'s package
        split deferred with rationale — see [Deferred Decisions](../deferred-decisions.md#deferred-decisions).
      - **API Conventions** — every Phase 4 / 3.9 endpoint uses the envelope;
        `SESSION_NOT_FOUND` / `SESSION_SLOT_NOT_FOUND` / `SLOT_ORDER_MISMATCH` /
        `POSSIBLE_DUPLICATE_RECIPE` / `SUBSTITUTION_*` / `AI_EXTRACTION_*` are all
        SCREAMING_SNAKE_CASE, translated centrally in `app/main.py`; `?limit`/`?offset` on the
        session + recipe list endpoints.
      - **Recipe Capture / AI Provider Migration** — 3 separate Gemini calls, Flash →
        Flash-Lite → `capture_queue` on 429, hourly lifespan poller, "Pending AI processing"
        badge (M6), §0a hardening (delimiter / `MAX_INPUT_TEXT_CHARS` / `suggested_section`
        allow-list) and §0c gates (`AI_EXTRACTION_ENABLED` / `AI_EXTRACTION_FAKE_MODE`, off by
        default) carried over verbatim; M7 live call passed 2026-09-07 (recipe id 6, kept).
      - **Diagnostics** — the `ai_extraction` block reports `today_by_model` / `recent_calls`
        / `queue` / `last_success` / `dashboard_url` / `api_enabled` / `fake_mode`; the USD
        spend tracker + reset button + `api_usage` / `api_usage_resets` are gone (M5).
      - **Environment Variables** — `config.py` + `.env.example` on `GEMINI_API_KEY` /
        `AI_EXTRACTION_ENABLED` / `AI_EXTRACTION_FAKE_MODE`; supporting docs/scripts caught up
        this session (commit `4e6e3c2`); DEPLOY.md notes the NUC `.env` still needs the rename.
      **Carried forward as open items** (logged, not silently dropped):
      1. `services/ai_extraction.py` → `ai_extraction/` package split — deferred, see
         [Deferred Decisions](../deferred-decisions.md#deferred-decisions).
      2. Gemini free-tier data-usage decision — still open (add a Cloud Billing payment method
         to stop free-tier training use?); see [Deferred Decisions](../deferred-decisions.md#deferred-decisions).
      3. The 5 capture-flow fixes staged in `Capture-Fixes-Staged.md` were implemented
         (commit `9d30414`) but **not re-verified against a live Gemini call** — do that under
         a fresh §0c go-ahead when convenient (piggyback on any future live check).
      4. Ingredient synonym normalisation (salt group etc.) is prompt-wording only today; the
         robust Settings-managed alias table is flagged as a Phase 5/6 bring-forward.

**Deliverable:** recipe capture works end-to-end on Gemini with the Flash→Flash-Lite→queue
chain; substitution is capture-time per-recipe flagging with a quick-pick memory, no silent
auto-apply, nothing in consolidation, and can change an ingredient's amount + unit as well
as its name (M8); diagnostics shows Gemini quota + attempt log.

### Phase 3.9 chunks (M0–M8)

- **M0 — Decisions + CLAUDE.md fold-in** (this edit). Resolve the above, rewrite the
  superseded sections in place, drop the `⚠️` banners. No code.
- **M1 — Config + SDK + fake-mode skeleton.** `requirements.txt` (`anthropic` out,
  `google-genai` pinned in); `config.py` + `.env.example` env-var rename; rename
  `services/claude_client.py` → `services/ai_extraction.py` with the `google-genai` client,
  Pydantic `response_schema` models, ported fake fixtures, §0c gates verbatim. Extraction
  call only, still single-call-shaped. All tests mocked / fake — no real key.
- **M2 — Split into 3 per-task calls.** `extract_recipe()` / `flag_substitutions()` /
  `suggest_sections()` — section suggestion moves out of the extraction prompt into its own
  call. Each its own prompt + JSON schema + fixture. `capture_url` / `capture_photo`
  orchestrate the three.
- **M3 — Fallback chain + `capture_queue`.** Flash → Flash-Lite → queue on `429`
  (`RESOURCE_EXHAUSTED`); non-quota errors fail normally. `capture_queue` table + migration.
  Hourly retry poller as a lifespan background task.
- **M4 — Substitution redesign (the merge).** Migrations: `recipe_ingredients` +=
  `resolved_ingredient` / `substitution_note`; `ingredient_substitutions` →
  `remembered_substitutions` (drop `is_default`; add `note` / `last_used_at`). Rework
  `services/substitutions.py` (no default logic); **remove** substitution resolution from
  `consolidation.consolidate()`, keep the session-override resolution in
  `consolidate_session()` reading `resolved_ingredient`. `capture-review.js` +
  `recipe-edit.js` per-ingredient confirm/decline + quick-picks + "save this swap" tick;
  `settings-substitutions.js` reframed to the quick-pick library; rework the Chunk 4.7 swap.
- **M5 — Diagnostics rework.** Drop USD spend (cost math, `cost_usd_cents`, reset-spend
  button, `api_usage` / `api_usage_resets`); add `ai_call_log` + a daily quota indicator +
  recent-capture-attempt log + AI Studio dashboard link. `models/diagnostics.py`,
  `routers/diagnostics.py`, `static/js/diagnostics.js`.
- **M6 — "Pending AI processing" badge.** Per-recipe outstanding-AI-task tracking
  (`recipes.ai_tasks_pending`, migration); badge in the recipe list + detail; queued items
  visible in diagnostics.
- **M7 — Live Gemini verification.** ✅ Done 2026-09-07 — one real URL capture (satay chicken
  legs), all 3 calls `success`, structured output parsed first time, recipe kept (id 6).
  Folded in a model-ID fix: Google retired the pinned `gemini-2.5-flash` mid-migration, so
  primary/fallback are now the floating `gemini-flash-latest` / `gemini-flash-lite-latest`
  aliases. See the M7 chunk entry above and
  [Provider & model selection](../recipe-capture.md#provider--model-selection). Free-tier-data-usage decision
  still open → M-review.
- **M8 — Substitution quantity/unit transform.** ✅ Done 2026-09-07. A swap can change the
  amount + unit, not just the name ("2 corn cobs" → "2 cans"). Recipe-level absolute
  (`recipe_ingredients.resolved_quantity` / `resolved_unit`), library-level equivalence pair
  that pre-fills it, session-override pair. Resolved in `consolidate_session()`; pure
  `consolidate()` unchanged; AI flag call not extended. Migration `c199ab55bf1e`; suite 293
  pass; headless + curl verified offline. Full detail in the Phase 3.9 chunk list above and
  [Ingredient Substitution Flagging](../ingredient-handling.md#ingredient-substitution-flagging--the-merged-spec).
- **M-review** — full re-check of Phase 3.9 **and** the deferred Phase 4 review, together.

---

