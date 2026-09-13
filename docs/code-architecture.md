# Code Architecture & Maintainability

## Code Architecture & Maintainability

This is a first-class requirement, same standing as [Diagnostics & Logging](./diagnostics-and-logging.md#diagnostics--logging)
above — not a nice-to-have for "later, if there's time." The app is built incrementally over six
phases across many separate development sessions, months apart in places. The thing that makes
that safe is a codebase where each file has one obvious job, dependencies only point one
direction, and a session that has only read this file plus the two or three files it's touching
has enough context to make a correct change — without having to re-read or re-understand the
whole app first. Optimise for that over cleverness or brevity everywhere below.

### Layering — dependencies point one way only
```
routers/  →  services/  →  models/ + database.py
static/js/[feature].js  →  static/js/api.js  →  backend routers/
```
- **`routers/`** — HTTP only. Parse the request, call one (or a couple of) `services/` function(s),
  wrap the result in the `{"ok": ...}` envelope (see [API Conventions](#api-conventions)). No
  business logic, no query construction beyond a simple lookup-by-id, no direct AnyList/Claude
  SDK calls. If a route handler is doing anything a unit test would want to exercise without
  spinning up FastAPI, that logic belongs in `services/` instead.
- **`services/`** — all business logic, as plain Python. No `fastapi` import in this directory,
  ever. Where possible (`scaling.py`, `consolidation.py`, `purchase_units.py` in particular —
  these carry the highest risk of subtle bugs per [Scaling Logic](./scaling-and-consolidation.md#scaling-logic)), functions
  take plain data in and return plain data out, so they can be unit-tested with no DB and no
  network. `claude_client.py` and `anylist_client.py` are the exception in kind: they *do* talk
  to the outside world, which is exactly why §"External integrations" below applies to them.
- **`models/`** — SQLAlchemy ORM only, already split one file per table group. Never imported by
  `routers/` directly for anything beyond type hints — routers go through `services/`.
- **`schemas/`** (new — add alongside `models/`, one file per feature area matching `routers/`) —
  Pydantic request/response models. These are the API's actual contract and are kept separate
  from the ORM models in `models/` on purpose: an internal column can be renamed, split, or
  soft-deleted without every response shape changing, and vice versa. Routers import from
  `schemas/`, never expose a raw SQLAlchemy object as a response body.
- Frontend mirrors the same discipline: one `static/js/[feature].js` file per feature area
  (already the plan), all of them going through `api.js` for HTTP rather than calling `fetch`
  directly, and none of them reaching into another feature file's DOM or in-memory state.
  `router.js` is the only file that knows hash routes exist.

### External integrations sit behind a small, stable interface
The AnyList connector already has a live fork point baked into the plan — Python-native now,
Node-microservice fallback possible at Phase 5 (see [Tech Stack](./project-overview.md#tech-stack) and
[AnyList — derisking spike](./project-overview.md#anylist--derisking-spike-bring-forward)) — which is a concrete example of why this
rule exists, not a hypothetical. `services/anylist_client.py` and `services/claude_client.py` must
each expose a small function/class surface (e.g. `get_items()`, `add_item()`,
`extract_ingredients()`) that the rest of the app codes against. If the AnyList implementation
underneath ever swaps from native calls to the Node microservice, that swap is a rewrite of one
file's internals, not a hunt through every router and service that happens to need shopping-list
data. The same applies to anything else with an external dependency added later.

### Tests — pytest, `tests/` mirroring `app/`
- `services/` functions get unit tests with no DB and no network — these are cheap to write
  because the layering rule above keeps them pure, and they're what catches a scaling/rounding
  regression before it reaches a real shopping list.
- Each router gets at least a smoke test (happy path + one error path) once it has real logic
  behind it — a Build Phase isn't done when it's manually clicked through once, it's done when
  its own tests pass, matching the "build and verify each phase" rule already in
  [Build Phases](./build-status/process.md#build-phases).
- Claude API and AnyList calls are mocked in tests. Automated tests never hit the real network or
  spend real API budget — that's what the Phase 1.5 spike and manual verification are for.
- `pytest` is a dev dependency from Phase 2 onward (the first phase with real logic to test);
  add it to `requirements.txt` when that work starts, not before.

### File size and scope discipline
- One feature or table group per file, as the directory structure already lays out. A file
  pushing past roughly 300–400 lines is a signal to split it by sub-feature, not a size to grow
  toward.
- A new feature is a new file/function, not a new conditional branch bolted onto an existing one.
  Concrete example already on the books: the Phase 4 leftovers slot type
  (see [`session_recipes`](./data-model.md#session_recipes)) should land as its own small piece of logic in
  `services/`, not as a growing pile of `if slot_type == ...` checks inside whatever else is
  already in `sessions.py`.
- **Oversized files flagged 2026-09-06 to split at the Phase 3.9 M-review** — status after the
  M-review (2026-09-07):
  - ✅ `services/recipes.py` (571 → 366) — Chunk 4.2 duplicate-detection block moved to
    `services/recipe_duplicates.py`; `recipes.py` re-exports the public names so call sites
    are unchanged.
  - ✅ `services/sessions.py` (448 → 244) — the `consolidate_session` orchestrator moved to
    `services/session_consolidation.py`; `sessions.py` re-exports it.
  - ✅ `services/ai_extraction.py` (~861 by the time it was picked up) — split at the
    **Phase 5 review** (2026-09-12) into the `services/ai_extraction/` package exactly as
    the deferred `# NOTE:` planned: `types.py` (model-ID constants + public dataclasses +
    exceptions — deliberately the one module with zero imports from its siblings, which is
    what keeps the package's import graph one-way), `prompts.py`, `schemas.py`,
    `fixtures.py`, `client.py` (`_call_gemini` + the §0c gate + response cleaners), `calls.py`
    (the 4 task functions + `capture_recipe()`), `__init__.py` re-exporting the full former
    public surface (including `genai`/`settings` themselves, so
    `patch("app.services.ai_extraction.genai.Client", ...)`-style test patches keep
    resolving to the same shared module object). One real behaviour wrinkle found and fixed
    during the split, not just a file move: `capture_recipe()`'s internal calls to
    `extract_recipe()`/`suggest_sections()`/`flag_substitutions()` used to resolve as
    same-module bare names — which a test patching `app.services.ai_extraction.suggest_sections`
    relied on working, by coincidence of everything living in one file. Split apart, that
    patch no longer reached the call; fixed by having `capture_recipe()` route through the
    package's own current attributes (a call-time-deferred `from app.services import
    ai_extraction as _pkg`) instead of bare names, restoring the old patchability with no
    test changes needed. Suite 481 pass; live-smoke-tested against the real dev server in
    fake mode (`capture_recipe()` end-to-end: extraction + section suggestion + substitution
    flagging all correct), `/diagnostics/recent-errors` clean.

### Documentation & comments — thorough and judicious (set 2026-09-06)
Every file, function and non-obvious block must be documented well enough that a session
which has read only CLAUDE.md plus the two or three files it's touching can make a correct
change. This is not optional polish — it's what makes the incremental-over-many-sessions
build safe (see the intro to this section).

- **Every module** gets a docstring: what it's for, where it sits in the layering, and a
  pointer to the CLAUDE.md section(s) it exists *because of* (e.g. "see CLAUDE.md > AI
  Provider Migration").
- **Every non-trivial function** gets a docstring: what it does, what the args mean when not
  obvious, what it raises, and any invariant it upholds. One-line helpers can stay bare.
- **Comment the "why", not the "what".** Explain a decision, a workaround, a subtlety, an
  ordering constraint, a spec cross-reference — never narrate code that already reads
  plainly. A comment that restates the next line is noise; delete it.
- **Judicious, not exhaustive.** Don't pad. Dense, obvious code needs no commentary;
  surprising code needs a sentence. If a block needs a paragraph to explain, that's usually
  a sign it should be a named function instead.
- **Keep comments true.** A comment that's drifted from the code is worse than none — update
  or delete it in the same change that moves the code. Same rule as
  [Keep this document and the code pointing at each other](#keep-this-document-and-the-code-pointing-at-each-other),
  applied at the comment level.
- This applies to **all further code** — Python, JS, migrations, scripts, tests.

### Migrations
- Alembic from Phase 2 onward, as already stated in [Data Model](./data-model.md#data-model). Once Alembic is in
  use, every schema change ships as a migration — never a hand-edited table or a reliance on
  `create_all()` picking up the difference — so the schema's history stays reconstructable from
  the migration chain alone, independent of this document.
- **Reality check (2026-09-06):** Alembic was never actually set up in Phase 2 — the app still
  runs `Base.metadata.create_all()` on startup. This stayed invisible because every schema
  change through Phase 3 Chunk 3.5 only *added whole tables*, which `create_all()` handles.
  Adding `source_book`/`source_page` to the existing `recipes` table in Chunk 3.7 is the first
  change that genuinely needs a migration, so **Alembic is bootstrapped as the first step of
  Chunk 3.7** (its own commit: scaffold, wire `env.py` to `app.database.Base` and the config
  URL, a baseline revision representing the current schema, `alembic stamp head` on the
  existing dev DB). `create_all()` stays as the fresh-empty-DB fast path; schema *changes*
  from Chunk 3.7 onward go through Alembic. The Phase 4 `product_units` UNIQUE-constraint
  change (see [`product_units`](./data-model.md#product_units)) then rides on an Alembic that already exists.
- **3.7a done (2026-09-06):** `alembic==1.19.2` pinned in `requirements.txt`; `alembic/` +
  `alembic.ini` scaffolded; `alembic/env.py` takes `target_metadata` from
  `app.database.Base.metadata` (it imports `app.models` to register every table) and derives
  the DB URL from `app.config.settings.database_path` — nothing hardcoded in `alembic.ini`,
  so `alembic` and the running app can't point at different databases. `render_as_batch=True`
  for SQLite ALTERs. Baseline revision `bf3919bfcbd9` reproduces the `create_all()` schema;
  the existing dev DB was `alembic stamp head`ed, not upgraded. Verified: `alembic upgrade
  head` on a fresh empty DB is semantically identical (columns / PKs / FKs + `on_delete` /
  indexes / uniqueness) to `Base.metadata.create_all()` — codified as
  `tests/test_migrations.py`, which every future migration must keep green.
- **Applying migrations (from Chunk 3.7b onward):** dev PC — run `alembic upgrade head` after
  pulling a migration (startup `create_all()` does NOT add a column to an existing table).
  NUC — `scripts/update.py` runs `alembic upgrade head` between `pip install` and the
  restart, and aborts the restart (leaving the old version running) if it fails; wired up in
  Chunk 3.7b alongside the first real migration.

### Keep this document and the code pointing at each other
- Keep doing what Phase 1 already does: a docstring or comment that names the relevant CLAUDE.md
  section (e.g. "see CLAUDE.md > Data Model") wherever code exists *because* of a decision made
  here, not something derivable from the code alone.
- If building something surfaces a gap, contradiction, or a decision that turns out to not fit
  reality, that gets folded back into this file (per the existing norm in
  [How to Use This File in Claude Code](../CLAUDE.md#how-to-use-this-file-in-claude-code)) rather than left
  as a code comment only this session can see. A comment explains the code; this file is what the
  next session — human or Claude — reads first.

---

## Project Directory Structure

```
ShoppingApp/
├── CLAUDE.md                  ← this file
├── SETUP.md                   ← static IP + first-run + backup Task Scheduler setup for NUC
├── DEPLOY.md                  ← dev PC → NUC deployment: one-time git/GitHub setup, deploy.bat/update.bat, rollback
├── HEADLESS_VERIFY.md         ← the one working way to drive the frontend in headless Edge (scratch server + scripts/cdp.py)
├── README.md                  ← brief usage guide
├── .gitattributes             ← CRLF normalisation (Windows-only project)
├── start.bat
├── stop.bat
├── backup.bat                 ← runs scripts/backup.py
├── restore.bat                ← runs scripts/restore.py
├── deploy.bat                 ← runs scripts/deploy.py (dev PC: commit/tag/push)
├── update.bat                 ← runs scripts/update.py (NUC: pull + restart)
├── setup_nuc.bat               ← runs scripts/bootstrap_nuc.ps1 (NUC: one-time automated first-run setup)
├── requirements.txt
├── .env.example               ← template, never commit .env
├── .gitignore
├── app/
│   ├── main.py                ← FastAPI app entry point
│   ├── config.py              ← loads .env, exposes settings object
│   ├── database.py            ← SQLAlchemy engine + session factory
│   ├── models/                ← SQLAlchemy ORM models (one file per table group)
│   │   └── store.py           ← stores, store_sections, product_sections
│   ├── schemas/                ← Pydantic request/response models (one file per feature area,
│   │                              mirrors routers/ — kept separate from models/ on purpose, see
│   │                              CLAUDE.md > Code Architecture & Maintainability)
│   ├── routers/                ← FastAPI routers (one file per feature area)
│   │   ├── recipes.py
│   │   ├── sessions.py
│   │   ├── checklist.py
│   │   ├── anylist.py
│   │   ├── settings.py
│   │   └── diagnostics.py
│   ├── services/               ← business logic (no HTTP concerns)
│   │   ├── scaling.py
│   │   ├── consolidation.py     ← pure consolidation rules (rounding/units/irreconcilable)
│   │   ├── session_consolidation.py  ← consolidate_session orchestrator (DB plumbing); split from sessions.py at the M-review
│   │   ├── purchase_units.py
│   │   ├── recipes.py           ← recipe + ingredient CRUD; re-exports the duplicate-prevention API
│   │   ├── recipe_duplicates.py ← duplicate-recipe detection (Chunk 4.2); split from recipes.py at the M-review
│   │   ├── substitutions.py     ← remembered_substitutions quick-pick library (M4) + M8 equivalence pair
│   │   ├── ingredient_aliases.py ← "same shopping item" grouping (2026-09-10); distinct from substitutions.py, see CLAUDE.md > Ingredient Aliases
│   │   ├── unit_synonyms.py     ← unit-spelling canonicalisation (2026-09-12), see CLAUDE.md > Ingredient Unit Handling > Layer A
│   │   ├── coarse_ingredients.py ← ingredients that skip quantity math entirely (2026-09-12), see CLAUDE.md > Ingredient Unit Handling > Layer D
│   │   ├── sessions.py
│   │   ├── capture_url.py
│   │   ├── capture_photo.py
│   │   ├── ai_extraction/       ← Gemini per-task calls (was claude_client.py — renamed Phase 3.9 M1; split into this package at the Phase 5 review, 2026-09-12 — types/prompts/schemas/fixtures/client/calls + __init__ re-export)
│   │   ├── capture_queue.py     ← 429 retry queue + hourly poller (Phase 3.9 M3)
│   │   ├── checklist.py         ← checklist load + AnyList push orchestrator (Phase 5)
│   │   ├── usuals.py            ← "the usuals" recurring-items CRUD + due calc (Phase 5)
│   │   └── anylist_client.py    ← Python-native AnyList connector, small stable interface (Phase 5, from spike/)
│   ├── seed_data.py           ← staples + product_units + section vocabulary starter data
│   └── log_config.py          ← logging setup, in-memory ring buffer
├── alembic/                    ← DB migrations (bootstrapped Phase 3 Chunk 3.7 — see CLAUDE.md > Migrations)
│   ├── env.py                  ← wired to app.database.Base + the config sqlite:/// URL
│   └── versions/               ← one file per schema change from Chunk 3.7 onward
├── alembic.ini                 ← Alembic config (no hardcoded URL — env.py pulls it from app.config)
├── scripts/                    ← maintenance scripts, run as `python -m scripts.<name>`
│   ├── cdp.py                  ← stdlib-only headless-Edge CDP driver for frontend verification (see HEADLESS_VERIFY.md)
│   ├── seed_phase5_fixtures.py ← builds data/phase5-test.db with the recipes the Phase 5 hand test plan needs
│   ├── backup.py               ← weekly DB + JSON dump, trims old backups, commits/pushes if git is set up
│   ├── restore.py              ← lists / dry-runs / restores a backup, with a pre-restore safety copy
│   ├── deploy.py                ← dev PC: tag + push a release (see DEPLOY.md)
│   ├── update.py                ← NUC: pull + reinstall deps ahead of a restart (see DEPLOY.md)
│   ├── git_utils.py             ← shared subprocess helper used by the scripts above
│   └── bootstrap_nuc.ps1        ← NUC: one-time automated first-run setup (see SETUP.md)
├── tests/                      ← pytest, mirrors app/ structure (services/ unit tests with no
│                                  DB/network, routers/ smoke tests) — see CLAUDE.md > Code
│                                  Architecture & Maintainability. Added from Phase 2 onward.
├── static/                    ← frontend assets
│   ├── index.html
│   ├── css/
│   │   └── app.css
│   └── js/
│       ├── api.js             ← fetch wrapper, error handling
│       ├── router.js          ← client-side view routing
│       └── [feature].js       ← one file per feature area
├── images/                    ← uploaded recipe photos (gitignored)
├── logs/                      ← log files (gitignored)
├── data/                      ← SQLite database file (gitignored)
└── backups/                   ← weekly DB + JSON dump pairs (NOT gitignored — this is the backup)
```

---

## API Conventions

All API responses use this envelope:
```json
{
  "ok": true,
  "data": { ... }
}
```
```json
{
  "ok": false,
  "error": {
    "code": "ANYLIST_AUTH_FAILED",
    "message": "Could not authenticate with AnyList. Check credentials in .env.",
    "detail": "..."
  }
}
```

Error codes are SCREAMING_SNAKE_CASE strings, never raw HTTP status messages.

All list endpoints support optional `?limit=` and `?offset=` for pagination, even if not
immediately needed.

---

