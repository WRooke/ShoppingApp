# Build Phases — Process

## Build Phases

Build and verify each phase before starting the next. Each phase ends with a working,
testable state. Do not skip ahead.

### Terms used in these build-status files
These files are a historical log. Rather than rewrite them, the words they use are defined once here.

| Term | Meaning |
|---|---|
| **Chunk N.M** | One numbered build step inside a phase (for example Chunk 5.3 is the third step of Phase 5). Each phase file lists its chunks with a checkbox. |
| **Phase 3.9 and M0–M8** | Phase 3.9 is the switch of the AI provider from Anthropic Claude to Google Gemini. M0–M8 are its nine steps; the closing check ("end-of-migration review", also called "M-review" in the log) also covered the Phase 4 review that had been postponed. |
| **Kickoff** | The planning conversation held at the start of a phase. It splits the phase into chunks and records the design decisions made. A "kickoff decision N" is the Nth numbered decision in that phase's list at the top of its file. |
| **Chunk 6.7 batch ("7.1–7.8")** | The user-feedback work done 2026-09-29 to 2026-10-01 was tracked in commit messages as "Chunk 7.1" to "7.8". It is all part of Chunk 6.7, not a separate phase: 7.1 mockup review of the ingredient panel; 7.2 AI substitution-flagging removed; 7.3 the checklist re-consolidates on every load; 7.4 the Review screen removed; 7.5 the checklist ingredient panel; 7.6 panel back-navigation; 7.7 Status page fixes; 7.8 the batch's review. |
| **Layer A–D** | The four parts of Ingredient Unit Handling: A unit spellings, B known units per ingredient, C duplicate-unit hint, D bought by the bunch. See [docs/ingredient-handling.md](../ingredient-handling.md#ingredient-unit-handling). |
| **Fix 1–5** | Five pieces of ingredient-name matching work (2026-09-27/28); see the key at the top of [docs/ingredient-handling.md](../ingredient-handling.md). |
| **Gate** | Either a *build gate* (work held back until something else is done) or a *runtime gate* (an on/off switch in `.env`, such as `AI_EXTRACTION_ENABLED`). Newer text avoids the word and says "switch" or "check". |
| **Spike** | A short throwaway experiment to prove a risky idea works before building it properly (for example the AnyList spike in Phase 1.5). |
| **Stage A / Stage B** (AnyList fault-finding spike) | The two parts of that investigation: A is finding the cause, B is the fix. They are not project phases. |
| **Carried-forward item N** | The Nth entry in the "carried forward" list of the chunk before it. |
| **The maintainer** | The project owner, who runs the household's shopping app and makes the open decisions. |
| **Mockup approval step** | A UI change needs an approved mockup before it is built (the log sometimes calls this the "mockup gate"). See [docs/ui-ux.md](../ui-ux.md). |

### Phase workflow & progress tracking
Each phase is broken into a small number of chunks — five is a reasonable default, not a rule;
a phase can have more or fewer if its work doesn't split evenly into five. A chunk is a
self-contained slice of a phase that one session can pick up, finish, and verify without leaving
the phase half-wired.

- Chunks are tracked as checkbox lines (`- [ ] ...` → `- [x] ...`) directly under their phase,
  in place of a flat bullet list — progress state lives next to the spec it tracks instead of in
  a separate document that can drift, same reasoning as folding the old addenda into this file
  rather than appending them (see the "Document history" paragraph at the top of CLAUDE.md).
- Tick a chunk's box only once it's actually built and verified — matches the existing rule that
  a phase "isn't done when it's manually clicked through once, it's done when its own tests
  pass" (see [Code Architecture & Maintainability](../code-architecture.md#code-architecture--maintainability)); the
  same standard applies at chunk granularity, not just at the whole-phase level.
- **Tests per chunk (2026-10-11):** a chunk's tests go at the lowest layer that can observe the
  behaviour and must not duplicate an existing assertion (search first; extend or parametrise
  rather than adding a sibling) — see
  [Tests](../code-architecture.md#tests--pytest-tests-mirroring-app). Verify a chunk with the
  smallest sufficient run (the tests for what changed); run the whole suite only at the
  phase-end review below, before a deploy, or after touching shared test/runtime infrastructure.
- **Plain-language check:** before ticking a chunk, confirm the docs and comments you wrote follow the
  [Plain-language documentation standard](../code-architecture.md#plain-language-documentation-standard).
- **Phase-end review:** before starting the next phase, re-read every section of this file the
  finished phase touches — not just its own chunk list, but Data Model, Security, API
  Conventions, Scaling Logic, etc., wherever relevant — and confirm each requirement is actually
  implemented, not just plausible. Record the review as its own checked-off line at the end of
  the phase's chunk list (e.g. `- [x] Phase N review — see docs/build-status/process.md > Phase workflow &
  progress tracking`). A gap the review turns up gets fixed, or logged as an open item /
  [Deferred Decisions](../deferred-decisions.md#deferred-decisions) entry if it's a genuine design decision to defer —
  never silently dropped.
- Phases are chunked out at that phase's own kickoff, not speculatively ahead of time — the same
  "do not implement deferred items speculatively" norm this file already applies everywhere
  else. Phase 2 (see phase-2-recipe-library.md) was the first phase chunked this way; Phases 3–6 got their chunk lists when
  each was reached.

