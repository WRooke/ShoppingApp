# Build Phases — Process

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
  pass" (see [Code Architecture & Maintainability](../code-architecture.md#code-architecture--maintainability)); the
  same standard applies at chunk granularity, not just at the whole-phase level.
- **Phase-end review:** before starting the next phase, re-read every section of this file the
  finished phase touches — not just its own chunk list, but Data Model, Security, API
  Conventions, Scaling Logic, etc., wherever relevant — and confirm each requirement is actually
  implemented, not just plausible. Record the review as its own checked-off line at the end of
  the phase's chunk list (e.g. `- [x] Phase N review — see CLAUDE.md > Phase workflow &
  progress tracking`). A gap the review turns up gets fixed, or logged as an open item /
  [Deferred Decisions](../deferred-decisions.md#deferred-decisions) entry if it's a genuine design decision to defer —
  never silently dropped.
- Phases are chunked out at that phase's own kickoff, not speculatively ahead of time — the same
  "do not implement deferred items speculatively" norm this file already applies everywhere
  else. Phase 2 below is the first phase chunked this way; Phases 3–6 get their chunk lists when
  each is actually reached.

