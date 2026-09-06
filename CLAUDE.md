# CLAUDE.md — Mealplanner Project Context

This file is the authoritative project specification. Read it in full before writing any code.
All decisions here were made through a detailed planning session. Do not re-litigate decided
items. Deferred items are explicitly marked — flag them for discussion when their phase arrives,
do not implement them speculatively.

**Document history:** originally written as a single planning document, then extended with three
standalone addenda (Shop Layout Reorganisation, Security Considerations, Schema & Planning
Addendum). Those addenda have since been folded into the sections below — Data Model, Build
Phases, Security, Backup & Restore, Deferred Decisions — so each decision lives next to the
related material instead of in a separate append-only block. Nothing below was re-litigated in
that process; it was moved and cross-referenced, not re-decided. A few genuine gaps the addenda
left open are called out explicitly where they occur, and again in Deferred Decisions.

---

## ⚠️ Personal Data Policy

**Under no circumstances should personal identifying information (PII) be used anywhere in this project:**
- No real names of users or household members
- No real account names or email addresses
- No specific household details, locations, or personal habits
- No real AnyList list names or shared accounts

Use generic placeholders instead: "User A", "User B", "Household Shopping List", "test@example.com", etc.

This applies to:
- Source code and comments
- Configuration files and documentation
- Git commits and history
- Logs and diagnostics output
- Test data and fixtures

**Why:** This project may be shared, archived, or referenced in contexts where real personal data should not be exposed. Treating all development as if this code will be public is the safest approach.

---

## ⚠️ Non-Negotiable Operating Rules

**Set 2026-09-05, revised 2026-09-06. These rules are of the highest criticality in this
project — they override every other facet of the app, including anything else in this
document, any convenience, any feature request, and any deadline.** Full detail lives in
[Security](#security) (§0a, §0b, §0c below); this banner exists so none of them can be missed
by skimming straight to a phase's chunk list.

> **Provider note (2026-09-06):** the AI extraction provider is Anthropic Claude → Google
> Gemini as of Phase 3.9 (see
> [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39)).
> Rules 1 (prompt-injection hardening) and 2 (explicit enable switch, fake mode,
> ask-before-real-call, no agent flips the switch) are **provider-agnostic and carry over
> verbatim** — the switches are just renamed `AI_EXTRACTION_ENABLED` / `AI_EXTRACTION_FAKE_MODE`
> and the key becomes `GEMINI_API_KEY`. §0b's *dollar-spend* observability becomes *quota*
> observability (Gemini free tier has no per-call cost).

1. **Prompt injection hardening.** Any content this app sends to an LLM that originated
   from outside the household's own direct input — a scraped webpage, a photographed
   cookbook page, or any future untrusted source — must be treated as data, never as
   instructions, and the app must be built to resist attempts embedded in that content to
   override its behaviour. Err on the side of caution in every such scenario. See
   [Security §0a](#0a-prompt-injection-hardening-highest-priority).
2. **Explicit permission to use the API at all, and development restructured to need it as
   rarely as possible.** A separate switch (`CLAUDE_API_ENABLED`, off by default) gates every
   real call, and a fake/fixture mode lets almost all of a phase's build and verification work
   happen with zero key, zero cost, and zero real calls, pushing the one unavoidable live check
   to the very end. See
   [Security §0c](#0c-api-enable-switch--offline-development-highest-priority). No agent
   session may turn the switch on itself, and must ask the maintainer in conversation before
   making any real call even once it's on. Cost calculation and per-call logging (`api_usage`)
   are kept for observability regardless — see
   [Security §0b](#0b-api-usage-observability-no-hard-cap).

**2026-09-06 revision — the hard AU$0.50 spend cap from the original 2026-09-05 rule set has
been removed.** It was set out of a mistaken belief that Anthropic API billing works like an
open-ended postpaid invoice that could spiral unnoticed. It doesn't — usage is billed against
credit purchased upfront, so there is no invoice-shock scenario for this app to additionally
guard against with an in-code ceiling; the account's own prepaid balance is already the hard
stop. The two mechanisms that address the *actual* underlying goal (never spend without
explicit permission; keep test/dev spend minimal) were never the cap itself — they're the
enable switch and fake mode above, both retained unchanged. What's gone is only
`enforce_spend_cap()`'s pre-call refusal and `MAX_API_SPEND_AUD_CENTS`; cost calculation and
`api_usage` logging stay, purely for the maintainer's own visibility into what's actually being
spent. See [Security §0b](#0b-api-usage-observability-no-hard-cap) for what replaced it.

---

## Project Overview

A shared meal planning and shopping list web application. It runs as a local web server on
a Windows 10 NUC (Intel NUC, former light-use workstation, always on). Multiple household
members access it via browser on Android phones over their home WiFi. The server pushes a
consolidated shopping list to AnyList, a shared grocery list app they both use.

**Core user flow:**
1. Start a planning session (weekly or ad-hoc single recipe)
2. Add recipes — from URL, photo of cookbook page, or the saved recipe library
3. AI extracts and displays ingredients for review and confirmation
4. Optionally slot recipes into days of the week
5. Planning engine consolidates ingredients across all recipes, scales quantities, resolves
   purchase units
6. Checklist screen: pull current AnyList items, then walk through each ingredient — "do you
   have this?" Pre-tick anything already on AnyList. Staples appear only when they are needed
   by a recipe in this session.
7. Review final list — optionally as a store-specific walking-order view (see
   [Shopping List Store Layout](#shopping-list-store-layout))
8. Push to AnyList in one action
9. Session saved to history log

---

## Users

- **Primary user** — technical background, Python experience, comfortable with technical tools
- **Secondary user(s)** — non-technical; the UI must be functional now but will need to be
  polished for everyday use in a later phase. They may also add items directly to AnyList
  manually — the system must handle that gracefully.
- **Shared access** — no login system required. Single shared account effectively.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.11+, FastAPI | FastAPI is async, modern, serves static files, has auto-docs |
| Database | SQLite via SQLAlchemy (ORM) | Zero config, single file, sufficient for household scale |
| Frontend | Vanilla HTML5 / CSS3 / JS | No build step, no framework complexity, easy to debug, runs in any browser |
| AI (recipe extraction) | Google Gemini API — `gemini-2.5-flash` (primary), `gemini-2.5-flash-lite` (fallback), then a retry queue. `google-genai` SDK, structured-output mode. Three separate calls per capture (extraction / substitution flagging / section suggestion). See [AI Provider Migration (Phase 3.9)](#ai-provider-migration--anthropic-claude--google-gemini--phase-39). | Anthropic account can't add billing credit; Gemini's free tier replaces it. *(Code is on the `anthropic` SDK / Haiku 4.5 until Phase 3.9 chunk M1 lands.)* |
| URL scraping | httpx + BeautifulSoup4 | Fetch recipe page content for Claude to parse |
| AnyList | See Phase 5 note | Unofficial reverse-engineered API — implementation approach TBD at Phase 5 |
| Deployment | Python venv, batch scripts, Windows Task Scheduler | No Docker; simple start/stop scripts |

### FastAPI notes
- Use `uvicorn` as the ASGI server
- Mount a `/static` directory for frontend assets
- **Resolved (Phase 1 kickoff):** flat static HTML + vanilla JS, no Jinja2. Matches the
  no-build-step goal; the frontend is hash-routed from a single `static/index.html`.
- All API routes under `/api/v1/`
- Enable CORS for local network access

### AnyList integration — Phase 5 decision
The AnyList API is unofficial and reverse-engineered. The reference implementation is the
Node.js package `codetheweb/anylist` on GitHub. When Phase 5 begins:
1. First attempt: implement the AnyList HTTP/WebSocket/protobuf calls natively in Python using
   `httpx`, `websockets`, and `protobuf` libraries, using the Node package as a reference.
2. Fallback: run a thin Node.js Express microservice (localhost only) that wraps the npm
   package, called by the Python backend over HTTP. This adds Node.js as a runtime dependency
   but isolates the complexity. **If this fallback is used, it must bind to `127.0.0.1` only —
   never `0.0.0.0`** (see [Security](#security) §2).
Flag this choice for discussion at the start of Phase 5.

### AnyList — derisking spike (bring forward)
AnyList has been flagged as a high-risk, low-confidence part of the stack, so the core
integration risk must be retired early rather than discovered at Phase 5. After Phase 1 is
complete and before committing to the Phase 2 build, run a throwaway spike (separate script
or scratch module, not wired into the app):
- Authenticate against AnyList with the real `.env` credentials
- Fetch the target list and its current items
- Add a test item and remove it again
- Record which approach worked (Python native vs Node microservice), any protobuf/auth
  surprises, and rough effort estimate
Deliverable: a short written finding + working proof-of-concept call. This resolves the
Phase 5 "native vs Node" choice with evidence instead of deferring it. Do not build the full
connector or UI here — just prove the calls work. Flag the result before proceeding.

---

## Deployment Environment

- **Host OS:** Windows 10
- **Dev machine:** Windows 11, Python 3.14.6
- **NUC:** bare Windows 10 install + Plex. Python not yet installed.
- **Network:** Local WiFi only. NUC needs a static local IP (reserved DHCP lease in router
  settings). See `SETUP.md`.
- **Access:** Local keyboard/mouse access to NUC and remote network access available.
- **Port:** Run on port 8080 (unlikely to conflict with Plex). Make configurable via .env.

### Startup
Two batch scripts in the project root:
- `start.bat` — creates/activates the venv on first run, installs dependencies, starts uvicorn,
  opens a browser to the app URL
- `stop.bat` — kills the running app process

Two more for the backup system (see [Backup & Restore](#backup--restore)):
- `backup.bat` — runs `scripts/backup.py`
- `restore.bat` — runs `scripts/restore.py`

Two more for deployment from the dev PC to the NUC (added ahead of schedule, alongside this
session's diagnostics/backup work, since getting the pipeline right early is cheap and it
only gets more annoying to retrofit once there's more to ship — see `DEPLOY.md` for the full
walkthrough and one-time git/GitHub setup):
- `deploy.bat` — runs `scripts/deploy.py` on the **dev PC**, from the `develop` branch:
  verifies the working tree is clean and current, tags the commit, pushes `develop` + the
  tag to the private GitHub repo, then fast-forwards the remote `production` branch to
  match.
- `update.bat` — runs `scripts/update.py` on the **NUC**, from the `production` branch:
  pulls the new commit (fast-forward only, never merges), reinstalls dependencies if
  `requirements.txt` changed, then stops and restarts the server. Aborts before touching the
  running server if any step fails, so a bad update leaves the old version running.

Two branches, not one — see [Git branching strategy](#deferred-decisions), decided at the
Phase 2 review: `develop` is where all work happens (dev PC), `production` is what the NUC
runs and only ever moves via `deploy.bat`. Full rationale, one-time setup (including
migrating this repo's existing `main` history across), and the day-to-day workflow are in
`DEPLOY.md`.

This reuses the same private GitHub repo already planned as the backup push destination
(see [Backup & Restore](#backup--restore)) rather than adding a second piece of
infrastructure — one repo, two jobs (three, counting deploys). `scripts/backup.py`'s
commit-and-push now rebases onto the latest origin first, precisely so its weekly commits
(landing on `production`, since that's what the NUC is checked out on) and dev-PC deploys
fast-forwarding that same branch don't fight each other.

One more, for first-run NUC setup: `setup_nuc.bat` runs `scripts/bootstrap_nuc.ps1`, which
automates everything about SETUP.md steps 1–6 that safely can be (installing Python + Git,
cloning the repo, scaffolding `.env`, adding the firewall rule scoped to the NUC's actual
LAN subnet, first start + health check). **Deliberately still manual, per the existing
"Task Scheduler: not a script — too brittle" call below**: the router-side static IP
(no script has access to the router's admin UI) and the two Task Scheduler entries
(auto-start-on-boot and weekly backup) — scripting the "run whether logged on or not" boot
trigger would need the NUC account's Windows password handled non-interactively, which
trades one kind of fragility for another. See `SETUP.md` for the full breakdown of what's
automated vs. still manual, and why.

Windows Task Scheduler instructions (not a script — too brittle) for auto-start on boot and for
the weekly backup are in `SETUP.md`.

---

## Diagnostics & Logging

This is a first-class requirement, not an afterthought. The system must make it
readily apparent when, where, why and how something has failed.

### Rules
- Every module must use Python's `logging` library with a named logger (`logging.getLogger(__name__)`)
- Log levels: DEBUG (request/response detail, internal state), INFO (user actions, session events),
  WARNING (recoverable issues, unexpected but non-fatal states), ERROR (failures, exceptions)
- All exceptions must be caught at the outermost handler, logged with `exc_info=True`, and
  return a structured JSON error response to the frontend
- Every external API call (Claude API, AnyList, URL fetch) must be wrapped in try/except,
  log the attempt at INFO, log success at INFO, log failure at ERROR with full exception info
- Log format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

### Log file
- Write to `logs/app.log` in the project root
- Rotate daily, keep 14 days of history (`logging.handlers.TimedRotatingFileHandler`)

### Diagnostics web UI
A `/diagnostics` page in the web app (accessible from the main nav) must show:
- **Live log tail**: last 200 log entries, auto-refreshing every 5 seconds, filterable by level
- **Component status panel**: green/amber/red indicators for:
  - Database connection
  - AI extraction service (Gemini) — last successful call timestamp, and which model handled
    it (`flash` / `flash-lite`) or whether the last capture is queued
  - AnyList connection (last successful auth timestamp)
- **Daily quota usage indicator**: observed Gemini request count today per model (from
  `ai_call_log`), plus a link to the Google AI Studio dashboard. Best-effort — exact free-tier
  caps are not reliably documented, so this is an observed count, not "X of Y". *(Replaced the
  old USD "API spend tracker" + reset button at Phase 3.9 — the Gemini free tier has no
  per-call dollar cost. See [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39).)*
- **Recent capture attempt log**: last N `ai_call_log` rows — task type, model tried, outcome
  (`success` / `quota` / `error` / `queued`), error detail. Queued captures are also surfaced
  here.
- **Recent errors**: last 10 ERROR-level entries highlighted prominently at the top

The diagnostics page must be built as a skeleton in Phase 1 and populated progressively as
each component is added.

---

## Code Architecture & Maintainability

This is a first-class requirement, same standing as [Diagnostics & Logging](#diagnostics--logging)
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
  these carry the highest risk of subtle bugs per [Scaling Logic](#scaling-logic)), functions
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
Node-microservice fallback possible at Phase 5 (see [Tech Stack](#tech-stack) and
[AnyList — derisking spike](#anylist--derisking-spike)) — which is a concrete example of why this
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
  [Build Phases](#build-phases).
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
  (see [`session_recipes`](#session_recipes)) should land as its own small piece of logic in
  `services/`, not as a growing pile of `if slot_type == ...` checks inside whatever else is
  already in `sessions.py`.

### Migrations
- Alembic from Phase 2 onward, as already stated in [Data Model](#data-model). Once Alembic is in
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
  change (see [`product_units`](#product_units)) then rides on an Alembic that already exists.
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
  [How to Use This File in Claude Code](#how-to-use-this-file-in-claude-code)) rather than left
  as a code comment only this session can see. A comment explains the code; this file is what the
  next session — human or Claude — reads first.

---

## Data Model

All tables use SQLite via SQLAlchemy. Alembic for migrations — intended from Phase 2 onward,
actually bootstrapped at Phase 3 Chunk 3.7 (the first change to an existing table); see
[Code Architecture > Migrations](#migrations) for that history. `Base.metadata.create_all()`
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
> [Purchase unit resolution](#scaling-logic) for the selection algorithm this enables, and
> [Deferred Decisions](#deferred-decisions). Do not implement before Phase 4 — this is a plan,
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
[AI Provider Migration > Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec)).
A row is created only when the user ticks "save this swap" at capture-review, in the recipe
editor, or (optionally) after a planning-session swap.

```
id              INTEGER PRIMARY KEY
original_name   TEXT NOT NULL       -- normalised lowercase, matches recipe_ingredients.name
substitute_name TEXT NOT NULL       -- normalised lowercase (a single freetext string; 1:many
                                     -- like "milk + lemon juice" is stored verbatim — see
                                     -- Deferred Decisions)
note            TEXT               -- nullable, freetext — pre-fills recipe_ingredients.substitution_note
last_used_at    DATETIME           -- nullable, for quick-pick ordering (most-recent first)
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
UNIQUE(original_name, substitute_name)
```
Multiple substitutes per `original_name` are allowed; **none is a "default"** — they are all
just quick-picks, ordered by `last_used_at`. Never pre-seeded. Deleting a row never touches
any recipe's `resolved_ingredient` or any past session (reversibility is recipe-level).
Managed in Settings (`settings-substitutions.js`, reframed at M4).

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

From the [Shopping List Store Layout](#shopping-list-store-layout) design. Build now
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

## Scaling Logic

When a recipe is scaled from its base servings to requested servings.

> **Where rounding lives — resolved 2026-09-06 at Phase 4 kickoff (grilling with the
> maintainer; supersedes the earlier "round inside `scaling.py`" wording).** `scaling.py`
> does **one thing: multiply**. No rounding, no unit conversion, no pack-size logic. It takes
> `(quantity, unit, factor)` and returns `(quantity × factor, unit)` with the unit preserved
> verbatim; `"pinch"` / `"to taste"` style units pass straight through untouched
> (`scaled=False`). **Every** rounding and unit-normalisation decision happens *once*,
> downstream, in `consolidation.py` + `purchase_units.py` (Chunk 4.6) — after quantities from
> all recipes in the session have been summed. Rounding per-recipe and then summing would
> round twice and let drift compound across a session. Rationale in full:
> [Decision Dialogue > Scaling: rounding location & rules](#scaling-rounding-location--rules-phase-4-kickoff).

### Scaling — the `scaling.py` half (Chunk 4.3)
- `scaling_factor(base_servings, target_servings)` → `target / base` (raises on non-positive base).
- `scale_quantity(quantity, unit, factor)` → multiply; unit kept exactly as given (so `kg`
  stays `kg`, free-text `"can"` stays `"can"`); `NO_SCALE_UNITS` (`pinch`, `to taste`,
  `taste`, `splash`, `drizzle`, `dash` — extensible) pass through with `scaled=False`.
- **Default target servings = 4** — the household is two adults, each taking a serving as
  next-day lunch (2 people × 2 meals). Used as the pre-fill when a recipe is added to a
  session (Chunk 4.4), always overridable per recipe. It's a constant
  (`DEFAULT_TARGET_SERVINGS`), not yet a Settings field — see
  [Deferred Decisions](#deferred-decisions).
- Scaling is **rare** in practice (most recipes are `base_servings=4`, target 4, factor 1.0).

### Rounding & unit rules — the `consolidation.py` half (Chunk 4.6)
Applied to the **summed** quantity for each consolidated ingredient, in this order:

1. **Unit normalisation (Australian conversions — confirmed 2026-09-06).** Volume↔volume
   only; there is no density data so weight↔volume is never converted.
   - `tsp` → 5 ml, **`tbsp` → 20 ml** (the Australian tablespoon, *not* 15), `cup` → 250 ml
   - `kg` → 1000 g, `L` → 1000 ml
   After this, quantities for one ingredient are either all-mass (g) or all-volume (ml), or
   they are irreconcilable (see 4).
2. **Sum** the normalised quantities across the session's recipes (a substituted ingredient
   is already resolved to its target name before this — see
   [Ingredient Substitution](#ingredient-substitution)).
3. **Round the sum** — always **upward** to a clean step, never to nearest, so a shopping
   quantity is tidy but is **never short** ("tolerances, not round-to-x, remove admin"):
   - discrete / countable (no unit, or a free-text unit like `can`/`bunch`/`clove`) →
     **ceil to a whole number** (`1.5 eggs` → `2`; applies when scaling *down* too;
     `½ onion` → `1`)
   - g / ml, value ≥ 100 → **ceil to nearest 25**
   - g / ml, value < 100 → **ceil to nearest 5**
   - `tbsp` / `tsp` → ceil to nearest 0.5 (only relevant if an ingredient is *purely*
     tbsp/tsp across the whole session and so never got normalised to ml — in practice rare)
   - `cup` → 2-decimal trim, **no** clean-rounding (a scaled cup value is almost always < 1,
     where a "nearest 5" rule would destroy it)
   - `NO_SCALE_UNITS` ("to taste") → shown on the list **with no number** (e.g.
     `saffron — to taste`)
4. **Irreconcilable** — mass + volume for the same ingredient (e.g. `100 g cream` +
   `200 ml cream`), or a count + a unit (`3 onions` + `200 g onions`). Not merged: the line
   is **flagged** and both parts are shown (`cream — 100 g + 200 ml (needs review)`). The
   review UI for resolving these is Phase 5; Phase 4 only flags it on the API response.
5. **kg / L for display** — after summing in g/ml, a total ≥ 1000 is shown back in kg/L
   (`1030 g` → `1.03 kg`).

### Free-text units (`can`, `bunch`, `clove`, `sprig`, …) — 2026-09-06
Manual entry allows any unit string. Anything not in {`g`,`kg`,`ml`,`L`,`tsp`,`tbsp`,`cup`}
and not in `NO_SCALE_UNITS` is treated as **discrete** — scaled, then ceil-to-whole
("2 cloves" ×1.5 → 3). **Flagged as a revisit-after-real-use item** (see
[Deferred Decisions](#deferred-decisions)) — it's the pragmatic default, not a confident one.

### Consolidation across recipes
Each ingredient's effective name is its `recipe_ingredients.resolved_ingredient` if set,
else its `name` — so a recipe whose "bulgarian feta" the user resolved to "regular feta"
consolidates onto the same line as another recipe's "regular feta". **The pure
`consolidation.consolidate()` does no substitution *resolution*** (Phase 3.9 M4 — see
[AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39)):
it is handed already-resolved names as plain data. A **session-only** planning swap (the
Chunk 4.7 ad-hoc swap) is applied one layer up, in the `consolidate_session()` orchestrator,
which computes each ingredient's effective name (resolved_ingredient → session override)
before feeding `consolidate()`. The per-ingredient sum → normalise → round → flag pipeline
is the "Rounding & unit rules" list above. A consolidated line always carries the **required quantity** (the rounded sum);
purchase-unit resolution below may *add* a pack breakdown next to it but never replaces it —
so a no-pack-size ingredient still shows an amount (`passata — 1.05 kg`), and a pack-size
ingredient shows both (`passata — 2 × 750 g jars · need ~1.05 kg`).

### Purchase unit resolution (design confirmed 2026-09-05, PARTIALLY DEFERRED — build at Phase 4)
When an item exists in `product_units`, calculate how many purchase units are needed to cover
the required quantity, and display as e.g. "2 × 500g packs" or "1 dozen eggs".

**Multiple pack sizes per ingredient are the normal case, not an edge case** — confirmed
2026-09-05 after checking real household usage patterns. An ingredient like yoghurt commonly
comes in more than one pack size (e.g. 500g and 1kg tubs); resolving purely against a single
seeded size and rounding up (2 × 500g to cover 750g) gives the wrong answer when a 1kg tub
would do. This is what `product_units` moving to one-row-per-pack-size in Phase 4 (see the
[`product_units`](#product_units) schema note) is for. The resolution algorithm, to build when
Phase 4 starts — documented now so the shape doesn't need re-deriving then:

1. Look up all `product_units` rows for the ingredient (there may be zero, one, or several).
2. **Zero rows:** no pack breakdown — the consolidated line is just the rounded required
   quantity (`passata — 1.05 kg`).
3. **One row:** round the required quantity **up** to the nearest whole multiple of that pack.
4. **Several rows:** choose the combination of available pack sizes (repeats allowed) whose
   total meets or exceeds the required quantity, minimizing total overage first and pack count
   second as a tiebreaker (e.g. need 750g, options {500g, 1kg} → one 1kg pack, not two 500g).
   The search space is tiny (a handful of pack sizes, realistically no more than 2-3 packs
   deep to reach any plausible household quantity) — brute-force over small combinations is
   fine, no general knapsack/DP solver needed.
5. This generalises rather than replaces the existing "countable item purchase unit thresholds"
   deferred item below (eggs: need 6, buy a dozen?) — once an ingredient like eggs has more
   than one pack size seeded (e.g. half-dozen and dozen), step 4 already covers it. No separate
   special case for countable vs weight/volume items.

**Display (confirmed 2026-09-06 grilling):**
- The consolidated line **always shows the required quantity**; a pack breakdown is shown
  *in addition*, never instead: `passata — 2 × 750 g jars · need ~1.05 kg`. This is the
  resolution to the maintainer's worry about a bare `passata` line hiding "how much".
- **Overage** (spare amount beyond what the recipes need) is shown **only when it exceeds
  roughly half of one pack of the size used** — `need 750 g → 1 × 1 kg tub` (250 g over, a
  quarter-pack) says nothing; `need 550 g → 2 × 500 g packs` (450 g over, ~a pack) shows it.

**Multi-pack, seeded from day one (2026-09-06 — deliberate small departure from the
"don't pre-enumerate pack sizes" note below).** The maintainer wants the several-rows path
exercised in real use immediately rather than shipping dormant. `seed_data.py` seeds a
handful of genuine multi-pack items — **eggs (½ dozen + dozen), milk (1 L + 2 L), yoghurt
(500 g + 1 kg)** — and the algorithm + Settings multi-row display get real test coverage in
Phase 4, not "later". Every *other* ingredient still stays single-pack; a second option is
added via Settings opportunistically, as originally intended:

Most ingredients stay single-pack, as seeded. A second/third option gets added — via Settings
(see [Chunk 2.5](#phase-2--recipe-library)) — opportunistically, only for specific ingredients
where it's actually been noticed to matter. Chunk 4.5 re-checks that the Settings
`product_units` view still displays sensibly now an ingredient can have more than one row.

**Re-running consolidation is a merge, not a rebuild (2026-09-06).**
`POST /sessions/{id}/consolidate` upserts `session_checklist_items` keyed by
`ingredient_name`: quantities / pack breakdowns / `is_staple` / irreconcilable flags are
recomputed, new lines are added and lines no longer needed are removed, but per-item
**state is preserved** for lines that persist — `have_it`, `add_to_list`, and (Phase 5)
`already_on_anylist` / `anylist_item_id`. So adding a recipe and re-consolidating never
discards checklist progress.

---

## Recipe Capture — AI Extraction

**Provider: Google Gemini** (`gemini-2.5-flash` → `gemini-2.5-flash-lite` → `capture_queue`),
`google-genai` SDK, structured-output mode. See
[AI Provider Migration (Phase 3.9)](#ai-provider-migration--anthropic-claude--google-gemini--phase-39)
for the full spec — the provider swap, the Flash→Flash-Lite→queue chain, the "Pending AI
processing" badge, and the substitution merge. *(Code is on the `anthropic` SDK / Haiku 4.5
until Phase 3.9 chunk M1.)*

**Three separate Gemini calls per capture**, not one combined call (Phase 3.9 M2):
1. **Recipe extraction** — ingredients + `cuisine` / `protein` (the JSON below, minus
   `suggested_section`).
2. **Ingredient substitution flagging** — per recipe, per-ingredient confirm/decline (the
   merged spec — see the migration section).
3. **Store section suggestion** — per ingredient (`suggested_section`), moved out of the
   extraction prompt into its own call.

Each call: its own system prompt, its own Gemini `response_schema` (structured-output), its
own fake-mode fixture, its own place in the Flash→Flash-Lite→queue chain. A failed/queued
enrichment call (2 or 3) does not block extraction — the recipe is still usable, and
`recipes.ai_tasks_pending` + the badge track what's outstanding.

The rest of this section — the extraction prompt, the §0a hardening, the review flow — is
otherwise preserved across the provider swap. Where it still says "Claude", read "the AI
extraction service".

### URL capture flow
1. User pastes URL
2. Backend fetches page with `httpx` (follow redirects, 10s timeout, desktop user-agent)
3. Parse HTML with BeautifulSoup4, extract text content (strip nav, footer, ads — prefer
   `<article>`, `<main>`, `[class*="recipe"]`, `[class*="ingredient"]` elements)
4. Send extracted text to Claude with the extraction prompt (see below)
5. Return structured ingredient list to frontend for user review

### Photo capture flow
1. User uploads image (JPEG or PNG, from camera or gallery)
2. Store image in `images/` directory with UUID filename
3. Send image to Claude as base64 with the extraction prompt
4. Return structured ingredient list for user review
5. Keep image stored (linked to recipe record)

### Claude extraction prompt (system)

**Built at Phase 3 kickoff (2026-09-05) with the `suggested_section`/`cuisine`/`protein`
extension already folded in** — schema for these fields has existed since Phase 1, and the
extension was only waiting on the substitution-flagging gap, resolved the same day (see
[Decision Dialogues > "Substitution flagging" review
step](#substitution-flagging-review-step-before-phase-3-ai-extraction)). There is no
ingredients-only version of this prompt in the running app; building that and revising it
again a few chunks later would be pure churn. The response shape is a single JSON object
(not a bare array) so the recipe-level fields have somewhere to live:

```
You are a recipe extraction assistant. Given recipe text or an image of a recipe, extract
the ingredients list plus a few recipe-level fields. Return a single JSON object with this
exact structure:
{
  "cuisine": "italian" or null,
  "protein": "chicken" or null,
  "ingredients": [
    {
      "name": "ingredient name, lowercase, no preparation notes",
      "quantity": 2.0,
      "unit": "g" or null for unitless items,
      "preparation": "finely diced" or null,
      "original_text": "the raw text as it appeared",
      "suggested_section": "produce" or null
    }
  ]
}

Rules:
- quantity must be a number (convert fractions: 1/2 → 0.5)
- unit must be one of: g, kg, ml, L, tsp, tbsp, cup, or null
- Convert any non-standard units to the closest standard unit
- If a quantity is a range (e.g. "1-2 cloves"), use the lower bound
- Separate compound ingredients (e.g. "for the sauce:") into individual items
- Do not include method instructions or serving suggestions
- suggested_section must be one of: produce, dairy, meat & seafood, bakery, frozen, pantry,
  household, deli, drinks, other — or null if you are not reasonably confident
- cuisine and protein are freetext (lowercase, one or two words, e.g. "italian", "beef mince")
  — use null if not reasonably inferrable from the recipe
- Return ONLY valid JSON. No markdown, no explanation, no preamble.
```

The `suggested_section` enum in the prompt text is kept in sync with
`SECTION_VOCABULARY` in `app/seed_data.py` by hand (see
[Section Vocabulary Starter List](#section-vocabulary-starter-list) — it's still provisional,
so if that list changes, update this prompt text too). The review UI (Chunk 3.4) shows every
field as editable — `suggested_section` per ingredient, `cuisine`/`protein` per recipe — and on
confirm writes `product_sections` rows with `source='ai_suggested'` for any newly-tagged
ingredient. No substitution/alternatives suggestion mechanism is part of this review step
(resolved 2026-09-05 — see the Decision Dialogue linked above) — still correct as of 2026-09-06:
ingredient substitution is real and in scope, but lives in Phase 4's planning flow, not here.
See [Ingredient Substitution](#ingredient-substitution).

### After extraction
- Display extracted ingredients in an editable review UI (inline edit of name, qty, unit)
- User confirms or edits, then saves
- On save: normalise ingredient names to lowercase, store in `recipe_ingredients`
- Log: recipe id, call type, token counts, cost to `api_usage`

### Source provenance on the review screen (Phase 3 Chunk 3.7, 2026-09-06)
The review screen also carries two optional freetext inputs — **cookbook name** and **page** —
that the user fills in by hand while reviewing (same treatment as the existing `cuisine` /
`protein` inputs). They write `recipes.source_book` / `recipes.source_page` on confirm. Most
relevant for a photographed cookbook page; a URL capture already carries `source_url` through
without any new input.

**The extraction prompt is deliberately NOT extended to read the book title/page out of a
photo.** Reasons: OCR of a running-header book title / page number is unreliable; every new
prompt field costs a fresh round of [§0a](#0a-prompt-injection-hardening-highest-priority)
output-validation work on a prompt that was only just built and stabilised in Chunk 3.1; and
the manual inputs fully cover the need. Best-effort AI pre-fill of these two fields is parked
as a [Deferred Decision](#deferred-decisions) — revisit only if typing them every capture
turns out to be a real annoyance.

---

## Ingredient Normalisation

Ingredient names must be consistent across recipes for consolidation to work. Rules:
- Store all names in lowercase
- Strip leading/trailing whitespace
- Canonical forms: "beef mince" not "minced beef", "spring onion" not "green onion"
- On first capture, names are stored as Claude returns them (after lowercasing)
- The user can edit names in the recipe editing UI
- **Do not implement automatic synonym matching in early phases** — the user reviews and
  confirms all extractions, which provides sufficient normalisation for now. Flag for future.

---

## Ingredient Substitution

**Status: in scope. Design = the MERGE of the Phase 4 approach and the addendum's
capture-time flagging, confirmed 2026-09-06. Built in Phase 3.9 chunk M4.** The full,
authoritative spec is
[AI Provider Migration > Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec)
and the merge table just above it. This section is now a summary + the history.

Distinct from [Ingredient Normalisation](#ingredient-normalisation) above: normalisation
recognises two names as *the same thing* ("green onion" = "spring onion"). Substitution
treats two *different* products as interchangeable for shopping, because one is obscure or
hard to find — e.g. "bulgarian feta" → "regular feta".

### Summary of the merged design

- **Proposed** by a dedicated Gemini call at capture time (per recipe), *and* editable later
  in the recipe editor, *and* swappable session-only during planning.
- **Stored** on the ingredient record: `recipe_ingredients.resolved_ingredient` (nullable —
  the swap this recipe uses) + `substitution_note`. `name` stays the original. Clearing
  `resolved_ingredient` reverts.
- **Confirmed per recipe, always.** No silent auto-apply, no `is_default`.
- **Remembered** in [`remembered_substitutions`](#remembered_substitutions) *only* as a
  quick-pick accelerator — it pre-fills / top-ranks the suggestion in the per-recipe confirm
  UI under a "from your saved swaps" label; the user still confirms. The AI flagging call is
  never told about past choices.
- **Consolidation** reads `resolved_ingredient` (fallback `name`) as plain data — no
  substitution logic in the pure `consolidate()`. A session-only planning swap resolves in
  the `consolidate_session()` orchestrator.
- **1:many** ("buttermilk" → "milk + lemon juice") is a single freetext string for now — see
  [Deferred Decisions](#deferred-decisions).

### History (superseded designs, kept for the record)

- **2026-09-05** — "substitution flagging" asked about; resolved "doesn't exist, not built"
  (correct for that narrow question). See the Decision Dialogue.
- **2026-09-06 (a)** — reopened as a **Phase 4** feature: a global `ingredient_substitutions`
  table of name-scoped rules, one `is_default` per name **auto-applying silently at
  consolidation**, cross-session memory, a Settings management screen, created reactively
  from a planning-session "Remember this?" prompt. **Built** in Chunks 4.1 / 4.5 / 4.6 / 4.7.
- **2026-09-06 (b)** — the AI Provider Migration addendum's capture-time flagging idea +
  the Phase 4 approach were **merged** (this section). M4 keeps the library table (as
  `remembered_substitutions`, minus `is_default`), the multi-substitute quick-picks, Settings
  management, and the planning-swap plumbing; removes silent auto-apply and the
  `consolidate()` resolution step; adds the capture-time AI call and the
  `recipe_ingredients` columns.

> The detailed 2026-09-06 (a) design text (scope decisions, "where this lives", the open
> item about bulk rename) previously filled this section. It has been removed as defunct;
> `git log` on this file has it if ever needed. The Phase 4 chunk-list entries for 4.5–4.7
> still describe what was built and what M4 changes.

### Two situations, not one
- **Genuinely one-off** — "I'm out of basil this week, using oregano instead." Applies to this
  session's shopping list only. Never remembered, never affects the recipe or any future session.
- **Worth remembering** — once a substitute is confirmed to work, the user shouldn't have to
  re-confirm it every time that ingredient comes up in a future planning session.

### Scope decisions (confirmed 2026-09-06)
- **Not the same as recipe editing.** If a recipe's ingredient text is simply wrong (a typo, a
  bad AI extraction), that's fixed via the existing recipe editor
  ([Chunk 2.4](#phase-2--recipe-library), already built) — a correction, not a substitution.
  Substitution is for ingredients that are correctly captured but undesirable to actually buy.
- **No proactive tagging UI.** A rule is never created speculatively — same reasoning already
  applied to [Staples](#staples-starter-list) and the [`product_units`](#product_units)
  multi-pack-size note: don't pre-guess, wait for a real gap to show up in use. The *only* way an
  `ingredient_substitutions` row gets created is reactively, from an actual ad-hoc swap during
  planning (see below). There is no standalone "tag this ingredient as substitutable" screen.
- **Rules apply by ingredient name, not by recipe.** A rule for "bulgarian feta" applies to
  every recipe using that name, not only the recipe it was first created from. This is what
  makes a rule better than editing recipes individually once the same obscure ingredient turns
  up in more than one recipe — handled for free, no extra design needed.
- **One ingredient can have more than one known substitute**, e.g. "bulgarian feta" → both
  "regular feta" and "goat cheese" might be acceptable. Only one is the default (auto-applied);
  the rest are offered as quick-pick alternatives rather than retyped from scratch each time.
- **No repeated confirmation.** The core decision everything else follows from: a remembered
  substitution auto-applies silently at consolidation time, every time, with no "are you sure?"
  interruption. The cost of a substitution the user no longer wants is paid for by reversibility
  (below), not by asking up front every session.
- **Easily reversible, by construction.** A substitution is a separate record layered on top of
  a recipe, not an edit to the recipe itself — switching back to the original ingredient is
  disabling or deleting the rule in Settings. The recipe's own stored data is never touched, so
  there's nothing to retype from memory.
- **No recipe-level opt-out/kill switch.** Considered and dropped: once nothing interrupts the
  user uninvited, there's nothing left for a kill switch to protect against.

### Where this lives in the app (Phase 4)
- **Creation.** During planning session ingredient review — exact screen/placement is a Phase 4
  kickoff detail, but conceptually this happens after recipes are added to a session and before
  the consolidated list is finalised. The user can swap any ingredient for another, freely,
  whether or not a rule already exists for it. After a swap, the app asks *"Remember this
  substitution?"*:
  - **Yes** — creates or updates an `ingredient_substitutions` row. If this is the first
    substitute recorded for that ingredient, it becomes the default. If substitutes already
    exist for that ingredient, the new one is added as a non-default option unless explicitly
    marked as the new default.
  - **No** — applies to this session's shopping list only; nothing is written to the database.
  - If known substitutes already exist for the ingredient being swapped, they're offered as
    quick-pick options rather than requiring the user to retype a previously-used substitute.
- **Application.** Resolved during Phase 4, **before consolidation runs** — not at checklist
  time (Phase 5). This is what lets an accepted substitute merge correctly with any other line
  in the session needing the same resolved ingredient: if one recipe needs "bulgarian feta"
  (substituted to "regular feta") and another recipe separately needs "regular feta", they
  consolidate into one shopping-list line, not two. For each ingredient pulled from the
  session's recipes: look up `ingredient_substitutions` for a matching `original_name`; if a
  default exists, resolve to the substitute's name for consolidation purposes; otherwise use the
  ingredient's name as-is. **The recipe's own stored ingredient name is never modified** by this
  process — only the resolved name used for that session's consolidation and shopping list. See
  [Scaling Logic > Consolidation across recipes](#scaling-logic), which this step feeds into.
- **Management.** Settings ([Chunk 2.5](#phase-2--recipe-library), already built) gains a
  section listing existing substitution rules — view, change which substitute is the default,
  add/remove substitute options for an ingredient, delete a rule entirely. This is the only
  place a rule can be edited or reversed after creation; there is no separate creation path here
  (see "No proactive tagging UI" above).

### Open item
Handled for free by rules applying at the ingredient-name level: the same obscure ingredient
showing up in more than one recipe needs no extra design, since one rule already covers every
recipe using that name. What's *not* covered: if the same ingredient needs correcting in the
recipe data itself (a genuine fix, not a substitution) across several recipes at once, there's
no bulk rename/merge utility — each recipe is edited individually via the existing editor. Real
enough to flag, not real enough to build speculatively — see
[Deferred Decisions](#deferred-decisions).

---

## Duplicate Recipe Prevention

**Status: in scope, Phase 4.** Designed 2026-09-06. The recipe library must not silently
accumulate multiple copies of the same recipe — whether re-added because the user forgot it
was already there, or captured a second time under a slightly different name. None of the
three entry paths (`create_recipe`, `create_recipe_from_capture`, and the URL/photo/manual
capture flows — see [Recipe Capture](#recipe-capture--ai-extraction)) check for an existing
recipe today.

Distinct from [Ingredient Normalisation](#ingredient-normalisation) and
[Ingredient Substitution](#ingredient-substitution) above — those operate on *ingredient*
names within/across recipes. This operates on whole *recipes*, at save time.

### Why Phase 4, not Phase 3
Placed with the planning-engine work at Phase 4 kickoff (confirmed 2026-09-06), even though
capture (the main duplicate vector) is a Phase 3 feature. Reasons: it depends on the
`recipes.source_book` / `recipes.source_page` columns from
[Chunk 3.7b](#phase-3--recipe-capture-ai) for one of its match signals, so it can't land
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
  with [Security §0c](#0c-api-enable-switch--offline-development-highest-priority)'s
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
   Parked as a [Deferred Decision](#deferred-decisions) — revisit only if near-dupes are
   still getting through after Phase 4.

### Layering (per [Code Architecture](#code-architecture--maintainability))
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

## Checklist Screen Logic

At checklist screen load:
1. Fetch current AnyList items (names + quantities)
2. For each consolidated ingredient in `session_checklist_items`:
   a. Check if it appears in current AnyList list (fuzzy name match — normalised lowercase,
      strip plurals if needed)
   b. If found: set `already_on_anylist = True`, `have_it = 'yes'` by default
   c. Check if it is in `staples` table: set `is_staple = True`
3. Present checklist to user:
   - Items already on AnyList: pre-ticked, shown in a distinct style (user can untick)
   - Staples (only if used in this session's recipes): shown with a checkbox
   - All other items: unchecked by default
4. User taps each item: cycles through have_it states: unknown → yes → no → (partial if
   applicable)
5. Items marked 'no' or where `add_to_list` is True get pushed to AnyList

### "The usuals" — household recurring items (new, flag for Phase 5 design)
Raised 2026-09-05: alongside the recipe-driven checklist above, offer an optional pass over
recurring non-recipe household items — laundry powder, dishwashing liquid, and similar things
bought periodically regardless of what's being cooked that week. This is a distinct concept
from [`staples`](#staples) — staples are recipe ingredients assumed to already be on hand and
are only surfaced when a recipe in the session actually needs them; "the usuals" are non-recipe
items with no ingredient/recipe link at all, offered on their own schedule rather than triggered
by anything in the session. Not designed yet — open questions to resolve at Phase 5 kickoff:
- New table (e.g. `usual_items`, name/notes, shaped like `staples`) vs. some other structure —
  needs its own decision, not just reuse of `staples`.
- Whether it's offered every session or on some longer cadence (a weekly household run vs. every
  ad-hoc single-recipe session).
- Whether it plugs into the existing checklist UI as another item group, or is a separate optional
  step in the flow (e.g. before or after the ingredient checklist).
See [Deferred Decisions](#deferred-decisions).

---

## AnyList Push Logic

On push:
1. For each `session_checklist_items` where `add_to_list = True`:
   - If `already_on_anylist = True` AND `anylist_item_id` is set: increment quantity on
     existing item rather than adding duplicate
   - Otherwise: add as new item
2. Item name: use `ingredient_name` (capitalised for display)
3. Item quantity: use `display_qty` string (e.g. "2 × 500g packs", "1 dozen", "400g")
4. On completion: set `planning_sessions.status = 'pushed'`, set `pushed_at`, write to
   `shopping_history`
5. Log full response from AnyList to `shopping_history.anylist_response_json`

---

## Shopping List Store Layout

**Status: in scope** (folded in from the Shop Layout Reorganisation addendum). Originally
listed as a deferred item ("Shop layout reorganisation" — Phase 6 or post-MVP) and,
separately, "Multi-shop support" was Post-MVP/descoped. Both are now active scope — a
fixed single-store layout doesn't match the actual use case, so the descope was reversed.
Schema lands in Phase 1 (see [Data Model](#data-model)); the setup and rendering UI lands in
Phase 6 (see [Build Phases](#build-phases)).

### Use case
The shopping list should render in a walking order that matches whichever store the trip is
actually happening at — not one fixed layout, and not alphabetical or list-order. Each store
has its own section layout, defined once and reused on every future trip to that store.

### Scope decisions (confirmed)
- **Multi-store**: in scope. Each store is a distinct entity with its own section order.
- **Ordering data source**: no learning/inference from behaviour. The user sets a fixed section
  order per store, once, and edits it manually if a store's layout changes.
- **AnyList relationship**: AnyList stays untouched. This is a separate, app-native sorted
  view/printout generated from the same underlying list data — not a write-back into AnyList's
  own categories/sections. This keeps AnyList as the single source of truth for list state and
  avoids depending on what AnyList's API does or doesn't expose for section control.
- **Section assignment**: mixed — AI suggests a section for each item at capture time, user
  confirms/corrects (see the Phase 3 extraction prompt extension above).

### Key simplification
A product's *section* (e.g. "dairy", "produce", "frozen") is a property of the product, assigned
once, store-independent. A store's *section order* (which section comes first when walking that
store) is a property of the store, assigned once, product-independent. Sorting a list for a given
store is then just: group items by section → order groups by that store's section order → render.
This avoids a per-product-per-store mapping (which would require re-tagging every product for
every store) in favour of two small, independent tables that combine at render time — see the
`stores` / `store_sections` / `product_sections` tables in the Data Model.

### Store setup flow (new, small UI — Phase 6)
One-time per store: user adds a store by name, then drags the section vocabulary into their
preferred walking order. Editable later if a store rearranges. No per-product interaction here —
this screen only touches `store_sections`.

### List rendering flow (Phase 6)
1. User selects a store for the current shopping trip (defaults to last-used store).
2. App pulls the current checklist (from the existing planning engine output — unchanged).
3. Items are grouped by `section_name` via `product_sections`.
4. Groups are ordered using that store's `store_sections.sort_order`.
5. Any item with no section yet (never tagged) falls into an "other" group at the end, surfaced
   for tagging next time it comes up in capture.
6. Rendered as a sorted view/printout in-app. The AnyList list itself is not modified.

### Cost/complexity profile
Low. Two new small tables, one new one-time setup screen, one additional field in an extraction
prompt that's already being called per recipe, and a grouping/sort operation at render time. No
new AI calls beyond the existing per-recipe extraction (section suggestion piggybacks on it).

### Open items
- Store deletion/merge is not designed — low priority, add if it comes up (see
  [Deferred Decisions](#deferred-decisions)).
- Never-tagged items fall into an "other" group at render time — fine for MVP, not revisited.

---

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
  [Code Architecture](#code-architecture--maintainability).
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
doesn't match MFP's numbers is two sources of truth. See [Deferred Decisions](#deferred-decisions)
and the Decision Dialogue.

If this is ever built, expect roughly: an `ingredient_nutrition` reference table keyed by
`ingredient_name` (per-100g / per-unit macros, user-correctable — same pattern as
[`product_units`](#product_units) / [`product_sections`](#stores-store_sections-product_sections)),
per-recipe cached totals, and ingredient-level weight/density data to convert
tsp/tbsp/cup/"each" into the grams nutrition data is quoted in (partly overlapping
`product_units.purchase_qty`). That unit conversion is the genuinely hard part and the main
reason this is not a small feature.

### Out of scope (unchanged)
Cost/budget tracking stays out ([Explicitly Out of Scope](#explicitly-out-of-scope)); this does
not reopen it. Nutrition display, if it ever lands, is a reference readout — not a calorie-goal
or diet-tracking feature inside the app. MFP is that tool.

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
[Shopping List Store Layout](#shopping-list-store-layout). Lives as a Python constant
(`SECTION_VOCABULARY` in `app/seed_data.py`), not a database table — `section_name` columns are
free text, so this only drives dropdown choices in the (not-yet-built) store-setup and
section-tagging UI. Starter list, **provisional — confirm/adjust before the Phase 6
UI is built**:
```
produce, dairy, meat & seafood, bakery, frozen, pantry, household, deli, drinks, other
```

---

## Build Phases

Build and verify each phase before starting the next. Each phase ends with a working,
testable state. Do not skip ahead.

### Phase workflow & progress tracking
Each phase is broken into a small number of chunks — five is a reasonable default, not a rule;
a phase can have more or fewer if its work doesn't split evenly into five. A chunk is a
self-contained slice of a phase that one session can pick up, finish, and verify without leaving
the phase half-wired.

- Chunks are tracked as checkbox lines (`- [ ] ...` → `- [x] ...`) directly under their phase,
  in place of a flat bullet list — progress state lives next to the spec it tracks instead of in
  a separate document that can drift, same reasoning as folding the old addenda into this file
  rather than appending them (see Document history above).
- Tick a chunk's box only once it's actually built and verified — matches the existing rule that
  a phase "isn't done when it's manually clicked through once, it's done when its own tests
  pass" (see [Code Architecture & Maintainability](#code-architecture--maintainability)); the
  same standard applies at chunk granularity, not just at the whole-phase level.
- **Phase-end review:** before starting the next phase, re-read every section of this file the
  finished phase touches — not just its own chunk list, but Data Model, Security, API
  Conventions, Scaling Logic, etc., wherever relevant — and confirm each requirement is actually
  implemented, not just plausible. Record the review as its own checked-off line at the end of
  the phase's chunk list (e.g. `- [x] Phase N review — see CLAUDE.md > Phase workflow &
  progress tracking`). A gap the review turns up gets fixed, or logged as an open item /
  [Deferred Decisions](#deferred-decisions) entry if it's a genuine design decision to defer —
  never silently dropped.
- Phases are chunked out at that phase's own kickoff, not speculatively ahead of time — the same
  "do not implement deferred items speculatively" norm this file already applies everywhere
  else. Phase 2 below is the first phase chunked this way; Phases 3–6 get their chunk lists when
  each is actually reached.

### Phase 1 — Foundation
**Status: ✅ Complete.** **Phase 1 review (2026-09-05, pre-Phase-2):** re-checked this phase
against Security, Diagnostics & Logging, and Backup & Restore above (Phase 1 predates the
chunking convention, so this review was done as a whole-phase pass rather than a per-chunk
one). Found and fixed: CORS was `allow_origins=["*"]` with no auth, tightened to
`ALLOWED_ORIGINS` (see [Security §4](#security)); uvicorn's default logging config was
silently dropping every access-log line from `logs/app.log` and the diagnostics ring buffer
(`log_config=None` fix, plus removing a since-counterproductive `WARNING` filter on
`uvicorn.access`); `requirements.txt` was floor-pinned (`>=`) rather than exact, now pinned;
`diagnostics.py` had real logic with no test coverage, now has smoke tests. Also actually ran
`restore.bat latest --yes` for the first time (list → dry run → real restore), closing out
the "tested once" deliverable below rather than leaving it assumed. See commit
`e5b70a0` for detail. No open gaps carried forward — Phase 2 can start clean.
- Project scaffold: FastAPI app, directory structure, requirements.txt
- SQLite database setup with SQLAlchemy, all tables created on startup, including:
  - the recipe-history and "suggest something" prep columns on `recipes`
    (`times_made`, `last_made_at`, `rating`, `cuisine`, `protein`)
  - soft-delete (`recipes.archived_at`)
  - audit columns (`created_at`/`updated_at`) on every mutable table
  - `stores`, `store_sections`, `product_sections` (schema only — setup/rendering UI is Phase 6)
- Logging setup: file handler + in-memory ring buffer for diagnostics UI
- Diagnostics page skeleton (component status stubs, log tail viewer)
- `.env` file for configuration (PORT, ANTHROPIC_API_KEY, ANYLIST_EMAIL, ANYLIST_PASSWORD,
  LOG_LEVEL)
- `start.bat` and `stop.bat` scripts
- Automated backup: `scripts/backup.py` + `backup.bat`, weekly via Task Scheduler, plus
  `scripts/restore.py` + `restore.bat`, restore path actually tested once (see
  [Backup & Restore](#backup--restore))
- Security `[Phase 1 fix]` items applied — see [Security](#security) §1 and §3
- Static IP setup instructions for Windows 10 (as a `SETUP.md` file in project root)
- Health check endpoint: `GET /api/v1/health` returns DB status, config loaded status

**Deliverable:** Server starts, diagnostics page loads, log tail shows startup messages, backup
and restore have each been run successfully at least once.

### Phase 1.5 — AnyList derisking spike
**Status: ✅ Complete.** Finding: Python-native confirmed over the Node microservice fallback
(see [Tech Stack > AnyList integration](#anylist-integration--phase-5-decision)) — no revisit
needed at Phase 5 kickoff, just implementation.
Slotted in immediately after Phase 1 because AnyList has been flagged as the highest-risk,
lowest-confidence part of the stack — it must not stay unexplored until Phase 5.
- Throwaway spike only (scratch script / notebook, not wired into the app)
- Authenticate, fetch the target list + items, add and remove a test item
- Determine Python-native vs Node-microservice approach from real results
- Write up the finding (what worked, auth/protobuf surprises, effort estimate)

**Deliverable:** A working proof-of-concept AnyList call and a short written finding that
settles the Phase 5 "native vs Node" decision. Full connector and checklist UI stay in
Phase 5. Flag the outcome before continuing to Phase 2.

### Phase 2 — Recipe Library

- [x] **Chunk 2.1 — Data layer.** `schemas/recipes.py` (Pydantic request/response models per
      [Code Architecture](#code-architecture--maintainability)); `services/recipes.py` covering
      recipe CRUD (delete is soft: sets `archived_at`) and nested `recipe_ingredients` CRUD;
      `seed_data.py` populated with the [Staples Starter List](#staples-starter-list) and
      [Pre-seeded Product Units](#pre-seeded-product-units), run on first startup.
      Verified 2026-09-05: 20 new unit tests (`tests/services/test_recipes.py`, in-memory
      SQLite, no HTTP) all pass; real dev server started twice against `data/mealplanner.db` —
      first run seeded 22 product units + 19 staples (log line confirmed:
      `app.seed_data: Reference data seed: {'product_units_added': 22, 'staples_added': 19}`),
      second run (restart) added zero more, confirming the seed is idempotent as designed.
- [x] **Chunk 2.2 — Recipe & ingredient API.** `routers/recipes.py`: recipe CRUD endpoints plus
      nested ingredient CRUD endpoints, `{"ok": ...}` envelope, `?limit=`/`?offset=` pagination
      on list endpoints (see [API Conventions](#api-conventions)). Add `pytest` to
      `requirements.txt` (first phase needing it — see
      [Code Architecture > Tests](#code-architecture--maintainability)); unit tests for
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
      (a real "cooked" event is post-push, Phase 5+; see [Deferred Decisions](#deferred-decisions)).
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
      sections, per [Phase workflow & progress tracking](#phase-workflow--progress-tracking).
      **Also flag for decision:** Git branching strategy — should we introduce `production` /
      `develop` branches now to prevent breaking the working app, or defer this? (See
      [Deferred Decisions](#deferred-decisions) for full details.)
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
      [Code Architecture & Maintainability](#code-architecture--maintainability) — split
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
      see [Deferred Decisions](#deferred-decisions).
      Git branching decision made and implemented (not deferred) — see
      [Deferred Decisions > Git branching strategy](#deferred-decisions) for what was
      decided, built, and verified, and `DEPLOY.md` for the resulting workflow.

**Deliverable:** User can manually add, view, and edit recipes. Staples and product units
table is pre-populated and editable via Settings page.

### Phase 3 — Recipe Capture (AI)

**Kickoff (2026-09-05):** Phase 2 complete and reviewed; Phase 1.5 spike complete
(Python-native AnyList confirmed); the substitution-flagging gap resolved (doesn't exist,
not built — see [Decision Dialogues](#substitution-flagging-review-step-before-phase-3-ai-extraction)).
Chunked below per [Phase workflow & progress tracking](#phase-workflow--progress-tracking),
the way Phase 2 was. Since the substitution-flagging gap is what was blocking the
`suggested_section`/`cuisine`/`protein` prompt extension, that extension is built as part of
the base extraction prompt in Chunk 3.1 rather than as a separate later pass — there's no
reason to ship the Phase 1 ingredients-only prompt now and revise it again for Chunk 3.4.

**Restructured mid-kickoff per [Security §0c](#0c-api-enable-switch--offline-development-highest-priority)**
(the maintainer asked how much of this phase could be built without a real key at all): the
single real-API dependency is pushed to its own final chunk (3.6) rather than sitting inside
Chunk 3.1. Chunks 3.1-3.5 are all built and manually verified with `CLAUDE_API_FAKE_MODE=true`
— zero key, zero cost, zero real calls — the same offline path the automated test suite
already used from the start.

- [x] **Chunk 3.1 — Claude API integration + `api_usage` logging infrastructure.**
      `services/claude_client.py` (Anthropic SDK client, small stable function surface per
      [Code Architecture](#external-integrations-sit-behind-a-small-stable-interface) —
      `extract_ingredients(db, *, call_type, context_id=None, text=None, image_base64=None,
      ...)` returning parsed ingredients + `cuisine`/`protein`/per-ingredient
      `suggested_section` + token usage); `services/api_usage.py` (cost-calculation helper,
      `log_api_usage()` — [Security §0b](#0b-api-usage-observability-no-hard-cap)).
      Also folds in [Security §0a](#0a-prompt-injection-hardening-highest-priority)
      (untrusted-content delimiter, explicit system-prompt instruction, input length cap,
      `suggested_section` allow-list validation) and
      [§0c](#0c-api-enable-switch--offline-development-highest-priority) (`CLAUDE_API_ENABLED`
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
      editable `suggested_section` (dropdown, [Section Vocabulary](#section-vocabulary-starter-list)),
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
      `api_usage_resets` table — see [Data Model](#data-model)). Component states: fake mode →
      amber "FAKE MODE"; disabled → grey; a real logged call → green; key configured but no
      calls yet → amber; no key → grey.
- [ ] **Chunk 3.6 — Live API verification (real key, explicit go-ahead required).** The one
      point in the whole phase that actually needs a real Claude call: with a real
      `ANTHROPIC_API_KEY` in `.env`, `CLAUDE_API_ENABLED=true`, `CLAUDE_API_FAKE_MODE=false`,
      and the maintainer's explicit go-ahead given in conversation for this specific call (see
      [Security §0c](#0c-api-enable-switch--offline-development-highest-priority) — a
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
        `create_all()`. See [Code Architecture > Migrations](#migrations).
        **Done 2026-09-06** — `alembic==1.19.2`; baseline `bf3919bfcbd9`; dev DB stamped;
        empty-DB `upgrade head` verified semantically identical to `create_all()` and codified
        as `tests/test_migrations.py` (suite 130 pass). Dev + NUC migration-apply wiring
        (`scripts/update.py`) is noted in [Migrations](#migrations) and lands with 3.7b.
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
- [x] **Phase 3 review** — re-check against [Recipe Capture](#recipe-capture--ai-extraction),
      [Scaling Logic](#scaling-logic) (n/a until Phase 4, confirm nothing here needs it yet),
      [Code Architecture](#code-architecture--maintainability), and
      [API Conventions](#api-conventions), per
      [Phase workflow & progress tracking](#phase-workflow--progress-tracking).
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

### Phase 3.9 — AI Provider Migration (Anthropic Claude → Google Gemini) + substitution merge

**Added 2026-09-06.** Full spec, rationale and all resolved decisions:
[AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39).
Runs on top of the completed Phase 4 chunks 4.1–4.4 / 4.6; **M4 removes** the substitution
parts of Chunks 4.5 / 4.6 / 4.7 and replaces them with the merged design. The Phase 4 review
is folded into this phase's M-review.

- [ ] **M0 — Decisions + CLAUDE.md fold-in.** Done 2026-09-06 (this edit). No code.
- [ ] **M1 — Config + `google-genai` SDK + fake-mode skeleton.** `anthropic` out /
      `google-genai` pinned in; `ANTHROPIC_API_KEY`→`GEMINI_API_KEY`,
      `CLAUDE_API_*`→`AI_EXTRACTION_*`; `services/claude_client.py`→`services/ai_extraction.py`
      with the Gemini client, Pydantic `response_schema` models, ported fake fixtures, §0c
      gates verbatim. Extraction call only, still one-call-shaped. All tests mocked / fake.
- [ ] **M2 — Split into 3 per-task calls.** `extract_recipe()` / `flag_substitutions()` /
      `suggest_sections()` — section suggestion leaves the extraction prompt. Each own prompt +
      schema + fixture. `capture_url` / `capture_photo` orchestrate.
- [ ] **M3 — Fallback chain + `capture_queue`.** Flash → Flash-Lite → queue on `429`;
      non-quota errors fail normally. `capture_queue` table + migration. Hourly retry poller
      (lifespan background task).
- [ ] **M4 — Substitution redesign (the merge).** Migrations: `recipe_ingredients` +=
      `resolved_ingredient` / `substitution_note`; `ingredient_substitutions` →
      `remembered_substitutions` (drop `is_default`; add `note` / `last_used_at`). Rework
      `services/substitutions.py` (no default logic); **remove** substitution resolution from
      `consolidation.consolidate()`, keep the session-override resolution in
      `consolidate_session()` reading `resolved_ingredient`. `capture-review.js` +
      `recipe-edit.js` per-ingredient confirm/decline + quick-picks + "save this swap";
      `settings-substitutions.js` reframed; rework the Chunk 4.7 swap.
- [ ] **M5 — Diagnostics rework.** Drop USD spend (`api_usage` / `api_usage_resets` /
      `cost_usd_cents` / reset-spend button); add `ai_call_log` + daily quota indicator +
      recent-capture-attempt log + AI Studio link.
- [ ] **M6 — "Pending AI processing" badge.** `recipes.ai_tasks_pending` (migration); badge
      in the recipe list + detail; queued items visible in diagnostics.
- [ ] **M7 — Live Gemini verification.** The one real call, §0c-gated, explicit
      in-conversation go-ahead. Structured output parses, `429` handling, one real end-to-end
      capture. Revisit the free-tier-data-usage decision.
- [ ] **M-review** — full re-check of Phase 3.9 **and** the deferred Phase 4 review, together,
      per [Phase workflow & progress tracking](#phase-workflow--progress-tracking).

**Deliverable:** recipe capture works end-to-end on Gemini with the Flash→Flash-Lite→queue
chain; substitution is capture-time per-recipe flagging with a quick-pick memory, no silent
auto-apply, nothing in consolidation; diagnostics shows Gemini quota + attempt log.

### Phase 4 — Planning Engine

**Chunked 2026-09-06** (during Phase 3 Chunk 3.7 / the Phase 3 review — Phase 3 is not yet
closed; this list is planning-ahead, no Phase 4 chunk starts until the Phase 3 review is
signed off), per
[Phase workflow & progress tracking](#phase-workflow--progress-tracking), the way Phases 2
and 3 were. Four deferred decisions were resolved at planning time and folded into the
relevant sections rather than left for kickoff:
- **Australian pack-size rounding → calculate exactly** (option 2). Scaling keeps the true
  quantity; whole-pack rounding + overage display happen only in purchase-unit resolution.
  See [Scaling Logic](#scaling-logic) and its Decision Dialogue.
- **Weekly planner calendar view → moved to Phase 6.** Phase 4 sets `day_of_week` via a plain
  dropdown; the drag-into-a-7-day-grid layout is a Phase 6 polish item.
- **"Mark cooked" (`times_made` / `last_made_at`) → moved to Phase 6.** Closes the flag
  carried from Chunk 2.1/2.4. A real "cooked" event is post-push (Phase 5+), so it lands in
  the Phase 6 pass, not here.
- **"Suggest something" → stays deferred, no phase.** Not on the Phase 4 deliverable path and
  the signal algorithm is still undesigned. See its Decision Dialogue.

The [ingredient substitution](#ingredient-substitution) and
[duplicate recipe prevention](#duplicate-recipe-prevention) designs are already written up in
full — the chunks below build them, they are not re-opened here.

- [x] **Chunk 4.1 — Migrations + schema groundwork (no behaviour change).** Rides on the
      Alembic bootstrapped in Chunk 3.7a. Migrations + model updates only, nothing wired to
      logic yet: `session_recipes.recipe_id` → nullable and add
      `slot_type TEXT NOT NULL DEFAULT 'recipe'` (`'recipe'`|`'leftovers'`, see
      [`session_recipes`](#session_recipes) Phase 4 note); `product_units` drop
      `UNIQUE(ingredient_name)` → `UNIQUE(ingredient_name, purchase_label)` (SQLite
      batch/table-rebuild, see [`product_units`](#product_units) Phase 4 note); new
      `ingredient_substitutions` table + model (schema already in [Data Model](#data-model)) +
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
      [Duplicate Recipe Prevention](#duplicate-recipe-prevention) — ingredient-set overlap
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
      [Code Architecture](#code-architecture--maintainability), so heavy unit tests.
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
      `if slot_type == ...` pile ([Code Architecture](#file-size-and-scope-discipline)).
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
      [`ingredient_substitutions`](#ingredient_substitutions)); management section in Settings
      (`routers/settings.py` + `static/js/settings.js`). Also re-check the Settings
      `product_units` view still renders sensibly now an ingredient can have several pack-size
      rows ([`product_units`](#product_units) note). The ad-hoc swap + "remember this?" flow
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
      [Scaling Logic > Rounding & unit rules](#rounding--unit-rules--the-consolidationpy-half-chunk-46)
      and the Decision Dialogue). Consolidation: resolve substitution rules first (default
      only, silent); call `scaling.py` per recipe (leftovers slots contribute nothing);
      normalise units — **AU conversions** `tsp`=5 ml / `tbsp`=**20 ml** / `cup`=250 ml,
      `kg`=1000 g, `L`=1000 ml, volumes now merge; sum; **round the sum *upward*** to a clean
      step (ceil 25 for g/ml ≥100, ceil 5 below, ceil to whole for counts incl. free-text
      units, `cup` 2-dp trim only, `NO_SCALE_UNITS` → no number); mass-vs-volume for one
      ingredient stays **irreconcilable** → flagged, both parts shown. Purchase units: the
      zero / one / several `product_units` rows algorithm from
      [Scaling Logic](#scaling-logic) (brute-force small pack combos, minimise overage then
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
- [ ] **Phase 4 review** — re-check against [Data Model](#data-model) (`planning_sessions`,
      `session_recipes`, `session_checklist_items`, `ingredient_substitutions`,
      `product_units`), [Scaling Logic](#scaling-logic),
      [Ingredient Substitution](#ingredient-substitution),
      [Duplicate Recipe Prevention](#duplicate-recipe-prevention),
      [Code Architecture](#code-architecture--maintainability), and
      [API Conventions](#api-conventions), per
      [Phase workflow & progress tracking](#phase-workflow--progress-tracking).
      **⚠️ Blocked / rescoped 2026-09-06 by the
      [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini)
      addendum:** Chunks 4.5 / 4.6 / 4.7 built the now-superseded global
      `ingredient_substitutions` design, which that addendum tears out. Chunks 4.1–4.4 and the
      duplicate-recipe-prevention (4.2), scaling (4.3), session-CRUD (4.4), consolidation +
      purchase-units (4.6 minus the substitution step) work stand. The review should run
      *after* the migration is planned/sequenced, so it isn't signing off code that's about to
      be removed. See the addendum's Migration Notes decision list.

**Deliverable:** User can create a session, add recipes, scale them, substitute an ingredient
they don't want to buy, and see a consolidated shopping list with purchase units resolved.

### Phase 5 — Checklist & AnyList Integration
*(Not yet chunked — break this into checkbox chunks at kickoff, following
[Phase workflow & progress tracking](#phase-workflow--progress-tracking).)*
- AnyList connector: investigate and implement (Python native or Node microservice — see
  Tech Stack section; flag choice for discussion)
- AnyList auth (email/password from .env) — see [Security](#security) §2 for credential storage
- Fetch current AnyList items at checklist load
- Checklist UI: per-item have/don't have taps, AnyList pre-ticking, staples integration
- "The usuals" household recurring-items checklist — design at kickoff (see
  [Checklist Screen Logic](#checklist-screen-logic) and [Deferred Decisions](#deferred-decisions))
- Ingredient unit conflict review UI (for items that cannot be auto-consolidated)
- Push to AnyList: increment existing or add new
- Save session to shopping_history
- Diagnostics: AnyList connection status populated

**Deliverable:** Full end-to-end flow works. User can complete a planning session and
push the result to AnyList.

### Phase 6 — Polish
*(Not yet chunked — break this into checkbox chunks at kickoff, following
[Phase workflow & progress tracking](#phase-workflow--progress-tracking).)*
- UI visual polish (see UI/UX section below)
- Store setup UI + store-sorted list rendering (see
  [Shopping List Store Layout](#shopping-list-store-layout) — this reverses the earlier descope
  of both shop-layout sorting and multi-store support)
- Weekly planner calendar view — drag recipes into a 7-day grid (moved here from Phase 4 at
  the 2026-09-06 Phase 4 kickoff; `day_of_week` is already set via a plain dropdown in Phase 4
  Chunk 4.4, this is the visual layer only)
- "Mark cooked" action — increment `recipes.times_made` / set `last_made_at` (moved here at
  the 2026-09-06 Phase 4 kickoff; closes the flag carried from Chunk 2.1/2.4)
- Session history log page
- Error states and empty states throughout UI
- Comprehensive diagnostics page (all indicators wired up)
- User testing with secondary users; gather feedback

---

## UI / UX

### General principles
- Mobile-first. Primary use is on Android phones in portrait orientation over local WiFi.
- The app is accessed via browser shortcut (not a PWA install), so no service worker needed.
- Rough-but-functional is acceptable for Phase 1–5. Phase 6 is the polish pass.
- Every action should have visible feedback (loading state, success confirmation, error message).
- Navigation: persistent bottom nav bar on mobile with icons for: Home, Recipes, Plan, Settings,
  Diagnostics.

### Tone & copy
- Plain language. No jargon. Sentence case everywhere.
- Actions describe exactly what happens: "Add to list" not "Submit". "Save recipe" not "Confirm".
- Error messages explain what went wrong and what to do: "Couldn't reach AnyList — check your
  connection and try again" not "Error 500".

### Accessibility
- Tap targets minimum 44px.
- Sufficient colour contrast.
- Do not rely on colour alone to convey state.

### Design direction (Phase 6 polish)
- Functional kitchen-utility aesthetic — not a food blog. Clean, fast, practical.
- Palette: neutral warm whites and greys, one functional accent colour (not terracotta/clay).
- Typography: one sans-serif family, clear hierarchy, no decorative type.
- No animations except functional transitions (e.g. checklist item ticked → slides/fades out).

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
│   │   ├── consolidation.py
│   │   ├── purchase_units.py
│   │   ├── capture_url.py
│   │   ├── capture_photo.py
│   │   ├── ai_extraction.py     ← Gemini per-task calls (was claude_client.py — renamed Phase 3.9 M1)
│   │   ├── capture_queue.py     ← 429 retry queue + hourly poller (Phase 3.9 M3)
│   │   └── anylist_client.py
│   ├── seed_data.py           ← staples + product_units + section vocabulary starter data
│   └── log_config.py          ← logging setup, in-memory ring buffer
├── alembic/                    ← DB migrations (bootstrapped Phase 3 Chunk 3.7 — see CLAUDE.md > Migrations)
│   ├── env.py                  ← wired to app.database.Base + the config sqlite:/// URL
│   └── versions/               ← one file per schema change from Chunk 3.7 onward
├── alembic.ini                 ← Alembic config (no hardcoded URL — env.py pulls it from app.config)
├── scripts/                    ← maintenance scripts, run as `python -m scripts.<name>`
│   ├── cdp.py                  ← stdlib-only headless-Edge CDP driver for frontend verification (see HEADLESS_VERIFY.md)
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

## Security

Covers the security posture for the app's deployment on the NUC. The system is
local-network-only by design — no internet exposure is required or intended. The goal is not
to harden this like an internet-facing service, but to make sure a compromised or
untrustworthy device on the home WiFi (an IoT gadget, a guest's phone) can't read AnyList
credentials or interfere with the app.

Items marked **`[Phase 1 fix]`** apply to the already-built Phase 1 app. Where the fix is
config/environment (firewall scope, Task Scheduler privilege level) it's applied at NUC
deployment time — see `SETUP.md` steps 6 and 8, which carry the concrete commands/checkboxes.
Where it's something Claude Code can just do (repo hygiene), it's done.

### 0a. Prompt Injection Hardening (highest priority)

**Set 2026-09-05 — see [Non-Negotiable Operating Rules](#-non-negotiable-operating-rules).**
Any content this app sends to an LLM that did not originate from the household's own direct
input — a scraped recipe webpage, a photographed cookbook page, or any future untrusted
source — is treated as data only, never as instructions, and the app is built to resist
attempts embedded in that content to change its behaviour. This overrides every other design
concern, including the usual `services/` "no DB" purity and "small stable interface" norms in
[Code Architecture](#code-architecture--maintainability) where they'd otherwise conflict.

Concretely, for every LLM call that includes untrusted content (post-Phase-3.9: the
extraction and substitution-flagging calls in `services/ai_extraction.py`; pre-M1:
`claude_client.py` > `extract_ingredients()`):
- The system prompt explicitly tells the model the untrusted content is data, not
  instructions, and to ignore anything inside it that looks like a request to change
  behaviour, reveal the prompt, or do anything other than extract ingredients.
- The untrusted content is wrapped in an explicit, non-guessable delimiter tag in the user
  message, so it can never be mistaken for a system-level instruction or spoof its own
  closing tag.
- Input length is capped (`MAX_INPUT_TEXT_CHARS` in `claude_client.py`) — this bounds the
  size of any injected payload, and incidentally keeps per-call cost predictable too.
- The parsed response is validated against strict expected types and, for any field with a
  fixed vocabulary (`suggested_section`), an allow-list — a hallucinated or injected value
  outside that vocabulary is discarded (set to `null`), never passed through. Never trust a
  field's content just because the JSON parsed.
- No tool-use / code execution / external actions are ever granted to an extraction call, and
  this must stay true — an injection that can only influence the JSON payload returned (which
  the user reviews and can edit before anything is saved, per
  [Recipe Capture](#recipe-capture--ai-extraction)) has a far smaller blast radius than one
  that could trigger an action.
- This same pattern (delimiter + explicit instruction + strict output validation) applies to
  any future LLM call this app adds that includes content from outside the household's direct
  input — it is not a one-off fix scoped to Chunk 3.1.

**Why:** the app's core workflow feeds arbitrary external content (webpages, photos) straight
into an LLM prompt with no human review step before that call happens — a textbook prompt
injection surface. Erring on the side of caution here costs little (a delimiter, a stricter
parse) and closes off a class of failure that would otherwise be easy to miss until it's
exploited.

### 0b. API Usage Observability (no hard cap)

> **⚠️ Provider change (Phase 3.9 M5) — [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39).**
> Gemini's free tier has no per-call dollar cost, so **all** USD-spend observability is
> removed at M5: `calculate_cost_usd_cents`, `cost_usd_cents`, the diagnostics "spend
> tracker" + its reset button, and the `api_usage` / `api_usage_resets` tables. Replacement:
> the [`ai_call_log`](#ai_call_log) table + a **daily quota usage indicator** (observed
> request count per model) + a **recent capture-attempt log**. §0a prompt-injection hardening
> and §0c enable-switch / fake-mode / ask-first **carry over verbatim**. The prose below
> describes the pre-M5 Claude code, still live until then.

**Set 2026-09-05, revised 2026-09-06.** This section originally documented a hard AU$0.50
lifetime spend cap enforced in code (`enforce_spend_cap()`, `MAX_API_SPEND_AUD_CENTS`,
`SpendCapExceededError`). **That cap has been removed** — it was based on a mistaken
assumption that Anthropic API billing is an open-ended postpaid invoice that could run away
unnoticed. It isn't: calls are billed against credit purchased upfront, so the account's own
prepaid balance is already the real ceiling, and an additional in-app dollar cap wasn't
protecting against anything that couldn't otherwise happen. There is no cap-related
`Security §0b` mechanism to follow any more, and none should be re-added without the
maintainer explicitly asking for it again.

What stays, because it's genuinely useful independent of any cap:

- `app/services/api_usage.py` still calculates the USD cost of every call
  (`calculate_cost_usd_cents()`) and logs it to the `api_usage` table
  (`log_api_usage()`) — `claude_client.py` > `extract_ingredients()` still calls
  `log_api_usage()` immediately after every real call, including when the response turns out
  to be unparseable, so the log is never missing a call that Anthropic actually billed.
- `GET /api/v1/diagnostics/status` still reports running token totals and estimated USD spend
  on the `claude_api` block, plus a reset-with-confirmation action
  (`POST /api/v1/diagnostics/reset-spend`) so the maintainer can zero the *displayed* running
  total when they want a fresh view (e.g. starting real Chunk 3.6+ usage) — this only inserts a
  reset marker (`api_usage_resets` table); it never deletes or edits `api_usage` rows
  themselves, so the underlying log stays a genuine append-only record of every call ever made
  (see [Data Model](#data-model) > `api_usage`).
- This is pure observability, not enforcement — nothing in the app refuses a call because of
  cost. **The actual guardrails against unwanted spend are the enable switch and fake mode in
  §0c below** — never write a new dollar-cap mechanism in place of this section without being
  asked to.

**Why keep the logging at all, then?** Because "no hard cap" isn't "don't bother tracking
cost" — the maintainer still wants to see what recipe capture actually costs in practice, and
that number is cheap to keep accurate now that it's already wired through every real call.

### 0c. API Enable Switch & Offline Development (highest priority)

> **⚠️ Names change at Phase 3.9 M1, semantics unchanged
> ([AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39)):**
> `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`, `CLAUDE_API_FAKE_MODE` →
> `AI_EXTRACTION_FAKE_MODE`, and the check moves from `claude_client.extract_ingredients()`
> to `ai_extraction.py`'s per-task call functions. Everything below applies verbatim to
> Gemini — off by default, no agent flips it, ask before any real call, fake mode bypasses
> everything. Phase 3.9 M1–M6 build entirely in fake mode; **M7** is the single live call.

**Set 2026-09-05, still in force after the 2026-09-06 spend-cap revision above.** Two
mechanisms push the real API's involvement in building this app as close to the very end as
possible, and give the maintainer explicit, deliberate control over when it's used at all —
this is the part of the original rule set that actually did the job the spend cap was
mistakenly added alongside:

**The enable switch.** `CLAUDE_API_ENABLED` in `.env`, defaulting to `false`. Checked in
`claude_client.py` > `extract_ingredients()` before anything else — a configured key alone is
not enough; a real call also needs this explicitly set to `true`. Raising it is the
maintainer's action alone, taken in `.env`: **no agent session may set this to `true` on its
own initiative, ever, including when a task description asks for a real API call to be made.**
Separately, and just as binding: an agent session must ask the maintainer in conversation
before running anything that would make a real call, even once this switch is on — the switch
protects the app; asking protects against an agent deciding "close enough to permission" on
the maintainer's behalf.

**Fake mode.** `CLAUDE_API_FAKE_MODE` in `.env`, defaulting to `false`. When `true`,
`extract_ingredients()` returns a canned fixture (one of a small set of generic sample
recipes, picked deterministically from a hash of the input — same input always gives the same
fixture, different inputs land on different ones) instead of calling the real API at all. Zero
network, zero cost, no key required, bypasses the enable switch entirely because nothing
billable happens. Must never be `true` outside local development.

**Even with no hard cap, minimising real calls during development still matters** — every real
call has a real (if now unbounded-by-code) cost, and there's no reason to spend anything at all
on a call whose only purpose is checking that a button renders correctly. Fake mode and the
enable switch remain the mechanism for that, same as before 2026-09-06 — nothing about their
behaviour changed, only the (now-removed) cap that used to sit alongside them.

**What this buys, concretely — restructuring Phase 3 so the real key is needed exactly once:**
almost none of Phase 3's remaining work actually depends on a real Claude response:
- Chunks 3.2/3.3 (capture endpoints): the fetch/parse/upload logic has nothing to do with
  Claude; only the final `extract_ingredients()` call does, and fake mode covers that for
  manual click-through testing the same way a mocked SDK client covers it in automated tests.
- Chunk 3.4 (review UI): operates entirely on whatever extraction result it's handed — a real
  one or a fixture look identical to this layer. Fully buildable and clickable-through with
  fake mode on.
- Chunk 3.5 (diagnostics wiring): the enable/fake-mode/spend-observability fields are
  exercised by writing directly to `api_usage` in tests, not by real calls.
- **One live check, at the very end of the phase, not spread across it.** After 3.2-3.5 are
  built and manually verified with fake mode, a single explicit "does this actually work
  against the real API" pass is what Chunk 3.1's own verification step becomes — see the Phase
  3 chunk list, where this is now its own final chunk rather than a Chunk 3.1 blocker. It
  needs, in order: a real key added to `.env` (maintainer's action), `CLAUDE_API_ENABLED=true`
  (maintainer's action), and the maintainer's go-ahead in conversation for that specific call
  (agent's obligation to ask, per above). Cost is a few USD-cents — no cap to stay inside of
  any more, but still no reason to make more than the one call this chunk needs.

**Why:** the maintainer asked directly — "how much of the development can be restructured to
be developed without the API key" — and the honest answer turned out to be "nearly all of it."
Treating that as the default going forward (for this integration and any future one) means the
real API is something the app is deliberately, explicitly switched on to use, not something
that's live by accident because it was never obviously off.

### 1. Network exposure
- The server binds to `0.0.0.0` so it's reachable from phones on the LAN. Required for the
  intended use case, but it means anything else on the WiFi can also reach it.
- **Do not port-forward port 8080 on the router.** There is no reason for this app to be
  reachable from the internet, ever.
- **`[Phase 1 fix]`** Scope the Windows Firewall inbound rule for port 8080 to the home LAN
  subnet (e.g. `192.168.1.0/24`) and the Private profile, rather than any/all. Applied at NUC
  setup — see `SETUP.md` step 6 for the exact `netsh` commands.
- If the router supports a separate IoT/guest VLAN, keep smart-home devices on that VLAN and the
  NUC off it, so those devices can't reach port 8080 at all.

### 2. AnyList credentials (Phase 5, plan ahead now)
- AnyList's API is unofficial and reverse-engineered — a straight username/password login, not
  OAuth/token-based. That password should be treated as sensitive as an email password: a leak
  means someone can read and write the shared household list.
- **Never commit credentials to source control.** `.env` is in `.gitignore` as of Phase 1 —
  done, ahead of Phase 5 introducing the real credential.
- Preferred storage: Windows Credential Manager via the `keyring` Python package, rather than a
  plaintext `.env` file. `.env` is acceptable as a fallback if `keyring` proves awkward with the
  deployment scripts, but it should sit outside any directory that gets backed up/synced
  unencrypted. **This choice is not yet made — decide at the start of Phase 5** (also
  tracked in [Deferred Decisions](#deferred-decisions)).
- If the Node.js microservice fallback (Tech Stack > AnyList) is used, it must bind to
  `127.0.0.1` only — never `0.0.0.0`. It should only ever be called by the Python backend on
  the same machine, never be reachable from the LAN.

### 3. Windows 10 host
- Win10's end-of-support concerns are mainly about internet-facing exposure. Since this stays
  LAN-only, the realistic risk is a compromised device already on the WiFi, not an external
  attacker — so firewall scoping (§1) is the main mitigation, not OS patching urgency.
- Keep Windows Update running normally; don't disable Defender or the firewall for convenience
  during development (easy to forget to re-enable).
- **`[Phase 1 fix]`** Run the app as a standard user, not admin — limits the damage if a
  dependency ever has a vulnerability. Neither binding port 8080 (only sub-1024 ports need
  elevation) nor writing to the project's own folders needs admin rights. Applied at NUC setup
  — see `SETUP.md` step 8 (Task Scheduler task explicitly leaves "Run with highest privileges"
  unticked).

### 4. App-level
- **`[Phase 1 fix]`** CORS is scoped, not wide open. The initial build used
  `allow_origins=["*"]`, which — combined with there being no login at all — meant any
  origin's JavaScript (an ad, a compromised site, anything open in a browser tab on the same
  WiFi) could call the API cross-origin and read or write responses. `ALLOWED_ORIGINS` in
  `.env` now controls this (`app/config.py`, consumed in `app/main.py`'s `CORSMiddleware`),
  defaulting to `localhost`/`127.0.0.1` for dev. **Add the NUC's static IP to it once step 5
  of `SETUP.md` assigns one** — see that step for the exact line to add.
- No login system is fine for the household use case, but since any device on the WiFi can reach
  the API, a single shared basic-auth password on the API routes would be a cheap extra barrier
  against IoT devices or guests poking at it. **Optional, not a `[Phase 1 fix]`** — flagged as a
  recommendation, not built (see [Deferred Decisions](#deferred-decisions)). CORS scoping above
  is a partial, free complement to this, not a replacement for it.
- Recipe URL scraping (httpx + BeautifulSoup) fetches external, untrusted HTML. Not a credential
  risk, but don't ever `eval()` or execute anything derived from scraped content — parse it as
  data only, which is already the plan.
- Light access logging on `/api/v1/*` (especially the future AnyList routes) is worth having —
  not for compliance, just so an unexpected access pattern from an unfamiliar device is visible
  if it ever happens.

### 5. Deployment/Task Scheduler
- **`[Phase 1 fix]`** Any Task Scheduler task auto-starting the server (or running the weekly
  backup) leaves "Run with highest privileges" unticked unless there's a specific reason it's
  needed. Applied at NUC setup — see `SETUP.md` steps 8 and 9.
- Keep the venv and any secrets outside of any folder that Plex or other services on the NUC
  might expose (e.g. a Plex media/share folder) — accidental exposure through an unrelated
  service is an easy thing to miss on a multi-purpose box.

---

## Backup & Restore

**Build now (Phase 1)** — Schema & Planning Addendum #4.

- **Frequency:** weekly, via Windows Task Scheduler (`SETUP.md` step 9) — same mechanism as the
  auto-start task, no new infra.
- **What's backed up:** the SQLite `.db` file, copied verbatim with a timestamp, plus a
  plain-text JSON dump of every table alongside it (`scripts/backup.py`, `dump_db_to_json`).
  The JSON dump is what makes diffs meaningful in git — the raw `.db` file is an unreadable
  binary blob there.
- **Images:** excluded from the backup. Not versioned, not copied. Treated as
  lower-priority/regenerable.
- **Retention:** the 12 most recent backup pairs are kept locally; older ones are trimmed
  automatically on each run.
- **Destination:** a `backups/` folder in the project root (not gitignored). If the project is
  a git repository with an `origin` remote configured, `scripts/backup.py` also commits and
  pushes `backups/` automatically — this is the offsite copy. If there's no repo yet, or no
  remote, it logs a warning and stops there rather than failing the backup. See `SETUP.md`
  step 10 for connecting the private GitHub repo.
- **Credentials:** `.env` stays gitignored, never included in the backup or repo.
- **Restore path:** `scripts/restore.py` / `restore.bat`. Never overwrites without an explicit
  `--yes`; always saves a pre-restore copy of the current database first. **Actually tested
  during Phase 1** — run once end-to-end (list → dry run → `--yes` restore) rather than assumed
  to work when it's needed under pressure.

---

## Deferred Decisions

These items arose during planning and were explicitly parked for later. Do not implement them
speculatively. When the relevant phase begins, flag these for a focused decision.

| Item | Deferred to | Notes |
|---|---|---|
| Australian pack size rounding for weight/volume | ~~Phase 4 discussion~~ **Resolved 2026-09-06 — option 2 (calculate exactly, show overage)** | e.g. "needs 340g → buy 400g can, 60g over". Scaling keeps the true quantity; whole-pack rounding + overage live only in purchase-unit resolution. No pack-size reference data set needed. See [Scaling Logic](#scaling-logic) and the Decision Dialogue; builds in Phase 4 Chunks 4.3 / 4.6. |
| Partial quantities UX | Phase 5 | Implement binary have/don't have for now. Revisit if needed. |
| Free-text unit scaling (`can`, `bunch`, `clove`, `sprig`…) | Revisit after real use | 2026-09-06 grilling: anything not in {g,kg,ml,L,tsp,tbsp,cup} / `NO_SCALE_UNITS` is scaled as **discrete** (ceil to whole). Maintainer: "sounds good on paper, might come back to bite me — go with it for now, flag as a review item." See [Scaling Logic](#scaling-logic). |
| Default target servings as a Settings field | Not scheduled | 2026-09-06: `DEFAULT_TARGET_SERVINGS = 4` is a constant (form pre-fill, always overridable per recipe). If the household size changes often enough to matter, promote it to an editable Settings value. Needs a general app-settings store (Settings today is only staples + product_units CRUD). See [Scaling Logic](#scaling-logic). |
| Countable item purchase unit thresholds | Phase 4 | e.g. "need 6 eggs, buy a dozen?". **Design resolved 2026-09-05, implementation still pending Phase 4:** folded into the general multi-pack-size resolution algorithm — see [Purchase unit resolution](#scaling-logic) and the [`product_units`](#product_units) schema note. No separate special case needed once an ingredient can have more than one seeded pack size. |
| Ingredient synonym normalisation (automatic) | Phase 6 or later | e.g. "green onion" vs "spring onion". For now, user review at capture time provides sufficient normalisation. |
| Multi-user login / separate accounts | Post-MVP | Shared access, no auth. |
| AnyList credential storage: `keyring` vs `.env` | Phase 5 kickoff | Preferred: Windows Credential Manager via `keyring`. `.env` acceptable fallback if awkward with deployment scripts. See [Security](#security) §2. |
| Shared basic-auth on API routes | Optional, any phase | Cheap extra barrier against other devices on the WiFi. Recommended but not required at current trust level; not built. See [Security](#security) §4. |
| "Suggest something" — recency/variety suggestion logic + UI | Phase TBD (confirmed still deferred at Phase 4 kickoff, 2026-09-06 — not brought into Phase 4) | Schema prep (`cuisine`/`protein` on recipes) is done (Phase 1). Signal is recency + variety, surfaced via an on-demand button, not a proactive nudge. Logic and UI not designed yet — revisit once sessions + "mark cooked" exist to feed it real data. |
| "Mark cooked" — `times_made` / `last_made_at` increment | ~~Phase 2 onward / phase TBD~~ **Resolved 2026-09-06 at Phase 4 kickoff — Phase 6** | Flag carried from Chunk 2.1/2.4: the columns exist since Phase 1 but nothing writes them. A real "cooked" event is post-push (Phase 5+), so the small "mark cooked" action lands in the Phase 6 polish pass, not Phase 4. Feeds "Suggest something" (row above) when that is picked up. |
| Weekly planner calendar view (drag recipes into a 7-day grid) | ~~Phase 4~~ **Resolved 2026-09-06 at Phase 4 kickoff — Phase 6** | `day_of_week` is set in Phase 4 via a plain dropdown (Chunk 4.4). The visual calendar layout is a Phase 6 polish item — the engine does not need it. |
| "Substitution flagging" review step / Ingredient substitution | ~~Resolved 2026-09-05 — option 2 (doesn't exist; not built)~~ **Superseded 2026-09-06 — real feature, in scope for Phase 4** | The 2026-09-05 resolution was correct on its own narrow question (the Shop Layout addendum's reference genuinely was a mistaken cross-reference, and Phase 3's Chunk 3.4 correctly shipped with no suggestion mechanism). A follow-up conversation surfaced that a related, genuinely-wanted feature had been lost in that resolution: letting the user substitute an obscure/hard-to-find ingredient (e.g. "bulgarian feta" → "regular feta") for shopping purposes — ad-hoc per-session, or remembered without repeated prompting, easily reversible. Fully designed — see [Ingredient Substitution](#ingredient-substitution) and the [`ingredient_substitutions`](#ingredient_substitutions) table. Not yet implemented — lands when Phase 4 is chunked and built. |
| Bulk ingredient rename/merge across recipes | Possible future follow-up, not scheduled | Raised alongside [Ingredient Substitution](#ingredient-substitution): if a recipe's ingredient text needs a genuine *correction* (not a substitution) and the same wrong text appears in several recipes, there's no bulk find-and-replace — each recipe is edited individually via the existing editor ([Chunk 2.4](#phase-2--recipe-library)). Confirmed 2026-09-06 that per-recipe editing is good enough for now; flagged here in case it becomes a real friction point. |
| Duplicate recipe prevention | **Designed 2026-09-06 — build in Phase 4** | Warn-with-override (never a hard block) when a save looks like a recipe the library already has. Signals: `source_url` exact, name exact, `source_book`+`source_page` overlap, conservative stdlib fuzzy name. Full design in [Duplicate Recipe Prevention](#duplicate-recipe-prevention); becomes a Phase 4 chunk at kickoff. Residual deferred piece: the **ingredient-set overlap** signal is *not* in the Phase 4 build — revisit only if near-dupes still get through afterwards. Fuzzy threshold and whether to build the live `check-duplicate` endpoint are Phase 4 kickoff details. |
| Store deletion/merge | Post-MVP / low priority | Not designed — add if it comes up. See [Shopping List Store Layout](#shopping-list-store-layout). |
| Section vocabulary — final list | Confirm before Phase 6 store-setup UI is built | Starter list seeded in Phase 1 (`app/seed_data.py > SECTION_VOCABULARY`) is provisional. See [Section Vocabulary Starter List](#section-vocabulary-starter-list). |
| Multi-shop support | ~~Post-MVP~~ **Resolved — now in scope** | See [Shopping List Store Layout](#shopping-list-store-layout). Kept here only so the reversal isn't missed by anyone skimming old notes. |
| Shop layout reorganisation (list sorting by aisle) | ~~Phase 6 or post-MVP~~ **Resolved — now in scope** | See [Shopping List Store Layout](#shopping-list-store-layout). Kept here only so the reversal isn't missed by anyone skimming old notes. |
| Home tab content | Needs a decision, no later than Phase 6 polish | Still the Phase 1 stub ("Phase 1 foundation is running..."). What it should actually show (recent sessions? quick actions? current shopping list status?) was never designed anywhere in this document — it's a nav placeholder, not a deliberately-deferred landing page. Flagged 2026-09-05 via user testing. |
| Settings list re-render loses scroll position on Save/Delete | Bug — fix opportunistically, no later than Phase 6 | `static/js/settings.js`'s `load()` rebuilds the whole staples/product-units row list (`innerHTML = ""` + re-append) after every Save/Delete, which resets scroll to the top of the page — noticeable and frustrating once a list has more than a few rows. Fix should update/remove the affected row in place rather than a full-list re-render, or otherwise preserve scroll position across the rebuild. Flagged 2026-09-05 via user testing (Chunk 2.5), not yet fixed. |
| Git branching strategy: `production` / `develop` branches | ~~Phase 2 review~~ **Resolved 2026-09-05 — option 2 (`develop` + `production`)** | `deploy.bat`/`scripts/deploy.py` (dev PC, ships from `develop`, fast-forwards `production`) and `update.bat`/`scripts/update.py` (NUC, pulls `production` only) updated and verified against a sandbox origin+dev+NUC repo trio, including the diverged-`production`-from-a-backup-commit failure/recovery path. `backup.py` needed no logic change (already branch-agnostic via `HEAD`). Local `main` renamed to `develop`, `production` branched off it — **pushing both to origin and updating GitHub's default branch is still a manual step for the maintainer** (Claude Code creates commits but never pushes, see [Commits](#commits)); see `DEPLOY.md > One-time setup` for the exact commands. Full workflow in `DEPLOY.md`. |
| "The usuals" — recurring non-recipe household items checklist | Phase 5 kickoff | e.g. laundry powder, dishwashing liquid — bought periodically regardless of what's being cooked. Distinct from `staples` (recipe ingredients assumed on hand, surfaced only when a recipe needs them this session). Needs its own storage decision, a cadence decision (every session vs. periodic), and a decision on whether it's part of the existing checklist UI or a separate step. See [Checklist Screen Logic](#checklist-screen-logic). |
| AI pre-fill of cookbook name / page from a photo | Revisit if hand-entry proves tedious | Phase 3 Chunk 3.7 collects `source_book` / `source_page` via manual review-screen inputs and deliberately does not extend the extraction prompt to OCR them (unreliable; every new prompt field costs fresh [§0a](#0a-prompt-injection-hardening-highest-priority) output-validation work). If typing them every capture turns out to be annoying, add best-effort `suggested_book` / `suggested_page` to the prompt with allow-list-style validation. Same standing as any other not-yet-needed feature — no reserved phase. See [Recipe Capture](#recipe-capture--ai-extraction). |
| MyFitnessPal recipe export | Post-MVP / unscheduled | Secondary user wants recipes in MFP for macro tracking. Design done: app generates a clean recipe for MFP's built-in Recipe Importer; no push API, no macros held in the app. See [Nutrition & MyFitnessPal Export](#nutrition--myfitnesspal-export). Do not build speculatively; re-verify the MFP-API status when picked up. |
| Nutrition read-back into the app (per-recipe macros) | Post-MVP / unscheduled | Recipe→MFP export (row above) is the in-scope design. Reading macros *back* has no API path — only MFP scraping — so it's parked with the fragility/ToS trade-off to weigh, and needs a derisking spike if adopted. Independent in-app estimation (USDA FoodData Central / Claude / manual `ingredient_nutrition` table) set aside 2026-09-06: the ask is specifically MFP, and a non-matching estimate is a second source of truth; unit conversion (tsp/tbsp/cup/"each" → grams) is the hard part. See [Nutrition & MyFitnessPal Export](#nutrition--myfitnesspal-export). |
| Local LLM (Ollama) fallback for AI extraction | Future phase, not scheduled | Placeholder direction if the Gemini dependency ever must go entirely (cost/privacy/availability). Ollama native on the NUC (Windows, no Docker); candidates `llama3.2-vision` / `qwen2-VL` / `moondream2`. Trade-offs to check against real NUC hardware then: weaker messy-handwriting OCR, latency depends on GPU vs CPU-only. **No Ollama deps or code paths now.** See [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini). |
| Gemini free-tier data usage | Unresolved — revisit before the AI-extraction feature is signed off | On Gemini's free tier, recipe photos/text may be used by Google to improve their products; enabling Cloud Billing (even at $0 under free quota) stops this. Decision: is adding a Google Cloud payment method viable (unlike Anthropic), and worth it purely for the privacy improvement? See [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini). |
| Combine the 3 per-task Gemini calls into 1 | Revisit only if daily quota pressure is real | The [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39) deliberately keeps extraction / substitution-flagging / section-suggestion as **separate** Gemini calls (independent prompts, schemas, failure handling — diagnostics-first). Uses more quota; do **not** pre-optimise. |
| 1-to-many ingredient substitutions as structured data | Not scheduled | Merge decision #5 (2026-09-06): `remembered_substitutions.substitute_name` and `recipe_ingredients.resolved_ingredient` are a single freetext string; `buttermilk → "milk + lemon juice"` is stored verbatim and the user splits it by hand if they want. Making a resolved ingredient a real *list* ripples into scaling / consolidation / pack-resolution counting — revisit only if the freetext approach proves annoying in practice. See [AI Provider Migration > Ingredient Substitution Flagging](#ingredient-substitution-flagging--the-merged-spec). |

### Decision Dialogues

When a deferred decision comes due, use the relevant dialogue below to guide the discussion. The Q is
the prompt to raise with the maintainer; the A options are what to ask about; Expected Outcome is what
decision gets documented in this file once made.

#### Australian pack size rounding (Phase 4 kickoff)

**Q:** When a recipe needs 340g of an ingredient and the only seeded pack size is 400g, should we:
- Buy the 400g (overage 60g)
- Or round the requirement UP to 400g before buying, rounding up the quantity too?

**A options:**
1. Always round-trip: scale the consolidated quantity up to the nearest available pack, then resolve purchases. (e.g. need 340g → round to 400g → buy one 400g pack)
2. Calculate exactly: keep the 340g, then resolve to "buy one 400g pack which is 60g overstock". Show the overstock to the user.
3. Defer to Phase 5: ship Phase 4 without this, wire it up when AnyList integration happens and real usage emerges.

**Context:** This is a real-world impact — Australian grocery pack sizes aren't designed around metric halvings. The user will notice if the planner is suggesting weird quantities. Requires either a reference data set of common pack sizes or an algorithm to prefer whole packs and understock avoidance.

**Expected outcome:** Decision + implementation approach documented in [Scaling Logic](#scaling-logic).

**Resolved 2026-09-06 (Phase 4 kickoff) — option 2 (calculate exactly, show overage).**
Keeps `scaling.py` pure and free of pack-size reference data; the multi-pack resolution
algorithm in [Scaling Logic > Purchase unit resolution](#scaling-logic) already does the
whole-pack cover job. Option 1 would double-round and distort consolidation inputs; option 3
was unnecessary since the algorithm shape was already settled. Folded into
[Scaling Logic](#scaling-logic) and Phase 4 Chunks 4.3 / 4.6.

---

#### Scaling: rounding location & rules (Phase 4 kickoff)

**Resolved 2026-09-06 in a detailed grilling with the maintainer. Folded into
[Scaling Logic](#scaling-logic); this is the record of intent.**

**Q:** CLAUDE.md originally had `scaling.py` scale *and* round (nearest 25 / nearest 5 /
nearest 0.5). Is that what's wanted, and where should rounding actually happen?

**Context gathered:** scaling is *rare* (household target is 4 servings = 2 adults ×
dinner + next-day lunch, which is also the usual `base_servings`, so factor is normally
1.0). The end artifact is a shopping list. The maintainer's instinct: "remove as much admin
as possible", "I don't want this to be a round-to-x question", "tolerances", and a specific
worry that a bare `passata` line with no quantity would lead to buying the wrong amount.

**Decisions:**
1. **`scaling.py` only multiplies.** No rounding, no unit conversion, no pack logic. All of
   that moves to `consolidation.py` / `purchase_units.py` and runs **once, on the summed
   quantity** — not per-recipe-then-summed (which rounds twice and compounds drift).
2. **Round UP, never to nearest.** Clean steps (ceil to 25 for g/ml ≥ 100, ceil to 5 below,
   ceil to whole for counts) so numbers are tidy but a shopping quantity is *never short*.
   This is the "tolerance" the maintainer was reaching for.
3. **`cup` is not clean-rounded** — 2-decimal trim only (a scaled cup is ~always < 1, where
   "nearest 5" would zero it). Chosen from options {nearest 0.25, nearest 0.5, no rounding}.
4. **Australian volume conversions are defined and volumes DO merge**: `tsp`=5 ml,
   `tbsp`=**20 ml** (AU tablespoon), `cup`=250 ml, `kg`=1000 g, `L`=1000 ml. Only
   weight-vs-volume for one ingredient stays irreconcilable (no density data) → flagged,
   both parts shown, review UI is Phase 5.
5. **Discrete items always round up, including when scaling down** (3 eggs → 2 serves = 2
   eggs, not 1) — safety over waste, the maintainer's explicit call. `½ onion` → `1`.
6. **Free-text units** (`can`, `bunch`, `clove`…) → treated as discrete, ceil-to-whole.
   Acknowledged as "sounds good on paper, might bite" → [Deferred Decisions](#deferred-decisions)
   revisit-after-use item.
7. **Required quantity is never hidden.** No-pack-size line shows the amount; pack-size line
   shows both the pack breakdown *and* `need ~X`. Overage shown only when > ~half a pack.
8. **Multi-pack resolution seeded from day one** (eggs/milk/yoghurt) and properly tested,
   not dormant — small deliberate departure from the "don't pre-enumerate" note.
9. **Re-consolidation merges**, preserving `have_it` / `add_to_list` per line; never a wipe.
10. **Default target servings = 4**, a `DEFAULT_TARGET_SERVINGS` constant (form pre-fill,
    always overridable). Making it a Settings field is a [Deferred Decision](#deferred-decisions).

---

#### AnyList credential storage: `keyring` vs `.env` (Phase 5 kickoff)

**Q:** Where should we store the AnyList email and password?

**A options:**
1. Windows Credential Manager via the `keyring` Python package (preferred, more secure)
2. `.env` file in the project root, `.gitignore`'d but unencrypted on disk
3. Hybrid: try `keyring` on startup; if it fails, fall back to `.env` with a warning

**Context:** AnyList password is as sensitive as an email password — a leak means someone can read/write the shared household list. See [Security](#security) §2. The `.env` fallback makes deployment simpler if `keyring` proves awkward with the batch scripts.

**Expected outcome:** Decision + implementation (credential retrieval in `app/config.py`) + any deployment script changes documented in `SETUP.md` or `DEPLOY.md`.

---

#### Git branching strategy: `production` / `develop` branches (Phase 2 review)

**Resolved 2026-09-05 — option 2.** See the [Deferred Decisions](#deferred-decisions) table
row above for what was implemented and verified, and `DEPLOY.md` for the full workflow. Kept
below for the record of what was asked and why.

**Q:** Should we introduce stable/development branch separation to prevent breaking the running app?

**A options:**
1. Keep single `main` branch. Low complexity, okay because the maintainer runs verified phases before moving to production.
2. Introduce `develop` (active work) and `production` (NUC-deployed stable) branches. Updates to deployment scripts (`deploy.bat`, `update.bat`) and backup/restore to target the correct branch.
3. Introduce `main` (stable) and `develop` (active work) branches, flipping which is primary. Same complexity as option 2, different naming.

**Context:** Currently a single `main` branch works fine because Phase work is chunked and tested before the next phase starts. As complexity grows (or if dev/NUC work happens in parallel), separate branches prevent the running app from being broken by in-progress work. Requires coordination updates across multiple shell scripts.

**Expected outcome:** Decision + any branch/script changes. If adopted, update `DEPLOY.md` with the new workflow and `deploy.bat`/`update.bat` with the correct branch targets.

---

#### "The usuals" — recurring household items (Phase 5 kickoff)

**Q:** How should we handle recurring non-recipe household items (laundry powder, dishwashing liquid, etc.) that are bought on a schedule independent of meal planning?

**A options:**
1. **Separate table + optional session step.** New `usual_items` table (like `staples`, but not ingredient-linked); offered as an optional pre/post-checklist step. User selects which items to add to this session's list.
2. **Separate table + always-offered.** Same table, but offered on every session (or every N sessions on a cadence).
3. **Fold into `staples` logic.** Reuse `staples` with an added `is_recipe_ingredient` flag; surface "the usuals" when requested, separately from recipe-triggered staples.
4. **Manual only.** Skip the feature entirely; user adds these items directly to AnyList when needed. Simpler, lower scope, acceptable if the household prefers it.

**A sub-questions (if not option 4):**
- **Cadence:** Every session, weekly, monthly, user-selectable, or user manual-trigger?
- **UI integration:** Part of the existing checklist flow, or a separate optional screen?

**Context:** Raised 2026-09-05 during user testing — the household does buy recurring items that don't fit recipes. It's a distinct workflow from recipe staples. Currently undesigned.

**Expected outcome:** Decision on which option + cadence/UI integration details. Implementation lands in Phase 5 (or defer further if option 4).

---

#### "Substitution flagging" review step (Before Phase 3 AI extraction)

> **Third turn, 2026-09-06 (AI Provider Migration addendum):** substitution flagging is now
> back to being a **capture-time, per-recipe, confirmation-required** feature — much closer
> to the *original* 2026-09-05 framing than to the Phase 4 "global remembered rules" design.
> See [AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini). The
> two notes below are kept as the record of the earlier two turns.

**Superseded 2026-09-06 — see [Ingredient Substitution](#ingredient-substitution).** The
resolution below answered the question as originally asked (was there a pre-existing feature
Phase 3 should reuse?) correctly — there wasn't. But a follow-up conversation surfaced that a
related, genuinely-wanted feature had been lost in the process of resolving that narrower
question: not a Phase 3 extraction-review concern, but a Phase 4 planning-time one — letting the
user substitute an obscure/hard-to-find ingredient for shopping purposes without repeated
prompting, and easily reverse it. See [Ingredient Substitution](#ingredient-substitution) for the
real design and the [Deferred Decisions](#deferred-decisions) table for the current status. The
2026-09-05 resolution below is kept as-is for the historical record of what was actually asked
and answered at the time.

**Resolved 2026-09-05 — option 2 (doesn't exist; not built).** No prior substitution-suggestion
feature exists anywhere in this document — the Shop Layout addendum's reference was a mistaken
cross-reference, not a pointer to a real feature. Phase 3's Chunk 3.4 review UI is a fresh
ingredient + section review: editable name/qty/unit/preparation (same inline-edit pattern as the
Phase 2 recipe editor) plus `suggested_section` (editable dropdown), `cuisine`, `protein` — no
"can't find beef mince, try chicken mince?" suggestion mechanism, no supporting service. Rationale:
building a suggestion service now would be speculative scope the same way pre-guessing the full
staples list or pack-size rounding would be (see [Staples Starter List](#staples-starter-list),
[Deferred Decisions](#deferred-decisions)) — there's no evidence yet of which substitutions would
actually be useful, and the user already reviews/edits every extracted ingredient manually, which
is the same reasoning [Ingredient Normalisation](#ingredient-normalisation) already uses to skip
automatic synonym matching. Not reserved as a dedicated future-phase item; revisit only if a real
gap turns up in use, same standing as any other not-yet-needed feature. Kept below for the record
of what was asked.

**Q:** What is "ingredient substitution flagging," and does it exist as a real feature that Phase 3's extraction prompt should reuse?

**A options:**
1. **It exists.** There's a prior review UI for suggesting/flagging ingredient substitutions (e.g. "can't find beef mince, how about chicken?" or "too expensive, try budget option?"). Phase 3 should reuse that same review step for section suggestions.
2. **It doesn't exist.** The Shop Layout addendum reference was a mistaken cross-reference. Phase 3 should just build a fresh ingredient + section review UI, no substitution flagging.
3. **Future feature.** It's not built yet, but worth designing alongside Phase 3 so both reviews can share a common pattern.

**Context:** The Shop Layout addendum assumes this feature exists as prior context for reusing its review UI, but it's not specified anywhere else in CLAUDE.md. Needs clarification before the Phase 3 extraction prompt is written (see [Recipe Capture](#recipe-capture--ai-extraction)).

**Expected outcome:** Clarification + Phase 3 prompt updated accordingly (or substitution-flagging designed as a separate small feature alongside Phase 3).

---

#### Shared basic-auth on API routes (Optional, any phase)

**Q:** Should we add a simple shared password on `/api/v1/*` endpoints as a cheap barrier against other LAN devices?

**A options:**
1. Yes, add it now (before the app goes into regular use). Single shared password in `.env`, checked on every request.
2. Skip it. CORS scoping + the local-network-only design is sufficient. If a real threat emerges, add it then.
3. Add it only if the household is on a shared WiFi (dorm, apartment) where untrusted devices are common. Skip if it's a trusted home network only.

**Context:** See [Security](#security) §4. Not required for the current trust level, but cheap insurance if the NUC will be on a shared WiFi. The maintainer's trust level should be the deciding factor.

**Expected outcome:** Decision documented in [Security](#security) §4, and if adopted, implementation in `app/main.py` + .env template update.

---

#### Home tab content (No later than Phase 6 polish)

**Q:** What should the home screen actually show? (Currently just a Phase 1 stub: "Phase 1 foundation is running...")

**A options:**
1. **Recent sessions.** List of the last 5–10 planning sessions, tappable to resume/view. Quick action buttons for "New session", "New recipe".
2. **Current status snapshot.** Summary of active session (if any) + last pushed list date + quick access to settings/diagnostics.
3. **Quick actions only.** Large tappable buttons: "New session", "Browse recipes", "View diagnostics". Minimal, uncluttered.
4. **Activity feed.** Show recent session events + pushed items + recipe captures. More informative but more complex.

**Context:** Flagged 2026-09-05 during user testing — the home screen was never actually designed, just left as a nav placeholder. By Phase 6 polish, it needs a real purpose.

**Expected outcome:** Decision on layout + content. Update `static/js/home.js` (or rename if the current file gets repurposed) + `static/index.html` navigation accordingly.

---

#### Settings list re-render scroll position (Fix before Phase 6)

**Q:** How should we preserve scroll position when the settings list refreshes after Save/Delete?

**A options:**
1. **In-place DOM updates.** When saving/deleting a row, update or remove just that element (DOM manipulation) instead of rebuilding the whole list. Preserves scroll + faster visual feedback.
2. **Scroll restoration.** Keep the full re-render, but save `window.scrollY` before it, then restore after. Simpler to implement, still preserves user's reading position.
3. **Pagination/virtual scroll.** Split the lists into pages or lazy-load rows. Overkill for the expected list size, but clean long-term.

**Context:** Currently `static/js/settings.js`'s `load()` does `innerHTML = ""` + re-append on every Save/Delete, resetting scroll to top. Noticeable and frustrating once a list has more than ~10 rows. Flagged 2026-09-05, not yet fixed.

**Expected outcome:** Fix implemented + verified with a ~20-row staples/product-units list. Option 1 preferred (UX + performance), but option 2 is fine if easier.

---

#### "Suggest something" — recency/variety logic + UI (Phase TBD — bring forward?)

**Q:** When should we implement the "suggest a recipe" feature, and what algorithm should it use?

**A options:**
1. Phase 4 (with planning sessions). Surface via a button in the session view; suggest the least-recently-made, highest-rated recipe that hasn't been used in this session yet.
2. Phase 5 or later. Not critical for end-to-end flow; defer until core features are solid.
3. Skip for now. The library browse is enough; let the user pick recipes manually.

**Context:** Schema prep is done (Phase 1: `cuisine`/`protein`/`rating`/`times_made`/`last_made_at` on `recipes`). The feature logic isn't designed yet. If brought forward, it's a small service function + one UI button.

**Expected outcome:** Decision on phase + signal algorithm (recency, variety, rating, user preference input, etc.). Implement accordingly when that phase arrives.

**Reviewed 2026-09-06 at Phase 4 kickoff — not brought forward; stays deferred with no
reserved phase** (option 2/3 territory). It is not on the Phase 4 deliverable path and the
signal algorithm is still undesigned. Best revisited once planning sessions and "mark cooked"
(Phase 6) exist to give it real recency/variety data to work from.

---

#### Section vocabulary — final list (Before Phase 6 store-setup UI)

**Q:** Is the starter section vocabulary in `SECTION_VOCABULARY` correct for your actual grocery stores, or does it need adjustments?

**A options:**
1. Use as-is. The list (`produce, dairy, meat & seafood, bakery, frozen, pantry, household, deli, drinks, other`) matches real stores.
2. Adjust the list. Add/remove/rename sections to match your specific stores better before building the Phase 6 UI.

**Context:** The list is provisional (seeded in Phase 1, `app/seed_data.py`). It's a dropdown vocabulary for the Phase 6 store-setup UI, so it should match actual store layouts before that UI is built. Not a big change, but easier to do now than to rework later.

**Expected outcome:** Confirmed/updated `SECTION_VOCABULARY` in `app/seed_data.py` before Phase 6 store-setup UI is built.

---

#### Nutrition read-back into the app (Post-MVP — if raised again)

**Q:** Recipe→MFP export is settled. Should the app additionally hold per-recipe macros so it can show a nutrition summary (e.g. per planning session)?

**A options:**
1. **No — export only.** MFP holds nutrition; the app never mirrors it. Current position (2026-09-06).
2. **Manual write-back.** A per-serving kcal/protein/carbs/fat field on the recipe the user fills in once from MFP's computed figures. MFP stays source of truth; ~4 numbers per recipe. No integration, no new dependency.
3. **Scrape MFP.** Unofficial library reads MFP's computed recipe nutrition. Real automation, but AnyList-class fragility + a stricter ToS; needs a derisking spike.
4. **Independent estimate.** App computes its own macros from USDA FoodData Central / Claude / a manual `ingredient_nutrition` table. Always present, no MFP dependency, but won't match MFP's numbers — two sources of truth. Also carries the hard unit-conversion problem (tsp/tbsp/cup/"each" → grams).

**A sub-questions (if not option 1):**
- Where do macros surface — recipe detail, planning-session summary, or both?
- If option 3 or 4: does this get its own phase, or fold into an existing one?

**Context:** Raised 2026-09-06. The secondary user wants recipes in MFP for macro tracking; MFP has no API in either direction (see [Nutrition & MyFitnessPal Export](#nutrition--myfitnesspal-export)). Export covers the core ask cheaply. Read-back is a want, not a need, and every real option has a notable downside.

**Expected outcome:** Decision documented in [Nutrition & MyFitnessPal Export](#nutrition--myfitnesspal-export); if option 2–4, a build plan plus any schema / further Decision Dialogue follow-ups.

---

#### Duplicate recipe prevention — fuzzy threshold & live check (Phase 4 kickoff)

**Q:** The design ([Duplicate Recipe Prevention](#duplicate-recipe-prevention)) is settled —
warn-with-override on save, signals `source_url` / name exact / `source_book`+`source_page` /
conservative fuzzy name. Two build details to lock at kickoff:

**A sub-questions:**
1. **Fuzzy match method + threshold.** `difflib` ratio, token-set Jaccard, or both; and how
   strict. Start strict (few false positives, may miss some), loosen during verification only
   if real near-dupes get through.
2. **Live `GET /recipes/check-duplicate` endpoint?** Warn on name-field blur in the
   capture-review / manual-entry screens, or rely solely on the submit-time 409 +
   "Save anyway". Live check is nicer UX and cheap; the 409 alone is less code.
3. **Ingredient-set overlap signal** — still deferred. Only pull it in if signals 1–4 prove
   insufficient in real use.

**Context:** Raised 2026-09-06. Needs the `recipes.source_book` / `source_page` columns from
Chunk 3.7b, hence Phase 4 not Phase 3. No new dependency — fuzzy matching is stdlib only.

**Expected outcome:** Method/threshold and the live-endpoint call recorded in
[Duplicate Recipe Prevention](#duplicate-recipe-prevention); implementation lands as a Phase 4
chunk.

---

## AI Provider Migration — Anthropic Claude → Google Gemini (Phase 3.9)

**Status: IN PROGRESS — added 2026-09-06, chunked as Phase 3.9 (chunks M0–M7 below), all
decisions resolved 2026-09-06.** This is the authoritative spec for the AI extraction
provider and for ingredient substitution going forward. It **supersedes** the earlier
"Claude API" / "Anthropic API" / "Claude Haiku" references in the AI-extraction context and
the Phase 4 [Ingredient Substitution](#ingredient-substitution) design. As each chunk lands,
the relevant section ([Tech Stack](#tech-stack), [Recipe Capture](#recipe-capture--ai-extraction),
[Ingredient Substitution](#ingredient-substitution), [Diagnostics & Logging](#diagnostics--logging),
[Security §0a/§0b/§0c](#security), [Data Model](#data-model), [Environment
Variables](#environment-variables-env)) is rewritten in place and its `⚠️` banner removed.
Non-AI uses of the name "Claude" (Claude Code as this project's dev tool; git commit
`Co-Authored-By` lines) are unaffected.

**Why:** the Anthropic account used for recipe extraction is permanently unable to add
billing credit (see [Phase 3 Chunk 3.6](#phase-3--recipe-capture-ai), BLOCKED). Gemini's
free tier replaces it.

### The substitution merge — Phase 4 design + capture-time flagging

The Phase 4 [Ingredient Substitution](#ingredient-substitution) design (global
`ingredient_substitutions` rules, an `is_default` that auto-applies **silently** at
consolidation, cross-session memory, resolution inside the pure `consolidation.consolidate()`)
and the addendum's capture-time flagging idea are **merged** (decisions confirmed 2026-09-06):

| Axis | Merged behaviour |
|---|---|
| **Who proposes a swap** | Both: a dedicated Gemini call flags candidates per recipe at capture; the user can also swap later in the recipe editor, or session-only during planning. |
| **Source of truth** | The **ingredient record**. `recipe_ingredients` gains `resolved_ingredient` (nullable — the swap this recipe actually uses) and `substitution_note` (freetext why). `name` stays the *original* (merge decision #2 — reuse `name`, no separate `original_ingredient` column). |
| **Auto-apply** | **Never silent.** `is_default` and `get_default_substitution_map()` are removed. Every swap is confirmed per recipe. |
| **Memory** | A remembered swap is a **suggestion accelerator, not an action** (merge decision #1). `ingredient_substitutions` → `remembered_substitutions` (drop `is_default`; add `note`, `last_used_at`). When an ingredient is confirmed and a remembered swap exists for its name, that swap is **pre-selected / top-ranked** in the confirm UI under a visible "from your saved swaps" label — the user still clicks confirm. The AI *flagging* call is never told about past choices; only the UI pre-fill uses memory. |
| **Reversibility** | Recipe-level: clear `resolved_ingredient` in the editor → back to `name`. The original is never lost. Deleting a `remembered_substitutions` entry never cascades to recipes or past sessions. |
| **Consolidation** | `consolidation.consolidate()` becomes **pure again** — it reads `resolved_ingredient` (fallback `name`) as plain data, no substitution logic. Session-only planning swaps resolve in the `consolidate_session()` orchestrator *before* the pure function runs (merge decision #3 — the plumbing built in Chunk 4.7 stays, the resolution point moves). "Also remember" from a planning swap may add a `remembered_substitutions` row (merge decision #4). |
| **1-to-many** | Out of scope for now (merge decision #5). `substitute_name` stays a single freetext string; `buttermilk → "milk + lemon juice"` is one string the user splits by hand if they want. 1:many is a [Deferred Decision](#deferred-decisions). |

**Kept from Phase 4:** the library table (as `remembered_substitutions`), multiple
substitutes per ingredient, Settings management (reframed as a quick-pick library),
the planning-time ad-hoc swap + `ConsolidateRequest.overrides` plumbing, `substitution_note`.
**Removed:** `is_default` + its reassign/enforce logic, silent auto-apply,
`get_default_substitution_map()`, substitution resolution inside `consolidate()`.
**Added:** the capture-time AI flagging call, per-ingredient confirm/decline,
`recipe_ingredients.resolved_ingredient` / `substitution_note`, the "Pending AI processing"
badge.

### Provider & model selection

- **Primary:** `gemini-2.5-flash` — closest quality match to Haiku, especially for messy
  handwritten photo OCR.
- **Fallback (primary's daily quota exhausted):** `gemini-2.5-flash-lite` — for volume, not
  the default; photo-capture accuracy is the priority.
- **Queue (both exhausted):** the capture is queued and retried later (see Queueing).

**Do not hardcode Gemini rate limits.** Free-tier RPM/TPM/RPD have changed repeatedly in
2026 and third-party numbers conflict. Instead: read quota state from `429`
`RESOURCE_EXHAUSTED` at runtime; link the Google AI Studio dashboard from diagnostics rather
than printing a hardcoded "X of Y"; track observed daily request counts and reset the quota
bar on *detected* recovery (poll hourly with a light test call or by re-attempting the
oldest queued item), not an assumed fixed reset time.

### Call structure — separate calls per task

Each capture issues **separate Gemini calls**, not one combined call:
1. **Recipe extraction** — ingredients, steps, metadata (from URL text or photo).
2. **Ingredient substitution flagging** — per-recipe, confirmation required (see below).
3. **Store section suggestion** — per ingredient, confirmation required (unchanged in intent
   from the prior addendum; today it rides inside the single extraction call).

Uses more daily quota than a combined call, but keeps each task's prompt, schema and
failure handling independent and debuggable — consistent with the diagnostics-first
philosophy. **Do not pre-optimise by combining** — revisit only if quota pressure becomes a
real problem. Every call uses Gemini structured-output / JSON-schema mode to preserve the
schema parity from prior addenda.

### Ingredient Substitution Flagging — the merged spec

Supersedes both the addendum's stricter "no memory at all" wording and the Phase 4
"global auto-applying rules" design — see the merge table above. **If existing code
disagrees with the rules below, the code is wrong** (this feature has drifted before).

**What it IS:**
- At capture time, a dedicated Gemini call flags ingredients *in this specific recipe* that
  could be substituted, each with a suggested substitute + a short note (e.g. `buttermilk` →
  `"milk + lemon juice"`, note "acidulate the milk and rest 10 min").
- Each flag is surfaced for **per-recipe, per-ingredient confirm/decline** before anything is
  stored. Confirm → `recipe_ingredients.resolved_ingredient` + `substitution_note` set on
  *that* recipe. Decline → `resolved_ingredient` left NULL (falls back to `name`); the flag
  is dismissed, not hidden from history.
- On confirm, an optional **"save this swap"** tick writes/updates a
  [`remembered_substitutions`](#remembered_substitutions) row (name → name + note). Unticked
  = one-off, this recipe only.

**Memory — accelerator, never an action:**
- If `remembered_substitutions` has entries for a flagged ingredient's `name`, they are
  **pre-selected / top-ranked** in the confirm UI beneath a visible "from your saved swaps"
  label. The user still clicks confirm — nothing is applied without that per-recipe action.
- The Gemini flagging call is **never** given past choices — every recipe's AI flags are
  independent. Only the UI pre-fill consults memory.

**What it is NOT:**
- ❌ No silent auto-apply anywhere. No `is_default`.
- ❌ No substitution *resolution* inside the pure `consolidation.consolidate()` — it reads
  `resolved_ingredient` (fallback `name`) as plain data. (A session-only planning swap
  resolves one layer up, in the `consolidate_session()` orchestrator — that's retained.)
- ❌ No 1-to-many split as structured data yet (`substitute_name` is one freetext string).

**Call behaviour:** its own Gemini call; same Flash → Flash-Lite → queue chain; if it
fails/queues, extraction still completes and the recipe is usable — flags are enrichment,
not a blocker. The "Pending AI processing" badge names *which* sub-task (extraction /
substitution / section) is still outstanding.

**Where it lives in the app:**
- **Capture review screen** (`capture-review.js`) — the per-ingredient confirm/decline +
  quick-picks + "save this swap" tick, after extraction, before the recipe is saved.
- **Recipe editor** (`recipe-edit.js`) — the same per-ingredient controls, so a swap can be
  added / changed / cleared later. Clearing `resolved_ingredient` reverts to `name`.
- **Planning session review** (`session-review.js`) — the existing ad-hoc swap, now a
  **session-only override** (client-held, passed in `ConsolidateRequest.overrides`, resolved
  in `consolidate_session()` before `consolidate()`). Optional "also save this swap" →
  `remembered_substitutions` row; never edits recipe data.
- **Settings** (`settings-substitutions.js`) — reframed: view / edit note / delete
  `remembered_substitutions` entries. A pure quick-pick library. No default toggle. Deleting
  never touches recipes or past sessions.

### Photo capture

- One photo per capture for now.
- Keep the image input a **list** structure (one element populated today) so multi-photo
  (card front/back, multi-page printout) is not a breaking schema change later.

### Fallback & retry

1. Call `gemini-2.5-flash`.
2. On `429` quota-exhausted → retry the same call on `gemini-2.5-flash-lite`.
3. Flash-Lite also `429` → queue the capture.
4. **Non-quota errors** (malformed response, network failure, …) do **not** fall through to
   Flash-Lite or the queue — surface as a normal capture failure per existing error
   conventions.

### Queueing

- New SQLite table (e.g. `capture_queue`): original input (URL/text/photo ref), task type,
  queued-at timestamp, attempt count.
- Retry ~hourly (not on an assumed fixed reset).
- On success, the item processes through the normal capture pipeline and is removed.

### Surfacing queued / pending state (both required)

- **Recipe library badge:** "Pending AI processing" until all required AI tasks (extraction,
  substitution flagging, section suggestion) complete.
- **Diagnostics panel:** queued items visible in the live log tail / component status view.

### Diagnostics — replacing "Claude API spend tracking"

- **Daily quota usage indicator** — observed request count today per model (best-effort;
  exact caps aren't reliably documented).
- **Recent capture attempt log** — success/fail per capture task, which model handled it
  (Flash / Flash-Lite / queued), and any error detail.

Cost-in-dollars tracking goes away (Gemini free tier). `calculate_cost_usd_cents`, the
`cost_usd_cents` column, the `api_usage` / `api_usage_resets` tables and the "reset spend
tracker" button are all **removed** (decision #3 below — replace, don't repurpose; there is
essentially no real data — Chunk 3.6 never made a live call). Replacement: a purpose-built
`ai_call_log` table (see [Data Model](#ai_call_log)) recording one row per attempted Gemini
call — task type, model tried (`flash` / `flash-lite`), outcome
(`success` / `quota` / `error` / `queued`), token counts, error detail, timestamp. The
diagnostics quota indicator counts today's `ai_call_log` rows per model; the attempt log
lists the most recent.

### API key storage

`.env`, plaintext — unchanged from the Anthropic key. `keyring` hardening stays deferred to
Phase 5 with the AnyList credential work.

### Open item — free-tier data usage

On Gemini's free tier, prompt/response content (recipe photos and text) **may be used by
Google to improve their products**. Enabling Cloud Billing on the project stops this, even at
$0 spend under the free quota. **Unresolved — revisit before this feature is signed off.**
Decision needed: is adding a Google Cloud payment method viable (unlike Anthropic), and is it
worth doing purely to stop free-tier data usage.

### Deferred — local LLM fallback (future phase, NOT now)

Placeholder direction only, if the Gemini dependency ever must be removed entirely
(cost/privacy/availability): Ollama native on the NUC (Windows, no Docker); candidate models
`llama3.2-vision`, `qwen2-VL`, `moondream2`. Known trade-offs to check against real NUC
hardware at that time: weaker messy-handwriting OCR; latency depends heavily on GPU vs
CPU-only. **Do not add Ollama dependencies or code paths now.**

### Resolved decisions (2026-09-06)

1. **Sequence & scoping** — its own chunked mini-phase, **Phase 3.9**, chunks M0–M7 (below).
   The **Phase 4 review** is deferred until Phase 3.9's own review (M-review), which
   re-checks Phase 4 + 3.9 together — running it earlier would sign off substitution code
   that M4 removes. Phase 3.9 builds on top of the completed Phase 4 chunks 4.1–4.4/4.6.
2. **The "prior addendum" isn't in this file** — treat the merged spec above as complete.
   With merge decision #2, it's **two** new columns on `recipe_ingredients`
   (`resolved_ingredient`, `substitution_note`); `name` is the original.
3. **`api_usage` — replace, don't repurpose.** Drop `api_usage` + `api_usage_resets` +
   `cost_usd_cents` + `calculate_cost_usd_cents()` + the reset-spend button; add `ai_call_log`
   (see [Data Model](#ai_call_log)). No real data is lost — Chunk 3.6 never made a live call.
4. **Env var names — provider-neutral for the switches, provider-specific for the key.**
   `ANTHROPIC_API_KEY` → `GEMINI_API_KEY`; `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`;
   `CLAUDE_API_FAKE_MODE` → `AI_EXTRACTION_FAKE_MODE`. (Neutral so the deferred Ollama option
   wouldn't force another rename.) Touches `config.py`, `.env.example`, tests, and the NUC's
   real `.env` (call out in `DEPLOY.md` / the M-review).
5. **No Gemini key assumed.** Phase 3.9 builds and verifies entirely against fake mode +
   mocks (M1–M6). **M7** is the single live call — `AI_EXTRACTION_ENABLED=true`, real key,
   and an explicit in-conversation go-ahead per §0c (a standing "yes" does not carry).
6. **§0c carries over verbatim.** Enable switch off by default; no agent session flips it;
   ask the maintainer before any real call even once it's on; fake mode bypasses everything.
   Same for §0a prompt-injection hardening (provider-agnostic).
7. **Phase numbering** — this is **Phase 3.9** in this document. The addendum's "Phase 1"
   references are wrong for this repo; capture is Phase 3.

### Phase 3.9 chunks (M0–M7)

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
- **M7 — Live Gemini verification.** The one real call, §0c-gated, explicit go-ahead.
  Confirms structured output parses, `429` handling, one real end-to-end capture. Revisit the
  free-tier-data-usage decision.
- **M-review** — full re-check of Phase 3.9 **and** the deferred Phase 4 review, together.

---

## Explicitly Out of Scope

Confirmed during planning, not revisited unless raised again:
- Pantry/inventory tracking — adds admin overhead the app is designed to remove.
- Cost/budget tracking — real-time price data has poor cost/benefit for a meal planner, not a
  budgeting app.
- Batch-cook/freezer-session mode, camera capture of physical recipe sources, self-generating
  cookbook export, seasonal produce nudges, voice/widget interface, agent-driven planning
  autopilot — all considered, none wanted.

---

## Environment Variables (.env)

> **⚠️ AI env vars change at Phase 3.9 M1
> ([AI Provider Migration](#ai-provider-migration--anthropic-claude--google-gemini--phase-39)):**
> `ANTHROPIC_API_KEY` → `GEMINI_API_KEY`, `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`,
> `CLAUDE_API_FAKE_MODE` → `AI_EXTRACTION_FAKE_MODE`. §0c semantics unchanged (off by
> default, explicit maintainer opt-in, fake mode bypasses, no agent flips it). Code +
> `.env.example` + the NUC's real `.env` still use the `CLAUDE_API_*` names until M1;
> `DEPLOY.md` will note the `.env` update.

```
PORT=8080
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
ANTHROPIC_API_KEY=sk-ant-...           # M1 → GEMINI_API_KEY
CLAUDE_API_ENABLED=false               # M1 → AI_EXTRACTION_ENABLED
CLAUDE_API_FAKE_MODE=false             # M1 → AI_EXTRACTION_FAKE_MODE
ANYLIST_EMAIL=...
ANYLIST_PASSWORD=...
LOG_LEVEL=INFO
DATABASE_PATH=data/mealplanner.db
IMAGES_PATH=images
LOGS_PATH=logs
```

`CLAUDE_API_ENABLED`, `CLAUDE_API_FAKE_MODE` — see
[Security §0c](#0c-api-enable-switch--offline-development-highest-priority), a
highest-priority standing rule. Both default to `false` in `app/config.py` and in the
shipped `.env.example` (aligned here 2026-09-06 during the Phase 3 review — this block
previously showed `CLAUDE_API_FAKE_MODE=true`, out of step with the code default). Enable
`CLAUDE_API_ENABLED` only with the maintainer's explicit approval; set
`CLAUDE_API_FAKE_MODE=true` only in local development (never on the NUC), when you want the
capture flow to run against canned fixtures with no key. (`MAX_API_SPEND_AUD_CENTS`
existed here from 2026-09-05 to 2026-09-06 as part of a hard spend cap that has since been
removed — see the Non-Negotiable Operating Rules banner and
[Security §0b](#0b-api-usage-observability-no-hard-cap) — it is no longer a recognised
setting.)

---

## How to Use This File in Claude Code

At the start of your Claude Code session, run:
```
claude
```
Then say:
> "Read CLAUDE.md in full before we begin. This is the project specification and contains all
> decisions made during planning. Once you've read it, summarise the Phase 1 deliverables and
> tell me what you need from me to start."

Claude Code will read the file and use it as the authoritative project context for the session.
You do not need to re-explain any of the planning decisions — they are all in this document.
When a deferred item comes up, Claude Code should flag it explicitly rather than making a
unilateral choice. If you add a standalone addendum again in future, ask Claude Code to fold it
into the relevant sections (as was done here) rather than leaving it appended at the end — that's
what keeps deferred items from being missed when their phase arrives.

### Commits

Commits are shared responsibility. Claude Code should create commits proactively and judiciously:

- Commit meaningful units of work — a feature phase, a bugfix, a schema migration, a test suite
  for one area. Not every keystroke; not "WIP" or "temp". Each commit message should stand alone
  and describe exactly what changed and why.
- Do not commit unless you have something worth committing: tested and verified, or a
  deliberate checkpoint worth preserving in history.
- The maintainer is happy to `git push` these themselves; Claude Code should never push.
  Creating commits is the extent of git responsibility here.
- Commit messages follow the project's standard format (end with
  `Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>`).
