# Project Overview & Tech Stack

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
   [Shopping List Store Layout](./checklist-and-shopping.md#shopping-list-store-layout))
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
| AI (recipe extraction) | Google Gemini API — `gemini-flash-latest` (primary), `gemini-flash-lite-latest` (fallback), then a retry queue. `google-genai` SDK, structured-output mode. Three separate calls per capture (extraction / substitution flagging / section suggestion). See [AI Provider Migration (Phase 3.9)](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39). | Anthropic account can't add billing credit; Gemini's free tier replaces it. Floating `*-latest` model aliases — see the migration section (Google retired the originally-pinned `gemini-2.5-flash` mid-migration). |
| URL scraping | httpx + BeautifulSoup4 | Fetch recipe page content for Claude to parse |
| AnyList | See Phase 5 note | Unofficial reverse-engineered API — implementation approach TBD at Phase 5 |
| Deployment | Python venv, batch scripts, Windows Task Scheduler | No Docker; simple start/stop scripts |

### Local development environment (Windows)

The project venv lives at `.venv/` in the repo root — the bare `python`/`pip` on PATH is a
different (pyenv-managed) interpreter with none of `requirements.txt` installed, so calling
them directly fails with `No module named pytest` etc. Always go through the venv's own
executables, not `.venv\Scripts\activate` + a bare command (activation doesn't reliably carry
across every shell this project is driven from — PowerShell, Git Bash, and Claude Code's tool
sessions):

- PowerShell: `.venv\Scripts\python.exe -m pytest`, `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`, `.venv\Scripts\alembic.exe upgrade head`
- Git Bash / POSIX shell: `.venv/Scripts/python.exe -m pytest` (same `.exe` paths — this is still the Windows venv, not a POSIX one)

### FastAPI notes
- Use `uvicorn` as the ASGI server
- Mount a `/static` directory for frontend assets
- **Resolved (Phase 1 kickoff):** flat static HTML + vanilla JS, no Jinja2. Matches the
  no-build-step goal; the frontend is hash-routed from a single `static/index.html`.
- All API routes under `/api/v1/`
- Enable CORS for local network access

### AnyList integration — Phase 5 decision
The AnyList API is unofficial and reverse-engineered. The reference implementation is the
Node.js package `codetheweb/anylist` on GitHub.

**Resolved by the Phase 1.5 spike (2026-09-05) — Python-native, no Node microservice.**
`httpx` + a hand-rolled ~150-line protobuf codec (no `protobuf`/`websockets` package) worked
cleanly in ~2 hours. `spike/anylist_spike.py` + `spike/FINDINGS.md` are the reference the
Phase 5 Chunk 5.2 connector (`services/anylist_client.py`) was adapted from. The Node.js
Express microservice fallback was **not** taken; if it ever were, it must bind to
`127.0.0.1` only — never `0.0.0.0` (see [Security](./security.md#security) §2). The websocket
live-refresh listener was out of spike scope and is not used — the app fetches on demand.

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
> ([AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39)):**
> `ANTHROPIC_API_KEY` → `GEMINI_API_KEY`, `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`,
> `CLAUDE_API_FAKE_MODE` → `AI_EXTRACTION_FAKE_MODE`. §0c semantics unchanged (off by
> default, explicit maintainer opt-in, fake mode bypasses, no agent flips it). Code +
> `.env.example` + the NUC's real `.env` still use the `CLAUDE_API_*` names until M1;
> `DEPLOY.md` will note the `.env` update.

```
PORT=8080
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
GEMINI_API_KEY=...                     # was ANTHROPIC_API_KEY pre-M1
AI_EXTRACTION_ENABLED=false            # was CLAUDE_API_ENABLED pre-M1
AI_EXTRACTION_FAKE_MODE=false          # was CLAUDE_API_FAKE_MODE pre-M1
ANYLIST_EMAIL=...                      # Phase 5 — keyring is tried first (see Security §2)
ANYLIST_PASSWORD=...                   # Phase 5 — .env is the fallback, with a logged warning
ANYLIST_ENABLED=false                  # Phase 5 — gate on real AnyList calls (Security §2)
ANYLIST_FAKE_MODE=false                # Phase 5 — in-memory fake list, dev only
ANYLIST_TARGET_LIST_NAME=TestList      # Phase 5 — never the real household list in dev
LOG_LEVEL=INFO
DATABASE_PATH=data/mealplanner.db
IMAGES_PATH=images
LOGS_PATH=logs
```
`.env.example` in the repo is the source of truth for the exact current set.

`CLAUDE_API_ENABLED`, `CLAUDE_API_FAKE_MODE` — see
[Security §0c](./security.md#0c-api-enable-switch--offline-development-highest-priority), a
highest-priority standing rule. Both default to `false` in `app/config.py` and in the
shipped `.env.example` (aligned here 2026-09-06 during the Phase 3 review — this block
previously showed `CLAUDE_API_FAKE_MODE=true`, out of step with the code default). Enable
`CLAUDE_API_ENABLED` only with the maintainer's explicit approval; set
`CLAUDE_API_FAKE_MODE=true` only in local development (never on the NUC), when you want the
capture flow to run against canned fixtures with no key. (`MAX_API_SPEND_AUD_CENTS`
existed here from 2026-09-05 to 2026-09-06 as part of a hard spend cap that has since been
removed — see the Non-Negotiable Operating Rules banner and
[Security §0b](./security.md#0b-api-usage-observability-no-hard-cap) — it is no longer a recognised
setting.)

---

