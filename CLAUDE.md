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

**2026-09-12 — split into `docs/`.** This file had grown large enough (~5,000 lines) to work
against its own purpose as a fast-to-navigate spec. It is now the root index: every topic keeps
a short summary and a pointer here, and the detailed specification, decisions, and build-status
tracking live in `docs/`. This split moved and cross-referenced content — like the addenda
fold-in above, nothing was re-litigated. The **Manifest** section below is the map; use it the
way the old addenda *should* have been used, so nothing drifts out of sync the way the addenda
did before they were folded back in.

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
[Security](./docs/security.md#security) (§0a, §0b, §0c below); this banner exists so none of them can be missed
by skimming straight to a phase's chunk list.

> **Provider note (2026-09-06):** the AI extraction provider is Anthropic Claude → Google
> Gemini as of Phase 3.9 (see
> [AI Provider Migration](./docs/recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39)).
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
   [Security §0a](./docs/security.md#0a-prompt-injection-hardening-highest-priority).
2. **Explicit permission to use the API at all, and development restructured to need it as
   rarely as possible.** A separate switch (`CLAUDE_API_ENABLED`, off by default) gates every
   real call, and a fake/fixture mode lets almost all of a phase's build and verification work
   happen with zero key, zero cost, and zero real calls, pushing the one unavoidable live check
   to the very end. See
   [Security §0c](./docs/security.md#0c-api-enable-switch--offline-development-highest-priority). No agent
   session may turn the switch on itself, and must ask the maintainer in conversation before
   making any real call even once it's on. Cost calculation and per-call logging (`api_usage`)
   are kept for observability regardless — see
   [Security §0b](./docs/security.md#0b-api-usage-observability-no-hard-cap).

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
spent. See [Security §0b](./docs/security.md#0b-api-usage-observability-no-hard-cap) for what replaced it.

---

## Manifest — where everything lives

Every original section of this file now lives in exactly one of the files below. If you're
looking for something and it isn't summarised in this root file, it's in here — check this
table before assuming something went missing.

| docs/ file | Contents | Original section(s) it was built from |
|---|---|---|
| [project-overview.md](./docs/project-overview.md) | Project Overview, Users, Tech Stack, what's explicitly out of scope, the `.env` reference | Project Overview; Users; Tech Stack (+ FastAPI notes, AnyList integration decision, AnyList derisking-spike note); Explicitly Out of Scope; Environment Variables (.env) |
| [code-architecture.md](./docs/code-architecture.md) | Layering rules, file-size/documentation discipline, migrations, the source tree map, the API response envelope | Code Architecture & Maintainability; Project Directory Structure; API Conventions |
| [data-model.md](./docs/data-model.md) | All 16 SQLite tables, audit-column conventions, seed data | Data Model; Pre-seeded Product Units; Staples Starter List; Section Vocabulary Starter List |
| [scaling-and-consolidation.md](./docs/scaling-and-consolidation.md) | Scaling, rounding/unit-normalisation rules, purchase-unit resolution, the per-recipe ingredient breakdown | Scaling Logic; Which Recipe Is This Ingredient From |
| [recipe-capture.md](./docs/recipe-capture.md) | URL/photo capture flow, the extraction prompt, the current Gemini provider/model/call-structure spec | Recipe Capture — AI Extraction; AI Provider Migration (its provider/model selection, call structure, photo capture, fallback & retry, queueing, pending-state surfacing, API key storage, free-tier resolution, and deferred-Ollama parts only — see below) |
| [duplicate-recipe-prevention.md](./docs/duplicate-recipe-prevention.md) | Warn-with-override duplicate detection at recipe save time | Duplicate Recipe Prevention |
| [ingredient-handling.md](./docs/ingredient-handling.md) | Normalisation, substitution (incl. the merged capture-time-flagging spec), aliases, and the four-layer unit-handling design | Ingredient Normalisation; Ingredient Substitution (minus its History subsection — see decision-history.md); Ingredient Aliases; Ingredient Unit Handling (minus its Build-chunks subsection — see build-status/); AI Provider Migration's substitution-merge table and "Ingredient Substitution Flagging — the merged spec" |
| [checklist-and-shopping.md](./docs/checklist-and-shopping.md) | Checklist load/tap logic, "the usuals", the AnyList push algorithm, store-layout sorting | Checklist Screen Logic; AnyList Push Logic; Shopping List Store Layout |
| [nutrition-mfp-export.md](./docs/nutrition-mfp-export.md) | Recipe → MyFitnessPal export design (post-MVP, unscheduled) | Nutrition & MyFitnessPal Export |
| [diagnostics-and-logging.md](./docs/diagnostics-and-logging.md) | Logging rules, log file rotation, the `/diagnostics` page spec | Diagnostics & Logging |
| [security.md](./docs/security.md) | §0a–0c (injection hardening, usage observability, the enable switch) + §1–5 (network, credentials, host, app, deployment) | Security |
| [deployment-and-operations.md](./docs/deployment-and-operations.md) | NUC deployment, start/stop/deploy/update scripts, backup & restore | Deployment Environment (+ Startup); Backup & Restore |
| [ui-ux.md](./docs/ui-ux.md) | Mobile-first principles, tone, accessibility, the Phase 6 design direction | UI / UX |
| [deferred-decisions.md](./docs/deferred-decisions.md) | The live deferred-items tracking table | Deferred Decisions (table only — its Decision Dialogues subsection is in decision-history.md) |
| [decision-history.md](./docs/decision-history.md) | Every Decision Dialogue (resolved and still-open), plus superseded designs kept for the record | Decision Dialogues; Ingredient Substitution's "History" subsection; AI Provider Migration's "Resolved decisions (2026-09-06)" and "Diagnostics — replacing 'Claude API spend tracking'" subsections |
| [build-status/process.md](./docs/build-status/process.md) | The chunking/checkbox/phase-review convention itself | Build Phases > Phase workflow & progress tracking |
| [build-status/phase-1-foundation-and-spike.md](./docs/build-status/phase-1-foundation-and-spike.md) | Phase 1 + Phase 1.5 chunk lists and reviews | Build Phases > Phase 1 — Foundation; Phase 1.5 — AnyList derisking spike |
| [build-status/phase-2-recipe-library.md](./docs/build-status/phase-2-recipe-library.md) | Phase 2 chunk list and review | Build Phases > Phase 2 — Recipe Library |
| [build-status/phase-3-recipe-capture.md](./docs/build-status/phase-3-recipe-capture.md) | Phase 3 chunk list and review | Build Phases > Phase 3 — Recipe Capture (AI) |
| [build-status/phase-3.9-ai-provider-migration.md](./docs/build-status/phase-3.9-ai-provider-migration.md) | Phase 3.9 (M0–M8 + M-review) execution log, plus the migration section's own original chunk plan | Build Phases > Phase 3.9 — AI Provider Migration; AI Provider Migration > Phase 3.9 chunks (M0–M8) |
| [build-status/phase-4-planning-engine.md](./docs/build-status/phase-4-planning-engine.md) | Phase 4 chunk list and review | Build Phases > Phase 4 — Planning Engine |
| [build-status/phase-5-checklist-anylist.md](./docs/build-status/phase-5-checklist-anylist.md) | Phase 5 chunk list (review still open) | Build Phases > Phase 5 — Checklist & AnyList Integration |
| [build-status/anylist-fault-finding-spike.md](./docs/build-status/anylist-fault-finding-spike.md) | 2026-09-18 live fault-finding spike: dropped-note symptom confirmed on the phone, "Not set" quantity's leading theory falsified by the phone check and still open, plus a newly found duplicate-on-repush bug | (new — not in the original planning document) |
| [build-status/phase-6-polish.md](./docs/build-status/phase-6-polish.md) | Phase 6 placeholder (not yet chunked) | Build Phases > Phase 6 — Polish |
| [build-status/ingredient-unit-handling-chunks.md](./docs/build-status/ingredient-unit-handling-chunks.md) | The Ingredient Unit Handling feature's own build-chunk checklist | Ingredient Unit Handling > Build chunks |

**The two banners above this table (Personal Data Policy, Non-Negotiable Operating Rules) are
never delegated** — they stay inline in this file in full, regardless of any future edit to the
rest of the structure.

---

## Project Overview & Tech Stack

A shared meal planning and shopping list web app running on a Windows 10 NUC, used by two
household members over local WiFi, with a Python/FastAPI backend, vanilla-JS frontend, and a
push to AnyList as the endpoint of the core flow. Covers who the app is for, the tech stack and
why each piece was chosen (including the AnyList Python-native-vs-Node decision and the Phase
1.5 derisking spike), what's explicitly out of scope, and the full `.env` reference.

See [docs/project-overview.md](./docs/project-overview.md).

## Code Architecture & Maintainability

The rule set that keeps a project built incrementally across many separate sessions safe to
extend: strict one-way layering (`routers/` → `services/` → `models/`/`schemas/`), external
integrations kept behind small stable interfaces, a file-size guideline, a documentation
standard ("comment the why, not the what"), the Alembic migration story, and the physical
source tree. Also covers the API response envelope and error-code conventions.

See [docs/code-architecture.md](./docs/code-architecture.md).

## Data Model

Every SQLite table (16 of them) — `recipes`, `recipe_ingredients`, `product_units`, `staples`,
`remembered_substitutions`, `ingredient_aliases`, `unit_synonyms`, `coarse_ingredients`,
`planning_sessions`, `session_recipes`, `session_checklist_items`, `shopping_history`,
`usual_items`, `ai_call_log`, `capture_queue`, and `stores`/`store_sections`/`product_sections`
— plus the audit-column convention and the seed data (pre-seeded product units, the staples
starter list, the section vocabulary).

See [docs/data-model.md](./docs/data-model.md).

## Scaling Logic & Consolidation

How a recipe scales from its base servings to a session's target, and — separately — how
quantities from many recipes sum, normalise (Australian volume conversions), round (always
upward, never to nearest), and resolve against purchase pack sizes into one shopping-list line
per ingredient. Also covers the ephemeral per-recipe "which recipe is this ingredient from"
breakdown shown on the review screen.

See [docs/scaling-and-consolidation.md](./docs/scaling-and-consolidation.md).

## Recipe Capture — AI Extraction

The URL and photo capture flows, the extraction prompt, and the current (Gemini-based)
provider spec: the Flash → Flash-Lite → `capture_queue` fallback chain, the three separate
per-task calls, photo capture, API key storage, and the free-tier billing resolution. The
substitution-flagging call's actual merged design lives in ingredient-handling.md instead
(it's a substitution concern first).

See [docs/recipe-capture.md](./docs/recipe-capture.md).

## Duplicate Recipe Prevention

Warn-with-override (never a hard block) duplicate detection at recipe-save time, checked
against four signals (exact `source_url`, `source_book`+`source_page` overlap, exact name,
conservative fuzzy name), including archived recipes and a URL-capture short-circuit that
skips the AI call entirely on an exact match.

See [docs/duplicate-recipe-prevention.md](./docs/duplicate-recipe-prevention.md).

## Ingredient Handling — Normalisation, Substitution, Aliases & Units

Four closely related, easily-confused mechanisms, kept in one file because they constantly
cross-reference each other: **Normalisation** (spelling variants an AI extraction already
canonicalises), **Substitution** (a different product, confirmed per recipe, optionally
remembered as a quick-pick — never silently auto-applied), **Aliases** (two names that are the
*same* shopping item to this household, resolved silently at consolidation, with an optional
quantity/unit equivalence pair), and **Unit Handling** (four layers: unit-spelling
canonicalisation, per-ingredient known units derived live with zero admin, a warn-never-block
duplicate-unit nudge, and "coarse ingredients" that skip quantity math entirely).

See [docs/ingredient-handling.md](./docs/ingredient-handling.md).

## Checklist, AnyList Push & Shopping List Layout

The checklist screen's load/tap-cycle logic (including "the usuals" — recurring non-recipe
household items on their own cadence), the push-to-AnyList algorithm (batched update,
re-fetch-and-diff confirmation, `shopping_history` logging), and the store-specific
walking-order rendering design (multi-store, AI-suggested sections, store layout kept
independent of AnyList itself).

See [docs/checklist-and-shopping.md](./docs/checklist-and-shopping.md).

## Nutrition & MyFitnessPal Export

Post-MVP, unscheduled: exporting a recipe in a form MyFitnessPal's own Recipe Importer can
consume (MFP has no push/pull API in either direction, so this is export-only, no macros held
in the app).

See [docs/nutrition-mfp-export.md](./docs/nutrition-mfp-export.md).

## Diagnostics & Logging

Logging rules (levels, format, daily rotation), and the `/diagnostics` page spec: live log
tail, component status panel, AI-extraction quota/attempt log, and recent-errors panel.

See [docs/diagnostics-and-logging.md](./docs/diagnostics-and-logging.md).

## Security

§0a prompt-injection hardening, §0b usage observability (no hard cap), §0c the API enable
switch and fake-mode offline-development discipline — all highest-priority — plus §1–5:
network exposure, AnyList credential storage, the Windows 10 host, app-level CORS, and
Task Scheduler privilege scoping.

See [docs/security.md](./docs/security.md).

## Deployment & Operations

The NUC deployment environment, the six pairs of batch scripts (start/stop, backup/restore,
deploy/update, plus first-run `setup_nuc.bat`), the `develop`/`production` git branching
workflow, and the weekly backup + tested restore path.

See [docs/deployment-and-operations.md](./docs/deployment-and-operations.md).

## UI / UX

Mobile-first principles, plain-language tone and copy rules, accessibility minimums, and the
Phase 6 design direction (palette, typography, no decorative animation).

See [docs/ui-ux.md](./docs/ui-ux.md).

## Build Phases & Status

Every phase's chunk checklist, verification log, and phase-end review — Phase 1 through the
still-open Phase 5 review, plus Phase 6's not-yet-chunked placeholder and Phase 3.9's AI
Provider Migration chunks (M0–M8). This is the **live status tracker**: it's the file set that
changes as work actually happens, kept deliberately separate from the stable spec files above
it. One file per phase — see the Manifest table above for the full list, starting at
[docs/build-status/process.md](./docs/build-status/process.md).

## Deferred Decisions

The live tracking table of every item explicitly parked for a later phase, with what it was
deferred to and (where resolved) a pointer to where the resolution landed.

See [docs/deferred-decisions.md](./docs/deferred-decisions.md).

## Decision Dialogues & Historical Record

The structured Q&A prompts to use when a deferred decision comes due (most already resolved
and recorded; a few — shared basic-auth, Home tab content, the Settings scroll bug, "Suggest
something", the final section vocabulary, nutrition read-back — still open), plus superseded
designs kept for the record rather than silently deleted (the pre-merge Ingredient Substitution
designs, and two AI Provider Migration subsections whose current behaviour is now fully
described elsewhere).

See [docs/decision-history.md](./docs/decision-history.md).

---

## How to Use This File in Claude Code

At the start of your Claude Code session, run:
```
claude
```
Then say:
> "Read CLAUDE.md in full before we begin, including the Manifest section, then read whichever
> docs/ file(s) are relevant to the task at hand. This is the project specification and contains
> all decisions made during planning. Once you've read it, summarise the Phase 1 deliverables and
> tell me what you need from me to start."

Claude Code will read this file and use it — together with the `docs/` files it points to — as
the authoritative project context for the session. You do not need to re-explain any of the
planning decisions — they are all in this document set. When a deferred item comes up, Claude
Code should flag it explicitly rather than making a unilateral choice. If you add a standalone
addendum again in future, ask Claude Code to fold it into the relevant `docs/` file (as was done
here, and as was done with the original three addenda before that) rather than leaving it
appended at the end — that's what keeps deferred items from being missed when their phase
arrives, and what keeps this Manifest accurate.

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
