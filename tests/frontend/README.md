# tests/frontend/ — automated headless-browser regression tests

Added at the 2026-09-13 code review (Stage 4.3 of the fix plan) once the frontend had grown
real, confirmed bugs that shipped invisibly — no automated frontend coverage existed at all.
Built on `scripts/cdp.py` (stdlib-only Chrome DevTools Protocol client against Edge) — this
project has **no Node, no Playwright, no `chromium-cli`**, on either the dev PC or the NUC, and
never will (see `HEADLESS_VERIFY.md`).

## What lives here vs. a manual `scripts/cdp.py` session

- **Here (`tests/frontend/`)**: a *regression test* — something that broke once for real (or
  is a near-miss the review found), written so it can never silently break again. Runs every
  time with the rest of `tests/` (`pytest tests/`, `scripts/validate_develop.py`, and
  `scripts/deploy.py`'s pre-push test gate all pick these up automatically — same `tests/`
  tree, no separate wiring).
- **A one-off manual `scripts/cdp.py` session (per `HEADLESS_VERIFY.md`)**: exploratory
  checking *while building* a new feature, before there's anything stable enough to assert on
  yet — "does this even render", "does this button do roughly the right thing". Once the
  feature is stable and you know what "correct" looks like, promote the check that matters
  into a test here instead of leaving it as a one-off script in the scratchpad.

## Needs a real Edge or Chrome installed

This is the one part of `tests/` with that requirement. `scripts/cdp.py`'s own
`_find_browser()` raises a plain `RuntimeError` if neither is found — pytest surfaces that as
a normal test **failure**, not a skip. That's deliberate: a misconfigured machine must never
be able to silently "pass" by skipping real frontend coverage. If this directory's tests fail
everywhere with that error, install Edge (or set `CDP_BROWSER` to a Chrome path) rather than
skipping the suite.

## How it works

`conftest.py`'s session-scoped `server_url` fixture is the automated version of
`HEADLESS_VERIFY.md`'s own manual TL;DR recipe: one throwaway `app.main` subprocess for the
whole test session, on its own scratch `DATABASE_PATH`/`LOGS_PATH`/`IMAGES_PATH` (never the
real `data/mealplanner.db`), `AI_EXTRACTION_FAKE_MODE=true` (zero key, zero cost), a free
port. A session-scoped `browser_process` launches ONE headless Edge; the per-test `browser`
fixture gives each test its own `scripts.cdp.Browser` in an isolated browser context inside it
(empty localStorage/sessionStorage/cookies/cache, same 492x757 viewport a launched Edge renders),
so a test starts clean without paying for a launch. Anything else that needs a `Browser` must use
`process=browser_process` — the shared Edge is one per xdist worker, on its own free DevTools port. `Browser._settle()` waits
for the page to be idle (loaded, no fetch/XHR/short timer in flight, DOM quiet) rather than
sleeping a fixed time; use `wait_for`/a polling `_wait` for anything slower. The per-test `api` fixture gives each test a plain `httpx.Client` against
the same scratch server, for setup and for cross-checking a UI action's result against the API
directly rather than trusting the DOM alone — the same discipline `HEADLESS_VERIFY.md` already
asks for in a manual session.

**What belongs here:** only behaviour that exists in the browser — DOM state, inline errors, focus,
undo/toast, navigation, persistence across reload, layout. Do not re-assert a backend rule a
router/service test already pins (use the `api` fixture to cross-check that the UI really did
something, not to re-test the rule). Several of these run in parallel (`pytest tests/frontend -n 4`, or the whole suite with `-n 8 --dist loadfile`;
each xdist worker gets its own server and its own Edge on a free port). Prefer re-mounting a view,
stubbing a clock, or `wait_for` to waiting out a real timer.

These tests are slower/heavier than the rest of `tests/` (a real browser + a real server
subprocess per session) — that's an accepted, deliberate cost for the coverage. They carry the
`frontend` marker, so `pytest -m "not frontend"` skips them for a fast loop.
