# CLAUDE.md — Mealplanner Project Context

This file is the authoritative project specification. Read it in full before writing any code.
All decisions here were made through a detailed planning session with the user (Will). Do not
re-litigate decided items. Deferred items are explicitly marked — flag them for discussion when
their phase arrives, do not implement them speculatively.

**Document history:** originally written as a single planning document, then extended with three
standalone addenda (Shop Layout Reorganisation, Security Considerations, Schema & Planning
Addendum). Those addenda have since been folded into the sections below — Data Model, Build
Phases, Security, Backup & Restore, Deferred Decisions — so each decision lives next to the
related material instead of in a separate append-only block. Nothing below was re-litigated in
that process; it was moved and cross-referenced, not re-decided. A few genuine gaps the addenda
left open are called out explicitly where they occur, and again in Deferred Decisions.

---

## Project Overview

A household meal planning and shopping list web application. It runs as a local web server on
a Windows 10 NUC (Intel NUC, former light-use workstation, always on). Will and his partner
access it via browser on Android phones over their home WiFi. The server pushes a consolidated
shopping list to AnyList, a shared grocery list app they both use.

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

- **Will** — hardware/RF engineer, Python experience, comfortable with technical tools
- **Partner** — non-technical; the UI must be functional now but will need to be polished for
  her use in a later phase. She may also add items directly to AnyList manually — the system
  must handle that gracefully.
- **Shared access** — no login system required. Single shared account effectively.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.11+, FastAPI | Will has Python experience; FastAPI is async, modern, serves static files, has auto-docs |
| Database | SQLite via SQLAlchemy (ORM) | Zero config, single file, sufficient for household scale |
| Frontend | Vanilla HTML5 / CSS3 / JS | No build step, no framework complexity, easy to debug, runs in any browser |
| AI (recipe extraction) | Anthropic Claude API — Haiku 4.5 | Handles both vision (photo OCR) and text (URL content) in one API; cheapest model; ~$0.005 per recipe capture |
| URL scraping | httpx + BeautifulSoup4 | Fetch recipe page content for Claude to parse |
| AnyList | See Phase 5 note | Unofficial reverse-engineered API — implementation approach TBD at Phase 5 |
| Deployment | Python venv, batch scripts, Windows Task Scheduler | No Docker (user unfamiliar); simple start/stop scripts |

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
Flag this choice for discussion with Will at the start of Phase 5.

### AnyList — derisking spike (bring forward)
Will has flagged AnyList as the part of the stack he is least confident in, so the core
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
connector or UI here — just prove the calls work. Flag the result to Will before proceeding.

---

## Deployment Environment

- **Host OS:** Windows 10
- **Dev machine:** Windows 11, Python 3.14.6
- **NUC:** bare Windows 10 install + Plex. Python not yet installed.
- **Network:** Local WiFi only. NUC needs a static local IP (reserved DHCP lease in router
  settings). See `SETUP.md`.
- **Access:** Will has keyboard/mouse access to NUC and can work over the network.
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
- `deploy.bat` — runs `scripts/deploy.py` on the **dev PC**: verifies the working tree is
  clean and current, tags the commit, pushes branch + tag to the private GitHub repo.
- `update.bat` — runs `scripts/update.py` on the **NUC**: pulls the new commit
  (fast-forward only, never merges), reinstalls dependencies if `requirements.txt` changed,
  then stops and restarts the server. Aborts before touching the running server if any step
  fails, so a bad update leaves the old version running.

This reuses the same private GitHub repo already planned as the backup push destination
(see [Backup & Restore](#backup--restore)) rather than adding a second piece of
infrastructure — one repo, two jobs. `scripts/backup.py`'s commit-and-push now rebases onto
the latest origin first, precisely so its weekly commits and dev-PC deploys pushing to the
same branch don't fight each other.

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

This is a first-class requirement, not an afterthought. Will explicitly wants it to be
"readily apparent when, where, why and how something has failed."

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
  - Claude API (last successful call timestamp + estimated spend to date)
  - AnyList connection (last successful auth timestamp)
- **API spend tracker**: running total of Claude API input/output tokens used, converted to
  estimated USD cost. Reset button (with confirmation). Store in DB.
- **Recent errors**: last 10 ERROR-level entries highlighted prominently at the top

The diagnostics page must be built as a skeleton in Phase 1 and populated progressively as
each component is added.

---

## Code Architecture & Maintainability

This is a first-class requirement, same standing as [Diagnostics & Logging](#diagnostics--logging)
above — not a nice-to-have for "later, if there's time." The app is built incrementally over six
phases by a mix of Will and Claude Code across many separate sessions, months apart in places.
The thing that makes that safe is a codebase where each file has one obvious job, dependencies
only point one direction, and a session that has only read this file plus the two or three files
it's touching has enough context to make a correct change — without having to re-read or
re-understand the whole app first. Optimise for that over cleverness or brevity everywhere below.

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

All tables use SQLite via SQLAlchemy. Use Alembic for migrations from Phase 2 onward — Phase 1
uses `Base.metadata.create_all()` directly since the schema is still settling.

**Audit columns (Schema & Planning Addendum #5, build now):** `created_at` / `updated_at` are
added to every *mutable* table below — trivial to add now, effectively impossible to backfill
onto existing rows later. `shopping_history` and `api_usage` are append-only logs that are never
updated after insert, so they keep their existing single timestamp (`pushed_at` /
`timestamp`) instead of a redundant pair.

### `recipes`
```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL
source_type     TEXT NOT NULL  -- 'url', 'photo', 'manual'
source_url      TEXT           -- nullable
source_image_path TEXT         -- nullable, path to stored image file
base_servings   INTEGER NOT NULL DEFAULT 4
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
```
> **Resolved at kickoff:** the addendum proposed a second freetext `note` field
> ("used half the chilli next time") alongside the above. Confirmed with Will this is the same
> purpose as the existing `notes` column — no second field was added.

### `recipe_ingredients`
```
id              INTEGER PRIMARY KEY
recipe_id       INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE
name            TEXT NOT NULL       -- normalised lowercase, e.g. "beef mince"
quantity        REAL NOT NULL
unit            TEXT               -- nullable for unitless items (e.g. "eggs", "onions")
preparation     TEXT               -- nullable, e.g. "finely diced", "at room temperature"
sort_order      INTEGER NOT NULL DEFAULT 0
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

### `staples`
```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL UNIQUE  -- normalised lowercase
notes           TEXT                  -- nullable
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

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

### `api_usage`
```
id              INTEGER PRIMARY KEY
timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
model           TEXT NOT NULL
input_tokens    INTEGER NOT NULL
output_tokens   INTEGER NOT NULL
cost_usd_cents  REAL NOT NULL       -- calculated at call time
call_type       TEXT NOT NULL       -- 'recipe_url', 'recipe_photo', 'ingredient_normalise'
context_id      TEXT               -- nullable, e.g. recipe id for traceability
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

When a recipe is scaled from its base servings to requested servings:

### Discrete / countable items (no unit, e.g. eggs, onions, cans)
- Scale quantity proportionally, then **round up** to nearest whole number
- Exception: purchase unit resolution (see below) may further adjust — a scaled quantity of
  3 eggs does not mean buy 3 eggs; it means check against the product_units table

### Weight / volume (g, kg, ml, L, tbsp, tsp, cup)
- Scale exactly, then round to a "clean" number:
  - Values ≥ 100g/ml: round to nearest 25
  - Values < 100g/ml: round to nearest 5
  - tbsp/tsp: allow halves (0.5), round to nearest 0.5
  - "pinch", "to taste": do not scale, pass through as-is
- **Australian pack size rounding is a DEFERRED DECISION** — do not implement. For now, output
  the scaled/rounded quantity and unit as-is. Flag for Phase 4 discussion.

### Consolidation across recipes
When multiple recipes in a session use the same ingredient:
- Sum quantities (after scaling each recipe individually)
- Normalise units before summing (e.g. 500ml + 1L = 1500ml → display as 1.5L)
- If units cannot be reconciled (e.g. "2 tbsp soy sauce" + "100ml soy sauce"), flag for
  user review rather than silently failing

### Purchase unit resolution (PARTIALLY DEFERRED)
When an item exists in `product_units`:
- Calculate how many purchase units are needed to cover the required quantity
- Display as e.g. "2 × 500g packs" or "1 dozen eggs"
- **The exact threshold/rounding logic for countable items (e.g. eggs: need 6, buy dozen?)**
  is a DEFERRED DECISION. For Phase 4, implement basic coverage (round up to nearest whole
  purchase unit). Flag for refinement discussion.

---

## Recipe Capture — AI Extraction

Use Claude Haiku 4.5 via the official Anthropic Python SDK (`anthropic`).

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
```
You are an ingredient extraction assistant. Given recipe text or an image of a recipe,
extract ONLY the ingredients list. Return a JSON array of objects with this exact structure:
[
  {
    "name": "ingredient name, lowercase, no preparation notes",
    "quantity": 2.0,
    "unit": "g" or null for unitless items,
    "preparation": "finely diced" or null,
    "original_text": "the raw text as it appeared"
  }
]

Rules:
- quantity must be a number (convert fractions: 1/2 → 0.5)
- unit must be one of: g, kg, ml, L, tsp, tbsp, cup, or null
- Convert any non-standard units to the closest standard unit
- If a quantity is a range (e.g. "1-2 cloves"), use the lower bound
- Separate compound ingredients (e.g. "for the sauce:") into individual items
- Do not include method instructions or serving suggestions
- Return ONLY valid JSON. No markdown, no explanation, no preamble.
```

**Planned Phase 3 extensions to this prompt** (schema for these already exists as of Phase 1;
prompt/logic changes land when Phase 3 build starts, not before):
- A `suggested_section` field per ingredient (produce/dairy/etc., from the canonical vocabulary
  — see [Shopping List Store Layout](#shopping-list-store-layout)), shown in the same
  confirm-UI as an editable field, stored to `product_sections` with `source='ai_suggested'`
  until the user confirms/corrects it.
- `cuisine` / `protein` suggested at the recipe level, same confirm-then-save pattern as
  ingredients.
- **Open gap, flag to Will before Phase 3 prompt work starts:** the Shop Layout addendum
  describes the section suggestion as reusing "the same [review step] already built for
  ingredient substitution flagging" — but no substitution-flagging feature is otherwise defined
  anywhere in this document. Confirm whether that's assumed prior context that needs adding
  here, or a mistaken reference, before building the Phase 3 prompt changes.

### After extraction
- Display extracted ingredients in an editable review UI (inline edit of name, qty, unit)
- User confirms or edits, then saves
- On save: normalise ingredient names to lowercase, store in `recipe_ingredients`
- Log: recipe id, call type, token counts, cost to `api_usage`

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

Seed a default staples list. User edits via Settings. Suggested defaults:
```
salt, black pepper, olive oil, vegetable oil, garlic (whole bulb),
plain flour, white sugar, soy sauce, white wine vinegar, balsamic vinegar,
dried oregano, dried basil, ground cumin, ground coriander, paprika,
chilli flakes, bay leaves, tomato paste (tube), dijon mustard
```

---

## Section Vocabulary Starter List

Canonical, fixed, store-independent section names for
[Shopping List Store Layout](#shopping-list-store-layout). Lives as a Python constant
(`SECTION_VOCABULARY` in `app/seed_data.py`), not a database table — `section_name` columns are
free text, so this only drives dropdown choices in the (not-yet-built) store-setup and
section-tagging UI. Starter list, **provisional — ask Will to confirm/adjust before the Phase 6
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
  [Deferred Decisions](#deferred-decisions) entry if it's a genuine judgement call for Will —
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
Slotted in immediately after Phase 1 because Will has flagged AnyList as the highest-risk,
lowest-confidence part of the stack — it must not stay unexplored until Phase 5.
- Throwaway spike only (scratch script / notebook, not wired into the app)
- Authenticate, fetch the target list + items, add and remove a test item
- Determine Python-native vs Node-microservice approach from real results
- Write up the finding (what worked, auth/protobuf surprises, effort estimate)

**Deliverable:** A working proof-of-concept AnyList call and a short written finding that
settles the Phase 5 "native vs Node" decision. Full connector and checklist UI stay in
Phase 5. Flag the outcome to Will before continuing to Phase 2.

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
- [ ] **Chunk 2.2 — Recipe & ingredient API.** `routers/recipes.py`: recipe CRUD endpoints plus
      nested ingredient CRUD endpoints, `{"ok": ...}` envelope, `?limit=`/`?offset=` pagination
      on list endpoints (see [API Conventions](#api-conventions)). Add `pytest` to
      `requirements.txt` (first phase needing it — see
      [Code Architecture > Tests](#code-architecture--maintainability)); unit tests for
      `services/recipes.py` (no DB/network) and a smoke test (happy path + one error path) for
      the router.
- [ ] **Chunk 2.3 — Recipe library UI.** Browse list, search by name, recipe detail view;
      default views filter `archived_at IS NULL`.
- [ ] **Chunk 2.4 — Recipe edit & manual entry UI.** Inline edit of ingredients (name, qty,
      unit, preparation); recipe-level fields `rating`, `notes`, `cuisine`, `protein`; manual
      recipe entry form (new recipe from scratch, no capture involved).
- [ ] **Chunk 2.5 — Settings UI.** View/add/edit/delete entries in `staples` and
      `product_units` — this is what makes the seeded data from Chunk 2.1 actually editable,
      per the Phase 2 deliverable below.
- [ ] **Phase 2 review** — re-check this phase's work against the Data Model (`recipes`,
      `recipe_ingredients`, `product_units`, `staples`), API Conventions, and Code Architecture
      sections, per [Phase workflow & progress tracking](#phase-workflow--progress-tracking).

**Deliverable:** User can manually add, view, and edit recipes. Staples and product units
table is pre-populated and editable via Settings page.

### Phase 3 — Recipe Capture (AI)
*(Not yet chunked — break this into checkbox chunks at kickoff, following
[Phase workflow & progress tracking](#phase-workflow--progress-tracking), the way Phase 2 was.)*
- Anthropic SDK integration + api_usage logging
- URL capture endpoint: fetch, parse, extract, return for review
- Photo upload endpoint: store image, extract, return for review
- Review + confirm UI: editable ingredient list, confirm saves to recipe
- Extraction prompt extended with `suggested_section` per ingredient and `cuisine`/`protein`
  per recipe (see [Recipe Capture](#recipe-capture--ai-extraction) — resolve the
  substitution-flagging gap noted there first)
- Diagnostics: Claude API status indicator, spend tracker populated

**Deliverable:** User can capture a recipe from URL or photo, review the extracted
ingredients, edit if needed, and save to the library.

### Phase 4 — Planning Engine
*(Not yet chunked — break this into checkbox chunks at kickoff, following
[Phase workflow & progress tracking](#phase-workflow--progress-tracking).)*
- Planning session CRUD
- Session recipe management (add recipe, set day, set servings)
- Leftovers slot type (Addendum #1): `session_recipes.recipe_id` becomes nullable, a
  `slot_type` flag (`'recipe'`|`'leftovers'`) is added; a leftovers slot pulls no ingredients
  into consolidation for that day
- Scaling engine (apply scaled_servings, rounding rules)
- Consolidation engine (sum quantities across recipes, normalise units)
- Purchase unit resolution (look up product_units, calculate display_qty)
- Session summary UI: shows consolidated ingredient list before checklist
- Weekly planner view (optional calendar layout for slotting recipes into days)

**Deliverable:** User can create a session, add recipes, scale them, and see a
consolidated shopping list with purchase units resolved.

### Phase 5 — Checklist & AnyList Integration
*(Not yet chunked — break this into checkbox chunks at kickoff, following
[Phase workflow & progress tracking](#phase-workflow--progress-tracking).)*
- AnyList connector: investigate and implement (Python native or Node microservice — see
  Tech Stack section; flag choice for discussion with Will)
- AnyList auth (email/password from .env) — see [Security](#security) §2 for credential storage
- Fetch current AnyList items at checklist load
- Checklist UI: per-item have/don't have taps, AnyList pre-ticking, staples integration
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
- Session history log page
- Error states and empty states throughout UI
- Comprehensive diagnostics page (all indicators wired up)
- User testing with partner; gather feedback

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
│   │   ├── claude_client.py
│   │   └── anylist_client.py
│   ├── seed_data.py           ← staples + product_units + section vocabulary starter data
│   └── log_config.py          ← logging setup, in-memory ring buffer
├── scripts/                    ← maintenance scripts, run as `python -m scripts.<name>`
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
  unencrypted. **This choice is not yet made — flag to Will at the start of Phase 5** (also
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
speculatively. When the relevant phase begins, flag them to Will for a focused decision.

| Item | Deferred to | Notes |
|---|---|---|
| Australian pack size rounding for weight/volume | Phase 4 discussion | e.g. "needs 340g → buy 400g can". Requires a reference data set of common pack sizes. |
| Partial quantities UX | Phase 5 | Will said "leave the thinking to me" — implement binary have/don't have for now. Revisit if he raises it. |
| Countable item purchase unit thresholds | Phase 4/5 | e.g. "need 6 eggs, buy a dozen?". The product_units table stores purchase size; basic logic is "round up to nearest purchase unit". Edge cases TBD. |
| Ingredient synonym normalisation (automatic) | Phase 6 or later | e.g. "green onion" vs "spring onion". For now, user review at capture time provides sufficient normalisation. |
| Partner login / separate accounts | Post-MVP | Shared access, no auth. |
| AnyList credential storage: `keyring` vs `.env` | Phase 5 kickoff | Preferred: Windows Credential Manager via `keyring`. `.env` acceptable fallback if awkward with deployment scripts. See [Security](#security) §2. |
| Shared basic-auth on API routes | Optional, any phase | Cheap extra barrier against other devices on the WiFi. Recommended but not required at current trust level; not built. See [Security](#security) §4. |
| "Suggest something" — recency/variety suggestion logic + UI | Phase TBD | Schema prep (`cuisine`/`protein` on recipes) is done (Phase 1). Signal is recency + variety, surfaced via an on-demand button, not a proactive nudge. Logic and UI not designed yet. |
| "Substitution flagging" review step | Needs clarification before Phase 3 prompt work | The Shop Layout addendum assumes this exists as prior context for reusing its review UI; it isn't otherwise specified anywhere in this document. Confirm with Will. |
| Store deletion/merge | Post-MVP / low priority | Not designed — add if it comes up. See [Shopping List Store Layout](#shopping-list-store-layout). |
| Section vocabulary — final list | Confirm before Phase 6 store-setup UI is built | Starter list seeded in Phase 1 (`app/seed_data.py > SECTION_VOCABULARY`) is provisional. See [Section Vocabulary Starter List](#section-vocabulary-starter-list). |
| Multi-shop support | ~~Post-MVP~~ **Resolved — now in scope** | See [Shopping List Store Layout](#shopping-list-store-layout). Kept here only so the reversal isn't missed by anyone skimming old notes. |
| Shop layout reorganisation (list sorting by aisle) | ~~Phase 6 or post-MVP~~ **Resolved — now in scope** | See [Shopping List Store Layout](#shopping-list-store-layout). Kept here only so the reversal isn't missed by anyone skimming old notes. |

---

## Explicitly Out of Scope

Confirmed during planning, not revisited unless Will raises them again:
- Pantry/inventory tracking — adds admin overhead the app is designed to remove.
- Cost/budget tracking — real-time price data has poor cost/benefit for a meal planner, not a
  budgeting app.
- Batch-cook/freezer-session mode, camera capture of physical recipe sources, self-generating
  cookbook export, seasonal produce nudges, voice/widget interface, agent-driven planning
  autopilot — all considered, none wanted.

---

## Environment Variables (.env)

```
PORT=8080
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
ANTHROPIC_API_KEY=sk-ant-...
ANYLIST_EMAIL=...
ANYLIST_PASSWORD=...
LOG_LEVEL=INFO
DATABASE_PATH=data/mealplanner.db
IMAGES_PATH=images
LOGS_PATH=logs
```

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
- Will is happy to `git push` these himself; Claude Code should never push. Creating commits is
  the extent of git responsibility here.
- Commit messages follow the project's standard format (end with
  `Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>`).
