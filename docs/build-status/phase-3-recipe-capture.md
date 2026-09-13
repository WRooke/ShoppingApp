# Build Status — Phase 3: Recipe Capture (AI)

### Phase 3 — Recipe Capture (AI)

**Kickoff (2026-09-05):** Phase 2 complete and reviewed; Phase 1.5 spike complete
(Python-native AnyList confirmed); the substitution-flagging gap resolved (doesn't exist,
not built — see [Decision Dialogues](../decision-history.md#substitution-flagging-review-step-before-phase-3-ai-extraction)).
Chunked below per [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking),
the way Phase 2 was. Since the substitution-flagging gap is what was blocking the
`suggested_section`/`cuisine`/`protein` prompt extension, that extension is built as part of
the base extraction prompt in Chunk 3.1 rather than as a separate later pass — there's no
reason to ship the Phase 1 ingredients-only prompt now and revise it again for Chunk 3.4.

**Restructured mid-kickoff per [Security §0c](../security.md#0c-api-enable-switch--offline-development-highest-priority)**
(the maintainer asked how much of this phase could be built without a real key at all): the
single real-API dependency is pushed to its own final chunk (3.6) rather than sitting inside
Chunk 3.1. Chunks 3.1-3.5 are all built and manually verified with `CLAUDE_API_FAKE_MODE=true`
— zero key, zero cost, zero real calls — the same offline path the automated test suite
already used from the start.

- [x] **Chunk 3.1 — Claude API integration + `api_usage` logging infrastructure.**
      `services/claude_client.py` (Anthropic SDK client, small stable function surface per
      [Code Architecture](../code-architecture.md#external-integrations-sit-behind-a-small-stable-interface) —
      `extract_ingredients(db, *, call_type, context_id=None, text=None, image_base64=None,
      ...)` returning parsed ingredients + `cuisine`/`protein`/per-ingredient
      `suggested_section` + token usage); `services/api_usage.py` (cost-calculation helper,
      `log_api_usage()` — [Security §0b](../security.md#0b-api-usage-observability-no-hard-cap)).
      Also folds in [Security §0a](../security.md#0a-prompt-injection-hardening-highest-priority)
      (untrusted-content delimiter, explicit system-prompt instruction, input length cap,
      `suggested_section` allow-list validation) and
      [§0c](../security.md#0c-api-enable-switch--offline-development-highest-priority) (`CLAUDE_API_ENABLED`
      gate, `CLAUDE_API_FAKE_MODE` canned-fixture path) — both raised mid-chunk, both built the
      same session.
      Verified 2026-09-05: 37 unit tests (`tests/services/test_api_usage.py`,
      `tests/services/test_claude_client.py`) plus 4 new diagnostics tests, all
      mocked/fixture-based — no network, no real key needed, per §0c. Manually confirmed the
      fake-mode path end-to-end against a scratch DB (`extract_ingredients()` with
      `CLAUDE_API_FAKE_MODE=true`, no key set at all, returned a canned fixture correctly).
      Full suite 106/106. **The real-API call itself is deliberately deferred to Chunk 3.6,
      not required to close this chunk** — see §0c for why.
      **2026-09-06 revision:** the spend cap this chunk originally built
      (`enforce_spend_cap()`, `SpendCapExceededError`, `MAX_API_SPEND_AUD_CENTS`) was removed
      — see the Non-Negotiable Operating Rules banner and Security §0b for why. Cost
      calculation and `api_usage` logging, and the §0a/§0c hardening, are unaffected and stay
      exactly as built.
- [x] **Chunk 3.2 — URL capture endpoint.** `POST /api/v1/recipes/capture/url`: fetch (httpx,
      10s timeout, desktop UA), parse (BeautifulSoup4, prefer `<article>`/`<main>`/
      `[class*="recipe"]`/`[class*="ingredient"]`), call `claude_client.extract_ingredients()`
      (usage logging happens inside that call, not here), return the extraction for review —
      does not save a recipe yet. Manual verification uses `CLAUDE_API_FAKE_MODE=true` (no key
      needed) — real extraction is exercised once, in Chunk 3.6, not per-chunk.
- [x] **Chunk 3.3 — Photo upload endpoint.** `POST /api/v1/recipes/capture/photo`: multipart
      image upload, store under `images/` with a UUID filename, call
      `claude_client.extract_ingredients()` with the image, return the extraction for review.
      Same fake-mode manual verification approach as 3.2.
- [x] **Chunk 3.4 — Review + confirm UI.** Unified review screen: editable name/qty/unit/
      preparation per ingredient (same inline-edit pattern as the Phase 2 recipe editor) plus
      editable `suggested_section` (dropdown, [Section Vocabulary](../data-model.md#section-vocabulary-starter-list)),
      `cuisine`, `protein`. On confirm: create the recipe + `recipe_ingredients`, write
      `product_sections` rows with `source='ai_suggested'` for any ingredient not already
      tagged. No substitution-suggestion UI (resolved — see above). Fully buildable/clickable
      through with fake-mode fixtures — this layer never distinguishes a real extraction from
      a canned one.
      Verified 2026-09-05/06: real headless-Edge + CDP session against the dev server —
      capture-from-URL and capture-from-photo entry points both render correctly from the
      recipe list, the review screen renders all 6 fake-fixture ingredients with populated
      section dropdowns, editing the recipe name and saving creates the real recipe + its
      ingredients + `product_sections` rows (`source='ai_suggested'`), and the app navigates
      to the saved recipe's real detail view. `/api/v1/diagnostics/recent-errors` stayed empty
      throughout, no browser console errors. Test recipe archived and its `product_sections`
      rows deleted afterwards, leaving the DB as it was before.
- [x] **Chunk 3.5 — Diagnostics wiring.** Claude API status indicator (last successful call
      timestamp) and spend tracker (running input/output token totals + estimated USD) on
      `/diagnostics`, backed by `api_usage`.
      **2026-09-06 revision:** originally specified with spend-cap fields
      (`spend_cap_aud_cents`, `remaining_usd_cents`, `spend_cap_reached`) per the
      then-current §0b — those are gone along with the cap itself (see Security §0b). What
      shipped instead: `routers/diagnostics.py` reports `estimated_spend_usd`,
      `total_input_tokens`, `total_output_tokens`, `last_success`, `api_enabled`, `fake_mode`,
      and `reset_at` (when the tracker was last reset, or null); `static/js/diagnostics.js`
      renders all of these plus a "Reset spend tracker" button with a confirm-dialog guard,
      wired to the new `POST /api/v1/diagnostics/reset-spend` endpoint
      (`services/api_usage.py` > `reset_api_usage_display()`, backed by the new
      `api_usage_resets` table — see [Data Model](../data-model.md#data-model)). Component states: fake mode →
      amber "FAKE MODE"; disabled → grey; a real logged call → green; key configured but no
      calls yet → amber; no key → grey.
- [ ] **Chunk 3.6 — Live API verification (real key, explicit go-ahead required).** The one
      point in the whole phase that actually needs a real Claude call: with a real
      `ANTHROPIC_API_KEY` in `.env`, `CLAUDE_API_ENABLED=true`, `CLAUDE_API_FAKE_MODE=false`,
      and the maintainer's explicit go-ahead given in conversation for this specific call (see
      [Security §0c](../security.md#0c-api-enable-switch--offline-development-highest-priority) — a
      standing "yes" is not enough, ask each time), run one real extraction (the staged
      scratchpad script, or through the actual UI) and confirm: a sane ingredient list comes
      back, a matching `api_usage` row is logged with a plausible cost, and
      `/diagnostics` reflects it.
      **BLOCKED 2026-09-06 — account has no API credit. Not done, not skipped; box stays
      unticked.** With the maintainer's explicit in-conversation go-ahead, one real call was
      attempted via a throwaway scratchpad script (one `claude_client.extract_ingredients()`
      on a generic pancake recipe, `call_type='recipe_url'` — ~10 lines, trivially rebuilt or
      run through the capture UI instead). Two server-side `400`s in sequence, **both before
      any billing — zero spend, zero `api_usage` rows written:**
      1. `"This API key is not scoped to a workspace"` — the key was an org-level key.
         Resolved: maintainer swapped in a key scoped to the (default) workspace.
      2. `"Your credit balance is too low to access the Anthropic API"` (`request_id`
         `req_011CemegQYZUuXMWEoHNEqcL`) — the account's prepaid balance is empty and the
         maintainer can't top it up right now (bank issue). This is the prepaid-balance
         ceiling the Non-Negotiable Operating Rules banner describes, hit at zero — there is
         no in-app mechanism to work around it and none should be added.
      **Verified up to the billing gate:** config gates read correctly
      (`claude_api_enabled=True`, `fake_mode=False`, key + workspace detected); the request is
      built and accepted by the SDK (model id `claude-haiku-4-5`, `max_tokens`, system prompt,
      content blocks all clear client-side validation and reach the server's auth/billing
      stage); the `APIStatusError → ClaudeExtractionError` path logs correctly and writes no
      `api_usage` row on failure, exactly as designed.
      **Still unverified — the actual residual risk:** that a real Haiku 4.5 response parses
      against `_parse_extraction()` (bare JSON, our exact object shape, numeric `quantity`,
      in-vocabulary `suggested_section`). Haiku is the weakest current model for strict JSON
      and the fixtures are hand-written to our own spec, so this is the one genuine unknown.
      If it's wrong the failure is contained and visible, never silent: parse error →
      structured error envelope + raw response logged at ERROR, `log_api_usage()` has already
      run so the call is still recorded, and nothing reaches the DB (the Chunk 3.4 review step
      gates every save). Likely fix: a small parser tweak (code-fence strip / string→number
      coercion), not an architectural change. Confidence it works once credit exists: ~80-85%.
      **To close:** once the account has any credit (the one call costs ≈⅓ of a US cent),
      re-run the check and confirm a sane ingredient list, one matching `api_usage` row, and
      `/diagnostics` green with `last_success` + spend populated. Needs a **fresh**
      in-conversation go-ahead per §0c — a standing "yes" does not carry.
      **Does not block:** Chunk 3.7 (no API involvement anywhere in it), the Phase 3 review
      (records this as a carried-forward open item), or Phase 4 build/verify work (all offline
      against manual + fake-mode recipes).
- [x] **Chunk 3.7 — Recipe source provenance (URL + cookbook reference).** Added 2026-09-06
      from a planning session — `recipes` records where a recipe came from only partially today
      (`source_url` is stored on URL capture but never displayed or editable; a hand-typed
      recipe can't record a URL at all; a cookbook name + page has no home anywhere). No real
      API involvement, so independent of Chunk 3.6 — can land before it. (Confirmed 2026-09-06:
      Chunk 3.6 is now BLOCKED on account API credit; 3.7 is entirely unaffected — no Claude
      call anywhere in 3.7a/b/c — and is the next Phase 3 work to pick up. The Phase 3 review
      runs after 3.7 and carries 3.6 forward as a noted open item.)
      - **3.7a — Bootstrap Alembic** (its own commit, first). `alembic` added to
        `requirements.txt` (exact pin); `alembic init`; `env.py` wired to `app.database.Base`
        and the config `sqlite:///` URL (nothing hardcoded in `alembic.ini`); a baseline
        revision representing the current schema; `alembic stamp head` on the existing dev DB
        so nothing is recreated. `create_all()` stays as the fresh-empty-DB fast path. Verify:
        `alembic upgrade head` on a throwaway empty DB yields a schema identical to
        `create_all()`. See [Code Architecture > Migrations](../code-architecture.md#migrations).
        **Done 2026-09-06** — `alembic==1.19.2`; baseline `bf3919bfcbd9`; dev DB stamped;
        empty-DB `upgrade head` verified semantically identical to `create_all()` and codified
        as `tests/test_migrations.py` (suite 130 pass). Dev + NUC migration-apply wiring
        (`scripts/update.py`) is noted in [Migrations](../code-architecture.md#migrations) and lands with 3.7b.
      - **3.7b — Schema + service + API.** Alembic `add_column` migration for
        `recipes.source_book` / `recipes.source_page` (both `TEXT NULL`); the two columns on
        `models/recipes.py` with the orthogonality comment; `source_book` (max 200) /
        `source_page` (max 50) on `schemas/recipes.py` (`RecipeBase` → `RecipeCreate`,
        `RecipeUpdate`, `RecipeRead`) and `schemas/capture.py` (`CaptureConfirmRequest`);
        explicit passthrough in `services/recipes.py` `create_recipe` +
        `create_recipe_from_capture` (whitespace-trim, empty → `None`; `update_recipe` is
        already automatic via its `exclude_unset` loop). Service unit tests + router smoke
        tests, no network.
        **Done 2026-09-06** — migration `9b903c88b3aa` (batch `add_column`, nullable, no
        default — applied to the populated dev DB, its 5 existing rows untouched).
        `_clean_optional_text()` in `services/recipes.py` trims + maps blank→`None` on both
        create paths; `update_recipe` left as-is per the note above. `scripts/update.py` now
        runs `alembic upgrade head` between `pip install` and the restart, aborting the
        restart on failure (same contract as a failed `pip install`); `DEPLOY.md` updated to
        match. 8 new tests (5 `tests/services/test_recipes.py`, 3
        `tests/routers/test_recipes.py`); suite 138 pass; `tests/test_migrations.py` confirms
        `upgrade head` still equals `create_all()` with the new columns.
      - **3.7c — Frontend (three files).** `recipes.js` detail view gets a "Source" line —
        URL rendered as `<a target="_blank" rel="noopener noreferrer">` **only** if it parses
        as `http:`/`https:` (never `javascript:`/`data:`), else plain text; book as
        "From {book}, p.{page}" (page optional); both → both; neither → nothing.
        `recipe-edit.js` gets three optional recipe-level fields (Recipe URL, Cookbook name,
        Page). `recipe-form.js` (manual entry) gets the same three. `capture-review.js` gets
        two optional inputs (Cookbook name, Page) near the cuisine/protein fields. Manual
        verification: headless-Edge/CDP against the dev server (same approach as Chunks
        2.4/3.4), cross-checked against `GET /api/v1/recipes/{id}`,
        `/diagnostics/recent-errors` clean.
        **Done 2026-09-06** — all four files as specified; `safeHttpUrl()` in `recipes.js`
        gates the link via `new URL()` + `http:`/`https:` check. Verified against a throwaway
        dev server (scratch DB, fake mode) with real headless Edge: dump-DOM confirmed the
        detail view renders a linked source for `https://…` and **plain text with no anchor
        for `javascript:alert(1)`**, plus the "From {book}, p.{page}" line; a CDP drive of
        edit mode filled the three fields, saved, and round-tripped through
        `GET /api/v1/recipes/{id}`; a CDP drive of the capture→review flow saved
        `source_book`/`source_page` via `/capture/confirm`. Backend also curl-checked
        (manual create, `javascript:` URL stored raw, PATCH `source_page`, capture confirm).
        `/diagnostics/recent-errors` clean apart from deliberate bogus-URL 404s. Suite 138
        pass (frontend-only chunk, no new Python tests).
      **Chunk 3.7 complete 2026-09-06** — commits `4536f09` (3.7a), `1d27e6d` (3.7b), 3.7c
      this commit.
- [x] **Phase 3 review** — re-check against [Recipe Capture](../recipe-capture.md#recipe-capture--ai-extraction),
      [Scaling Logic](../scaling-and-consolidation.md#scaling-logic) (n/a until Phase 4, confirm nothing here needs it yet),
      [Code Architecture](../code-architecture.md#code-architecture--maintainability), and
      [API Conventions](../code-architecture.md#api-conventions), per
      [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      **Done 2026-09-06.** Full suite 138 pass; `alembic heads` == `alembic current` on the
      dev DB (`9b903c88b3aa`); `/diagnostics/recent-errors` clean on a fresh dev-server start.
      Checked and confirmed implemented:
      - **Recipe Capture** — URL flow (`services/capture_url.py`): httpx, 10s timeout,
        `follow_redirects`, desktop UA; BeautifulSoup prefers `article`/`main`/`[class*=recipe]`/
        `[class*=ingredient]`, strips `script`/`style`/`nav`/`footer`/`header`/`noscript`,
        falls back to whole-page text. Photo flow (`services/capture_photo.py`): UUID filename
        under `images/`, JPEG/PNG enforced server-side, 10 MB defensive cap, base64 to Claude,
        image kept. Prompt (`claude_client.EXTRACTION_SYSTEM_PROMPT`): single JSON object with
        `cuisine`/`protein`/`ingredients[]`+`suggested_section`, rules verbatim from the spec;
        the `suggested_section` enum is interpolated from `SECTION_VOCABULARY` (kept in sync by
        construction, stronger than the "by hand" the spec text still describes — see note
        below). Review UI (`capture-review.js`): every field editable, on confirm creates
        recipe + `recipe_ingredients` + `product_sections` rows `source='ai_suggested'` for
        untagged ingredients only (`product_sections.tag_suggested_sections` never clobbers an
        existing row). Source provenance (3.7): two optional freetext review-screen inputs
        write `source_book`/`source_page`; extraction prompt deliberately not extended to OCR
        them.
      - **§0a prompt-injection hardening** — system-prompt data-not-instructions statement;
        non-guessable delimiter tag `untrusted_recipe_source_7f3a` wrapping the user content;
        `MAX_INPUT_TEXT_CHARS = 20_000` truncation with a WARNING log; `_clean_suggested_section`
        allow-list → `None` for any out-of-vocab value; no tool use granted to the call.
      - **§0b observability** — `calculate_cost_usd_cents` + `log_api_usage` retained and
        called inside `extract_ingredients()` immediately after every real call (before the
        parse, so a billed-but-unparseable response is still logged); `api_usage_resets` +
        `reset_api_usage_display()` is insert-only and never touches `api_usage`; diagnostics
        `/status` reports spend, tokens, `last_success`, `reset_at`, `api_enabled`,
        `fake_mode`. Hard cap gone from code — only explanatory doc/comment references remain.
      - **§0c enable switch + fake mode** — `CLAUDE_API_ENABLED` (default `false`) checked
        before any real call → `ClaudeApiDisabledError` → 503; `CLAUDE_API_FAKE_MODE`
        (default `false`) returns a deterministic canned fixture and bypasses the switch.
        `app/config.py` and `.env.example` both default both flags to `false`.
      - **Code Architecture** — zero `fastapi` imports in `app/services/`; capture logic
        behind the small `claude_client` / `capture_url` / `capture_photo` surfaces;
        `schemas/capture.py` kept distinct from `schemas/recipes.py`; every capture exception
        translated centrally in `app/main.py`, none raised as a raw `HTTPException` in a
        router; `router.js` remains the only hash-parser (capture sub-routes dispatch via the
        `recipes` route param, the review screen is an in-memory handoff, not a route);
        `tests/` mirrors `app/`, Claude mocked, migration parity guarded by
        `tests/test_migrations.py`.
      - **API Conventions** — all capture endpoints use the `{"ok": ...}` envelope;
        `CLAUDE_API_DISABLED` / `EXTRACTION_FAILED` / `RECIPE_FETCH_FAILED` / `INVALID_IMAGE`
        are SCREAMING_SNAKE_CASE; no new list endpoints, so `limit`/`offset` n/a.
      - **Scaling Logic** — confirmed nothing in Phase 3 touches scaling; the pack-size
        resolution note added to that section this session is Phase 4 (Chunks 4.3 / 4.6).
      Gap found and fixed: the **Environment Variables (.env)** block showed
      `CLAUDE_API_FAKE_MODE=true`, out of step with §0c, `app/config.py`, and `.env.example`
      (all `false`) — aligned to `false` with a note.
      Notes, no action taken: (1) `claude_client.py` is ~385 lines, marginally over the
      ~300–400 "consider splitting" guideline, but it is dominated by the cohesive prompt
      constant + three fixtures — left as one file. (2) The spec's Recipe Capture text still
      says the `suggested_section` enum is "kept in sync ... by hand"; the code actually
      interpolates it from `SECTION_VOCABULARY`, which is better — spec wording could be
      updated opportunistically.
      **Carried forward — Chunk 3.6 (live-API verification) stays unticked**, BLOCKED on an
      empty prepaid account balance (see the Chunk 3.6 entry). Residual risk is real-Haiku
      strict-JSON parsing (~80–85% confidence); the failure mode is contained and visible.
      Does not block Phase 4 build/verify, which runs offline against manual + fake-mode
      recipes; close 3.6 when the account has credit, with a fresh in-conversation go-ahead
      per §0c.

**Deliverable:** User can capture a recipe from URL or photo, review the extracted
ingredients, edit if needed, and save to the library.

