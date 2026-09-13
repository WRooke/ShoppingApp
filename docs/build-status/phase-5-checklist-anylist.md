# Build Status — Phase 5: Checklist & AnyList Integration

### Phase 5 — Checklist & AnyList Integration

**Chunked 2026-09-07 at kickoff**, per
[Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking). Three deferred
decisions were resolved at kickoff and are folded in below:

- **AnyList native vs Node** — already settled by the Phase 1.5 spike: **Python-native**, no
  Node microservice. `spike/anylist_spike.py` (~500 lines: a hand-rolled protobuf codec +
  `login` / `get_lists` / `add_item` / `remove_item` / `post_operations` / `set_item_quantity`)
  and `spike/FINDINGS.md` are the reference the Chunk 5.2 connector is adapted from. See
  [Tech Stack > AnyList integration](../project-overview.md#anylist-integration--phase-5-decision).
- **Credential storage → hybrid `keyring` → `.env` fallback** (Decision Dialogue resolved).
  `config.py` tries Windows Credential Manager (`keyring`) first, falls back to the
  `ANYLIST_EMAIL` / `ANYLIST_PASSWORD` `.env` vars with a logged WARNING. `keyring` is a new
  pinned dependency. See [Security §2](../security.md#security).
- **"The usuals" → separate `usual_items` table + cadence** (Decision Dialogue resolved).
  A non-recipe recurring-items list, each item carrying a "buy every N" interval, surfaced on
  the checklist only when due. New table + service + Settings management + a checklist group.
  See [Checklist Screen Logic](../checklist-and-shopping.md#the-usuals--household-recurring-items).

**AnyList safety (kickoff, mirrors [Security §0c](../security.md#0c-api-enable-switch--offline-development-highest-priority)
for the AI):** `ANYLIST_ENABLED` (`.env`, default `false`) gates every real call;
`ANYLIST_FAKE_MODE` (default `false`) swaps in an in-memory fake list so the whole checklist
+ push flow builds and clicks through offline with no account, no network. Automated tests
never hit the real API (mocked). Manual verification runs **only** against
`ANYLIST_TARGET_LIST_NAME` (dev default `TestList`, already set aside for this). **The real
household shopping list is never read or written without a fresh, explicit, per-occasion
go-ahead from the maintainer** — a standing "yes" does not carry, same rule as §0c. No agent
session flips `ANYLIST_ENABLED`.

- [x] **Chunk 5.1 — Config: credential resolution + AnyList gates.** `keyring` pinned in
      `requirements.txt`. `config.py`: `anylist_email` / `anylist_password` resolved
      keyring-first (`keyring.get_password("shoppingapp", "anylist_email"|"anylist_password")`)
      then `.env` with a one-time WARNING when the fallback is used; `anylist_enabled` /
      `anylist_fake_mode` bools (narrow-true parse, same as the AI switches);
      `anylist_target_list_name`. `.env.example` + `settings.summary` + `SETUP.md` /
      `DEPLOY.md` (the NUC needs `keyring set` **or** `.env`). No connector yet. Unit tests
      for the resolver (keyring mocked).
      **Done 2026-09-07 (commit `0d1cbc7`).** `_from_keyring()` swallows any keyring failure
      (missing pkg / locked / absent backend) and degrades to `.env`; `anylist_secret_source`
      ("keyring"|"env"|"mixed"|"missing") drives the plaintext-fallback WARNING (emitted in
      `app.main` lifespan, not config import, since logging isn't up yet). 8 tests in
      `tests/test_config.py`; suite 301 pass.
- [x] **Chunk 5.2 — AnyList connector (`services/anylist_client.py`).** Adapt the spike behind
      a small stable interface (CLAUDE.md > External integrations): `get_items(list_name) ->
      list[AnyListItem]`, `add_or_increment_items(list_name, items)` (one batched
      `post_operations`), plus `check_auth()` for diagnostics. Protobuf codec + types lifted
      from the spike; **quantity read checks field 21 then field 18** (spike gotcha #1); **the
      `operations` multipart part carries no filename** (gotcha #2); **push is verified by
      re-fetch + diff, never trusted from the HTTP status** (gotcha #3); 401 → one token
      refresh + retry (spike didn't cover this — Phase 5 does). `ANYLIST_ENABLED` gate →
      `AnyListDisabledError`; `ANYLIST_FAKE_MODE` → deterministic in-memory `_FakeAnyList`.
      `AnyListError` / `AnyListAuthError` → envelope in `main.py`. No `fastapi` import. Unit
      tests: fake mode + a mocked `httpx` transport, no network.
      **Done 2026-09-07 (commit `cb9d00f`).** 401 handling is a fresh full re-login + one
      retry (no refresh-token endpoint needed). `main.py`: `ANYLIST_DISABLED` (503),
      `ANYLIST_AUTH_FAILED` / `ANYLIST_FAILED` (502). `_FakeAnyList` seeds milk/eggs/butter on
      the target list. 13 tests (`tests/services/test_anylist_client.py`) incl. httpx
      MockTransport for the real path + the silent-noop diff; suite 314 pass.
- [x] **Chunk 5.3 — Checklist load: service + API.** `schemas/checklist.py`;
      `services/checklist.py` `load_checklist(db, session_id)` — reads
      `session_checklist_items` (must already be consolidated), fetches AnyList items,
      fuzzy-matches names (normalised lowercase, singular/plural tolerant) to set
      `already_on_anylist` / `anylist_item_id`, pre-ticks matched items (`have_it='yes'`),
      re-confirms `is_staple`. Upsert semantics like `consolidate_session` — never clobbers a
      `have_it` the user already set. `routers/checklist.py`: `GET /checklist/{session_id}`,
      `PATCH /checklist/{session_id}/items/{item_id}` (`have_it` / `add_to_list`),
      `POST /checklist/{session_id}/items/{item_id}/resolve` (Chunk 4.6 `needs_review` lines —
      pick the mass or volume total, or enter a manual quantity/unit; clears `needs_review`).
      Service unit tests (AnyList mocked) + router smoke tests.
      **Done 2026-09-07 (commit `b3035f9`).** Key refinement: `already_on_anylist` /
      `anylist_item_id` are recomputed **only when the AnyList fetch succeeds** — a transient
      failure leaves the previous match state intact rather than wiping it; the load response
      carries `anylist_ok` / `anylist_detail`. `ChecklistNotReadyError` → 409
      `CHECKLIST_NOT_CONSOLIDATED`; `ChecklistItemNotFoundError` → 404. `_singularise` is
      conservative (tomatoes/potatoes/boxes/dishes; leaves ambiguous words alone). 14 service
      + 6 router tests; suite 334 pass.
- [x] **Chunk 5.4 — "The usuals": `usual_items` table + service + Settings.** Alembic
      migration: `usual_items` (`id`, `name` UNIQUE normalised, `notes`, `cadence_days`
      INTEGER NOT NULL — "buy roughly every N days"; `last_added_at` DATETIME nullable;
      audit columns). Cadence is **days**, not sessions (a session isn't a reliable clock —
      ad-hoc single-recipe sessions happen). `services/usuals.py`: CRUD + `due_items(db, *,
      as_of=None)` (`last_added_at IS NULL OR last_added_at + cadence_days < now`) +
      `mark_added(db, ids)`. Seeded empty (no pre-guessing — same call as staples).
      `schemas/usuals.py`, endpoints under `/api/v1/settings/usuals`, `main.py` translations,
      `static/js/settings-usuals.js` card (split per file-size rule). Service + router tests.
      **Done 2026-09-07 (commit `47fe761`).** Migration `d68cf188aaa4`; `UsualItem` in
      `catalog.py`. `is_due()` / `due_items()` / `mark_added()` (ignores unknown ids) /
      `due_as_checklist_rows()` / `to_read()` (computes `is_due`, not a stored column). 404
      `USUAL_ITEM_NOT_FOUND` / 409 `DUPLICATE_USUAL_ITEM_NAME`. 4th Settings card. 12 service
      + 4 router tests; migration parity green; suite 349 pass.
- [x] **Chunk 5.5 — Checklist UI + usuals + unit-conflict resolve.** `static/js/checklist.js`
      on `#/checklist/<session_id>` (nav gets a step from the session review screen).
      Per-item tap cycles **binary** `unknown → yes → no` (no `partial` — see
      [Deferred Decisions](../deferred-decisions.md#deferred-decisions)); items already on AnyList pre-ticked in a
      distinct style, untickable; staples shown as their own group with checkboxes; **"the
      usuals" due items** as a final group the user ticks into the list;
      `needs_review` lines get an inline resolve control (mass / volume / manual). Items
      marked `no` or with `add_to_list` true are what Chunk 5.6 pushes. `api.js` surface.
      Split by sub-feature if it passes ~350 lines. Headless-Edge/CDP verification
      (`HEADLESS_VERIFY.md`), fake mode.
      **Done 2026-09-07 (commit `897b149`).** `#/checklist/<id>` route; reached from a
      "Next: checklist →" button on the session review screen. Tap cycle
      `unknown → yes → no → unknown`; to `no` also sets `add_to_list`, back clears it.
      On-list items get `.on-anylist` styling + a "✓". Needs-review `note` is parsed into
      quick "use 100 g" buttons + a manual amount/unit entry. Usuals selection is client-held
      (`pushUsualIds`). Frontend-only chunk; suite 349 pass; headless verified all 4 groups +
      the tap cycle + resolve, no console errors.
- [x] **Chunk 5.6 — Push to AnyList + `shopping_history` + diagnostics.**
      `services/checklist.py` `push_to_anylist(db, session_id)`: collect `add_to_list` lines,
      `add_or_increment_items()` in one batch (increment when `already_on_anylist` +
      `anylist_item_id`, else add; item name Capitalised, quantity = `display_qty`), re-fetch
      + diff to confirm, then set `planning_sessions.status='pushed'` + `pushed_at`, mark any
      pushed usuals `last_added_at`, write one `shopping_history` row (`items_json` snapshot +
      `anylist_response_json`). `POST /checklist/{session_id}/push` — refuses a re-push of an
      already-`pushed` session unless `?force=true`. Diagnostics `anylist` block: last
      successful `check_auth()` timestamp, target list name, enabled/fake state, last push
      summary. Service tests (fake + mocked) + router smoke + a diagnostics test.
      **Done 2026-09-07 (commit `5367cdc`).** Push collects `add_to_list OR have_it == 'no'`
      lines + ticked due usuals; "increment" against AnyList's freetext display-string
      quantities = `set-list-item-quantity` to our `display_qty` (a display string can't be
      numerically added). Session is marked `pushed` **even if the diff wasn't fully
      confirmed** — discrepancies are recorded + returned; not marking would re-add the
      confirmed items as duplicates on retry. `SESSION_ALREADY_PUSHED` (409) unless
      `?force=true`. `anylist_client.last_success_at()` feeds diagnostics without a live
      round-trip; `POST /diagnostics/anylist-check` does an on-demand one. +8 tests; suite
      356 pass; headless E2E (review → checklist → push → history + diagnostics) clean.
- [x] **Chunk 5.7 — Live AnyList verification (TestList, explicit go-ahead required).** The
      one point that needs a real AnyList call. With real creds (keyring or `.env`),
      `ANYLIST_ENABLED=true`, `ANYLIST_TARGET_LIST_NAME=TestList`, and the maintainer's
      explicit in-conversation go-ahead **for that specific run** (a standing "yes" does not
      carry): one real end-to-end — load a checklist against TestList, push a small list,
      confirm via re-fetch + diff, then remove the test items again. **The real household
      list is never touched.**
      **2026-09-11 — the maintainer personally trialled this live and confirmed it works.**
      Box deliberately left unticked at that point because a separate agent-run pass was
      wanted, and the maintainer asked to hold off until the `.env` had been checked ("keep
      this open").
      **Done 2026-09-12 — agent-run pass, fresh explicit go-ahead given this session** (the
      maintainer set `ANYLIST_ENABLED=true` themselves — per §0c-equivalent policy no agent
      session flips that switch; confirmed both directly and via a config dump before
      anything ran: `ANYLIST_ENABLED=true`, `ANYLIST_FAKE_MODE=false`,
      `ANYLIST_TARGET_LIST_NAME='TestList'`). Ran a throwaway scratchpad script (same
      precedent as the Phase 3.9 M7 Gemini live check) directly against
      `services/anylist_client.py`'s public surface: `check_auth()` → authenticated;
      `get_items()` → confirmed the real TestList's starting state (2 items: "Crossed off"
      (checked), "Not crossed off"); `add_or_increment_items()` pushed one throwaway item
      ("Claude Chunk 5.7 Test Item", qty "1") → `confirmed=True`, zero discrepancies,
      re-fetch showed it landed with the right name + quantity; item removed again; final
      `get_items()` confirmed TestList back to exactly its original 2 items. **The real
      household list was never read or touched at any point** — every call targeted
      `TestList` only, per `settings.anylist_target_list_name`.
      **One genuine finding from that first pass, not a pre-existing bug (nothing in the
      shipped app calls remove):** the first removal attempt sent a `remove-shopping-list-item`
      op with only `list_id`/`list_item_id` (no item submessage) — AnyList returned `HTTP 200`
      but silently no-opped, the same class of "200 doesn't mean it landed" gotcha
      `anylist_client.py`'s own module docstring already warns about for other operations.
      Re-checking `spike/anylist_spike.py`'s `remove_item()` showed it always embeds the full
      item wire (field 6) on a remove, same as add — doing the same fixed it, confirmed by
      re-fetch. Not a code change: `services/anylist_client.py` deliberately exposes no
      `remove()` (the app's own push flow never deletes an AnyList item), so this only
      mattered for this one-off script.

      **Second pass, same session (2026-09-12) — the maintainer asked whether quantities and
      notes actually reach the real list, since hand-testing had flagged that before.** That
      question uncovered two real, previously undetected bugs, both fixed, plus one that
      couldn't be resolved today and is carried forward:

      1. **Fixed — one operation per HTTP request, never batched across items.** A real push
         of 2+ ingredients (the normal case — almost every session) was silently losing every
         quantity. Root-caused by comparing against the reference `codetheweb/anylist` Node
         client's actual source (`lib/list.js`/`lib/item.js`, fetched and read directly):
         it never combines operations for different items into one request either — every
         list mutation is its own lone-operation POST. `add_or_increment_items()` rewritten
         to match: one `_data_post` call per item, confirmed live with 2 items each landing
         its correct quantity. This *also* superseded the 2026-09-10 "chain a
         set-list-item-quantity op after add" workaround, which was almost certainly this
         exact bug misdiagnosed from what can't be confirmed as a single-item test at the
         time — quantity embedded only in the add's own item message (matching the reference
         client's `_encode()`) now confirmed to render correctly with no follow-up op.
      2. **Implemented, per the maintainer's request** (quantity field = the amount to
         actually buy; notes field = pack-size context): `services/checklist.py`'s
         `_display_quantity` → `_anylist_quantity` now sends the "need" total
         (`total_quantity`/`total_unit`) as AnyList's quantity, and a new `_anylist_note`
         folds the pack breakdown (e.g. "2 × 500g pack") into the note alongside the existing
         overage/to-taste/review text. Confirmed live and **visually confirmed by the
         maintainer in the real AnyList app**: "Beef Mince" showed quantity 600 g with note
         "2 × 500g pack · 400 g spare"; "Saffron" showed no quantity, note "to taste".
      3. **Attempted, then reverted — syncing a note on an item that's already on the list.**
         The original gap (a checklist note never reached AnyList past an item's first push)
         was fixed with a chained `set-list-item-details` op — confirmed live it updated the
         note correctly. But it also introduced a worse regression: once `set-list-item-details`
         touches an item, every later `set-list-item-quantity` call for that *same* item
         silently fails from then on (reproduced from a clean single-item test — quantity
         comes back completely absent, not stale). Re-sending `add-shopping-list-item` for
         the existing id doesn't recover it (that handler no-ops once the id exists); the only
         recovery found was delete + re-add under a new id, which the app can't do
         automatically without risking orphaning a household member's manual edits/checks on
         that item. **Reverted**: the update path sends only `set-list-item-quantity` again: a
         note is set correctly on an item's first push and does not update on a later push
         to an already-listed item. Documented as a real, accepted limitation (not a silent
         gap) in `anylist_client.py`'s module docstring and [AnyList Push
         Logic](#anylist-push-logic).
      4. **Carried forward, unresolved — `set-list-item-quantity` reliability on an update
         got flaky as this session went on.** After the revert above, a plain quantity-only
         update (no details involved at all) still failed on a fresh item, then failed again
         after a real 45-second delay — yet the *first* successful test of this exact
         mechanism, early in the same session (Part A), worked cleanly. Every quantity
         update attempted *later* in the session failed regardless of that item's own
         history, batching, or elapsed time; quantity *embedded directly in an add* worked
         every single time, no exceptions, throughout. Best current guess: something
         cumulative across a long real-API testing session (soft throttling on that specific
         handler, perhaps) rather than a fixed defect tied to any particular sequence — but
         this is a guess, not a finding, and needs re-testing fresh another day/session
         rather than more guessing against the real account. **Practical impact today:**
         the update path (an ingredient already on `TestList` from a previous push) cannot be
         confirmed reliable for quantity right now; the add path (a brand-new item) is
         solidly confirmed working. Re-verify this specific piece — ideally at the *start* of
         a session, away from any cumulative call volume — before relying on it. Flag for the
         Phase 5 review below.
         **Re-verified at the Phase 5 review (2026-09-12, fresh session, minimal calls,
         maintainer's explicit go-ahead for this one run):** add a throwaway item → update its
         quantity via `existing_id` (the exact mechanism under test) → re-fetch. `confirmed=True`,
         zero discrepancies, quantity read back exactly as set (`'1'` → `'2'`), on the very
         first attempt. `TestList` restored to its original 2 items; household list never
         touched. This is consistent with the "something cumulative across a long live-testing
         session" theory above, not a fixed code defect — the update path is reliable when
         exercised normally (a session pushes a handful of updates, not dozens back-to-back).
         No code change from this finding. **Residual caution, not a block:** if the earlier
         degradation recurs during a real long AnyList-heavy session, treat it as the same
         known, unconfirmed-mechanism issue rather than a new bug — don't re-diagnose from
         scratch each time.

      `TestList` restored to its exact 2 baseline items throughout and at the end of both
      passes. The real household list was never read or touched at any point. Suite re-run
      **481 pass** after all of the above; new/updated tests in `tests/services/test_anylist_client.py`
      (one-op-per-request, update-sends-only-quantity) and `tests/services/test_checklist.py`
      (`_anylist_quantity`/`_anylist_note`). Chunk kept ticked — the chunk's own ask (a real
      push, confirmed via re-fetch+diff, cleaned up after) is solidly met for the add path and
      the maintainer's quantity/note design is live-confirmed; item 4 above is the one
      genuinely open thread, carried to the Phase 5 review rather than silently dropped.
- [x] **Phase 5 review** — re-check against [Checklist Screen Logic](../checklist-and-shopping.md#checklist-screen-logic),
      [AnyList Push Logic](../checklist-and-shopping.md#anylist-push-logic), [Data Model](../data-model.md#data-model)
      (`session_checklist_items`, `shopping_history`, `usual_items`), [Security](../security.md#security)
      §1/§2, [Code Architecture](../code-architecture.md#code-architecture--maintainability),
      [API Conventions](../code-architecture.md#api-conventions), and [Diagnostics & Logging](../diagnostics-and-logging.md#diagnostics--logging),
      per [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      **Done 2026-09-12.** Full suite **481 pass** throughout (incl. after the package split
      below); `/diagnostics/recent-errors` clean on a fresh dev-server smoke test.
      **Checked and confirmed implemented:**
      - **Checklist Screen Logic** — `load_checklist()` fuzzy-matches AnyList items
        (normalised lowercase, plural-tolerant `_singularise`), pre-ticks matches, recomputes
        `already_on_anylist`/`anylist_item_id` only when the AnyList fetch actually succeeds
        (never wipes a previous match on a transient failure); staples surfaced only when
        used this session; tap cycle is binary `unknown → yes → no → unknown` (no `partial`,
        per the already-resolved Deferred Decisions row); usuals appear as their own group
        only when due; `needs_review` lines get the mass/volume/manual resolve control.
      - **AnyList Push Logic** — collects `add_to_list OR have_it == 'no'` lines + ticked due
        usuals; update-in-place vs add keyed on `anylist_item_id`; re-fetch+diff confirms,
        never trusts HTTP status alone; session marked `pushed` even on a partial confirm
        (discrepancies recorded, not silently dropped); `SESSION_ALREADY_PUSHED` unless
        `?force=true`; usuals `last_added_at` stamped only on an actual push, not merely
        being offered.
      - **Data Model** — `session_checklist_items` / `shopping_history` / `usual_items` ORM
        models match the spec field-for-field, with one gap found and fixed (below).
      - **Security §1/§2** — `ANYLIST_ENABLED`/`ANYLIST_FAKE_MODE` both default `false` in
        `config.py`; keyring-first credential resolution with a logged WARNING on the `.env`
        fallback (`anylist_secret_source` tracks which); CORS/firewall scoping from Phase 1
        untouched by this phase.
      - **Code Architecture** — zero `fastapi` imports anywhere under `app/services/`;
        `checklist.py`/`usuals.py`/`anylist_client.py` all go through the `{"ok": ...}`
        envelope via their routers, never raw `HTTPException`; `router.js` remains the only
        hash-parser; tests mirror `app/` (`test_checklist.py`, `test_usuals.py`,
        `test_anylist_client.py` at both service and router level).
      - **API Conventions** — checklist/usuals/anylist-check endpoints all use the envelope;
        `CHECKLIST_NOT_CONSOLIDATED` / `CHECKLIST_ITEM_NOT_FOUND` / `SESSION_ALREADY_PUSHED` /
        `ANYLIST_DISABLED` / `ANYLIST_AUTH_FAILED` / `ANYLIST_FAILED` / `USUAL_ITEM_NOT_FOUND` /
        `DUPLICATE_USUAL_ITEM_NAME` are all SCREAMING_SNAKE_CASE, translated centrally in
        `main.py`; the usuals list endpoint supports `?limit`/`?offset`.
      - **Diagnostics & Logging** — the `anylist` block reports enabled/fake-mode state,
        target list, credential source, last successful `check_auth()`, and the last push's
        confirm/discrepancy summary; component colour logic (grey/amber/red/green) matches
        the documented states.

      **Gaps found and fixed, not just noted:**
      1. **Doc/code drift** — `session_checklist_items.review_resolved_by_user` (added
         2026-09-10 fixing a real hand-testing bug: a manually-resolved `needs_review` total
         was being silently reset on the next re-consolidate) existed in the ORM model and
         was referenced by two code comments pointing at "CLAUDE.md > Scaling Logic >
         re-running consolidation" — but was never actually added there. Fixed: the column is
         now in the `session_checklist_items` schema block and "Re-running consolidation is a
         merge, not a rebuild" now describes what it protects against. No code change needed
         — the behaviour itself was already correct, only the documentation was missing.
      2. **File-size guideline, `services/ai_extraction.py`** — flagged at the Phase 3.9
         M-review (~715 lines) to split "before or early in Phase 5," still unsplit and grown
         to 861. Split into the `ai_extraction/` package this review (types/prompts/schemas/
         fixtures/client/calls + `__init__` re-export) — see
         [Code Architecture & Maintainability > File size and scope discipline](../code-architecture.md#file-size-and-scope-discipline)
         for the finished shape and the one real behavioural fix the split needed
         (`capture_recipe()`'s internal calls routed through the package's own attributes,
         not bare module names, to keep a test's patch targeting
         `app.services.ai_extraction.suggest_sections` working). Live-smoke-tested against
         the real dev server in fake mode after the split, not just the test suite.
      3. **Chunk 5.7 carried-forward item 4, re-verified fresh** — `set-list-item-quantity`
         on an already-listed item, tested at the start of a fresh session with minimal calls
         (maintainer's explicit go-ahead for this one run): add → update via `existing_id` →
         re-fetch, confirmed correct first attempt, `TestList` restored to baseline. Consistent
         with the "something cumulative across a long live-testing session" theory, not a
         fixed defect — no code change. See the updated Chunk 5.7 entry and the
         [Deferred Decisions](../deferred-decisions.md#deferred-decisions) row.

      **Explicitly not brought forward / honestly recorded rather than guessed at:**
      - **Ingredient synonym alias table** — the M-review's open item on this is already
        resolved, ahead of this review: built as [Ingredient Aliases](../ingredient-handling.md#ingredient-aliases)
        (2026-09-10) and extended by [Ingredient Unit Handling](../ingredient-handling.md#ingredient-unit-handling)
        (2026-09-12). Nothing left to bring forward here.
      - **"The usuals" cadence model against real use** — per the maintainer, `usual_items`
        has **not** yet been exercised in a real household session — only seeded/tested and
        headless-verified. Recorded honestly rather than claimed confirmed; re-confirm once
        it's actually been lived with for a few weeks.
      - **Remaining oversized files** — `services/session_consolidation.py` (450 lines) and
        `services/anylist_client.py` (635 lines, grown further by today's Chunk 5.7 fix) are
        both still over the ~300–400 guideline. Not split this review (only
        `ai_extraction.py`'s split was asked for) — flagged here rather than silently carried;
        revisit at Phase 6 or whenever either file is next touched for a real feature change,
        same standing as any other not-yet-urgent cleanup.

**Deliverable:** Full end-to-end flow works. User can complete a planning session and
push the result to AnyList (`TestList` in dev).

