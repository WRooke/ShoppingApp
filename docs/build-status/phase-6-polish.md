# Build Status — Phase 6: Polish

### Phase 6 — Polish

**Chunked 2026-09-19/20 at kickoff**, per
[Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking). This phase
touches almost every screen in the app (a deliberate full visual refresh, not a targeted-fixes
pass), so kickoff planning ran longer and turned up more than usual — thirteen decisions resolved
with the maintainer, plus two real cross-cutting risks found by re-verifying the plan against the
actual repo state before any chunk started. Both are recorded below because they materially
change chunk order and scope, not just because they happened.

#### Kickoff decisions

1. **Home tab** — quick actions only: "New session" and "New recipe" buttons, no recent/past
   sessions list. Also shows a **"Continue: `<label>`" button per session currently
   `status='active'`** (most-recently-updated first; `label` is nullable, fall back to
   "Continue: Session #`<id>`") — a session mid-edit is the thing you're most likely to want the
   instant the app opens, distinct from *finished* sessions which belong in history (Chunk 6.6).
2. **Two usability additions selected from a brainstormed shortlist:**
   - **Undo toast on delete** — deleting a recipe, ingredient, session slot, or Settings row
     shows "Deleted — Undo" instead of no recovery path. One shared toast component (Chunk 6.1),
     reused everywhere a delete already exists. Undo = re-POST the just-deleted data client-side
     within the toast's visible window; no backend change.
   - **"Add to session" from a recipe** — a button on a recipe's library card and detail page
     adds it straight into the current active session (one active session → add directly; more
     than one → a small picker; none → offer to start a new session with it pre-added).
   - Considered and **not** built: swipe-gestures on the checklist, "repeat last session".
3. **Smaller mobile-usability fixes, folded into whichever chunk touches the screen:**
   `inputmode="decimal"`/`"numeric"` on quantity/servings inputs; visible press/tap feedback on
   buttons (a functional transition, not decorative); a nav-icon badge (dot on "Plan" when a
   session is active/unpushed, on "Recipes" for pending AI processing); `navigator.share()` on a
   recipe or the checklist.
4. **Shopping List Store Layout (store setup UI + store-sorted rendering) — deferred back out of
   Phase 6.** Originally reversed into Phase 6 scope by an earlier planning session; the
   maintainer judged it needs its own focused kickoff rather than riding along here. Doc
   corrections made as part of this kickoff: [checklist-and-shopping.md > Shopping List Store
   Layout](../checklist-and-shopping.md#shopping-list-store-layout) and the
   [Deferred Decisions](../deferred-decisions.md#deferred-decisions) rows for "Multi-shop
   support" / "Shop layout reorganisation" / "Section vocabulary — final list" now read
   "in scope, UI build deferred, no reserved phase" instead of "resolved, Phase 6". The schema
   (`stores`/`store_sections`/`product_sections`) and `services/product_sections.py`'s background
   AI-tagging call are untouched.
5. **Visual polish scope: full refresh**, not targeted fixes only — palette, typography, and
   every component's visual style redone against [UI/UX](../ui-ux.md)'s design direction, even
   where a component is already functionally fine.
6. **Oversized-file cleanup — skip for now.** No dedicated chunk, no opportunistic-splitting
   mandate. (File-size numbers drift fast on this project — see the cross-cutting-risk note
   below on re-checking rather than trusting any number written down here.)
7. **Session history gets a per-session recipe expand** — each past session expands to show its
   recipes (name/day/servings), each linking to its detail page. Chunk 6.6.
8. **"The usuals" get a stock-check prompt, not a bare checkbox.** Deliberately **not** inventory
   tracking (no quantity ever recorded — see [Explicitly Out of
   Scope](../project-overview.md#explicitly-out-of-scope)): a due item asks "Add it, or do you
   have enough to last another `<cadence_days>` days?" with **Add to list** or **"I'm stocked,
   skip this time"** (flat reset of `last_added_at` to now, nothing sent to AnyList — no custom
   shorter re-check interval). Chunk 6.3b.
9. **Six gaps confirmed against the actual code, each folded into an existing chunk:** a
   `?cuisine=`/`?protein=` filter on `GET /recipes` + quick-filter chips (6.2); Settings
   restructured from one long scroll into an index + drill-down sub-pages, one `#/settings/…`
   route per section (6.4); a session slot's recipe name linked to its recipe page (6.3); a
   shared "Back" component using `history.back()` with a Home fallback, replacing five files'
   worth of hardcoded back-destinations (`capture.js`, `capture-review.js`, `recipe-form.js`,
   `session-review.js`, `sessions.js`) (built 6.1, applied 6.2–6.4); a "Pushing…" loading state
   on `checklist.js > doPush()` (6.3b); switchable (not just automatic) dark mode — a
   Light/Dark/System control in a new Settings "Appearance" section (toggle in 6.4, token
   groundwork in 6.1).
10. **Four UI decisions:** bottom nav icons → **emoji** (🏠 📖 📋 ⚙️ 📊), replacing the current
    `<span class="nav-icon">home</span>`-style text-caption placeholders (confirmed a literal
    placeholder, not a design choice); accent colour → **muted blue** (~#2f5f8f) *(superseded —
    see the Chunk 6.1 mockup-review note below: blue tested poorly in light mode, teal replaced
    it there)*; Settings navigation → **index + drill-down sub-pages** (tabs and accordion
    considered, declined); weekly calendar interaction → **tap-to-assign**, not drag-and-drop
    (touch-drag reliability at <400px was the concern).
    **Chunk 6.1 mockup review (2026-09-19), resolving the accent colour properly per-theme
    rather than one colour for both:** a live mockup (Artifact, with a click-through swatch
    picker) found the originally-picked blue read poorly against the light theme's warm ground —
    replaced there with **teal (#1f6b63)**, chosen from six real candidates compared side by
    side. Blue (#7db0e0) was re-compared against five dark-mode alternatives and confirmed as the
    better fit for dark specifically — **kept for dark mode only**. Typeface confirmed as
    **IBM Plex Sans + IBM Plex Mono** (compared against four other pairings live in the same
    mockup). This is the final palette — tokens.css implements exactly this, not the single
    "muted blue" pick above.
11. **Two more trust/resilience additions**, motivated by the real AnyList bugs the 2026-09-18
    fault-finding spike found (see `anylist-fault-finding-spike.md`): a "Last synced with
    AnyList" indicator on the checklist screen itself, not just Diagnostics (6.3b — re-check
    against whatever AnyList strategy has shipped by the time this is built); a red dot on the
    Diagnostics nav icon on a recent unresolved error (badge mechanism in 6.1, wiring in 6.4).
12. **A "smoothness" pass** (perceived speed / not losing state / less friction, distinct from
    the feature-shaped additions above): draft autosave on forms (6.2), scroll/list-state
    preserved on Back (6.1's component, applied throughout), skeleton loading placeholders
    instead of bare "Loading..." text (6.1), a small step indicator on multi-step flows (6.2,
    6.3, 6.3b), a sticky primary-action button pinned above the bottom nav on long screens (6.1,
    applied 6.2/6.3/6.3b/6.4), numeric steppers next to quantity/servings fields, smarter
    defaults (adding a recipe to a session suggests the next empty day). Two trade-offs raised
    and resolved toward the simpler option: **no optimistic UI updates** (real rollback
    complexity for a local-network round-trip that's already fast) and **the Undo toast dies on
    navigation** rather than persisting across a route change.
13. **Mockup-before-build — standing process rule for this phase.** Every chunk gets a visual
    mockup (phone + desktop width, reflecting the decisions above) shown and signed off *before*
    real frontend implementation starts for that chunk. A chunk's checkbox is still only ticked
    once actually built and verified — the mockup is a gate before the build, not a substitute
    for it.

#### Known cross-cutting risks (found re-verifying this plan against the repo before Chunk 6.1 started)

- **An active AnyList decision touched the same files as the checklist/push work — since
  resolved.** A separate investigation (`anylist-fault-finding-spike.md` +
  `docs/build-status/phase-3.9-ai-provider-migration.md`-adjacent live work) found a permanent
  AnyList server-side bug in `set-list-item-quantity` and, at the time Phase 6 was being
  planned, had 20 candidate fixes on the table with nothing chosen. Building the checklist-screen
  push-progress/sync-indicator UI against a mechanism about to be rewritten risked wasted work or
  a merge collision. **Resolution:** Chunk 6.3 was split — the session/planning-screen half has
  no AnyList dependency and proceeds normally; the checklist/push half became **Chunk 6.3b**,
  gated on that decision shipping. **As of this kickoff the gate is lifted** — `git log` shows
  the bug resolved (`2605a66`, lossless delete+re-add for unit-bearing updates, on top of the
  `246873f` ADD-path fix). Chunk 6.3b can proceed, but must re-read `checklist.py` /
  `anylist_client.py` as they now actually stand before building — not assume this document's
  descriptions of them are current.
- **The real automated frontend regression suite asserts on DOM this phase restructures.**
  `tests/frontend/test_frontend_regressions.py` (added by the 2026-09-13 code review, runs with
  `pytest tests/`) selects `.settings-row`/`.settings-name-input`/`.settings-notes-input` — used
  on **both** `#/settings` and `#/plan/<id>`, confirming it's a shared class, not Settings-only —
  and navigates straight to `#/settings` expecting a card's rows to be immediately present.
  Chunk 6.1's core-component rebuild and Chunk 6.4's index+sub-page restructure will break these
  unless updated in the same commit that changes the underlying structure. **Standing rule: run
  `pytest tests/frontend/` as part of every chunk's own verification**, alongside the
  phone-width headless-CDP pass, not deferred to the Phase 6 review.
- **§0c fake-mode discipline is unchanged for this whole phase** — `AI_EXTRACTION_FAKE_MODE=true`
  covers the capture progress indicator (6.2), `ANYLIST_FAKE_MODE=true` covers the checklist
  push/sync indicators (6.3b). Nothing in Phase 6 needs a real Gemini or AnyList call to build or
  verify.

#### Chunk list

- [x] **Chunk 6.1 — Design system foundation + Home tab.** Formalise `static/css/app.css` into a
      real token system (colour — **teal `#1f6b63` in light mode, blue `#7db0e0` in dark**, see
      the mockup-review note above; spacing; type scale — **IBM Plex Sans + IBM Plex Mono**,
      self-hosted) per [UI/UX](../ui-ux.md)'s design direction, plus a dark-mode token variant and a
      `data-theme` override mechanism (applied before first paint). Rebuild core shared
      components once: bottom nav (emoji icons 🏠📖📋⚙️📊 replacing the text-caption
      placeholders, plus nav-badges — a dot on "Plan" when active/unpushed, on "Recipes" for
      pending AI tasks, and the mechanism for a red Diagnostics-error dot wired up in 6.4);
      buttons (with press/tap feedback); cards; form inputs/labels (`inputmode` defaults); status
      badges/dots; a standard loading/empty/error pattern built as skeleton placeholders; a
      shared toast/snackbar (auto-dismiss, one at a time, dies on navigation); a shared "Back"
      component (`history.back()`, Home fallback, preserves scroll/list-state on return); a
      sticky primary-action-button pattern. Build `static/js/home.js`: "New session"
      (→ `#/plan/new`), "New recipe" (→ capture/manual-entry), and a "Continue: `<label>`" button
      per active session (`GET /sessions?status=active`, already existing). Split `app.css` if it
      passes ~300–400 lines. Verify at phone width (~390–430px) and desktop via
      `scripts/cdp.py`/`HEADLESS_VERIFY.md`, plus `pytest tests/frontend/` for anything it
      touches.

      **Done 2026-09-20 (commits `8811614`, `1192a75`).** New `static/css/tokens.css` +
      `components.css` (app.css trimmed from 427 to a header comment + the not-yet-migrated
      feature sections — recipe/ingredient rows, settings rows, dup-warn, pending-AI badge,
      have-toggle, log tail — which keep working unchanged via the legacy token names
      `--bg`/`--surface`/`--border`/`--text`/`--text-dim`/`--accent`/`--green`/`--amber`/`--red`/
      `--grey` tokens.css keeps defined for exactly that reason). IBM Plex Sans/Mono self-hosted
      (`static/fonts/*.woff2` + `OFL.txt`, ~76 KB total — fetched the real latin-subset files
      from Google's CDN rather than linking it live, since this app shouldn't need internet
      access to render its own UI). New `static/js/toast.js`, `back-link.js`, `nav-badges.js`,
      `home.js` — infrastructure Chunks 6.2–6.4 consume, not yet wired into any existing screen's
      hardcoded back-links/deletes (that's each of those chunks' own job).
      **One real bug found and fixed doing the verification, not just a visual check**:
      `api.js`'s `request()` already unwraps the `{ok, data}` envelope (returns `body.data`), so
      `home.js`/`nav-badges.js`'s `res.data.items` was always `undefined` and the Continue-session
      card silently never rendered — caught by actually creating a session and checking the live
      DOM via `scripts/cdp.py`, not by assuming the API shape. Also fixed in passing:
      `.primary` was previously scoped as `button.primary` in app.css, which never matched
      `<a class="btn primary">` (recipes.js's "+ Add recipe" link) — an existing, unnoticed gap,
      fixed by dropping the tag qualifier. Suite **535 pass** (532 backend + 3 frontend
      regression, unaffected by this chunk). Live headless-CDP verification at phone width
      (390×896) and desktop (1280×900), explicit light and dark: emoji icons render, nav badges
      show/hide correctly, the Continue card shows both a real label and the null-label
      `Session #<id>` fallback, dark resolves to `#7db0e0` / light to `#1f6b63` with zero console
      errors, and recipes/plan/settings/diagnostics all still render cleanly (confirms the
      app.css trim broke nothing outside this chunk's scope).
      **Known, expected gaps, not bugs**: dark mode has no toggle UI yet (ships in Chunk 6.4);
      a handful of not-yet-migrated `app.css` sections (dup-warn, pending-AI badge, have-toggle,
      log tail) still use hardcoded light-only hex, so they won't look right in dark mode until
      their own chunk migrates them — not user-reachable yet since there's no toggle. The
      "Recipes" nav-badge slot exists in markup but is deliberately unwired (pending-AI-processing
      detection is Chunk 6.2's own job, a recipes-domain question).
      **Process note, worth recording**: this chunk's files were found already committed as a WIP
      checkpoint (`8811614`) by a concurrent session working on unrelated deploy-script changes
      in the same working directory, which needed a clean git tree for its own testing and
      committed this session's in-progress work rather than losing it. Confirmed via diff that
      nothing diverged — the checkpoint was this session's own pre-verification code, continued
      normally. Flagging because it's a real, repeatable gotcha for this project's workflow (see
      memory `anylist-fault-finding-spike-2026-09-18.md`'s "concurrent sessions" note), not
      because anything here needed reconciling.
- [x] **Chunk 6.2 — Recipe & capture screens.** Apply the Chunk 6.1 design across `recipes.js`,
      `recipe-form.js`, `recipe-edit.js`, `capture.js`, `capture-review.js`. A visible
      progress/step indicator during the AI capture calls (extraction → substitution flagging →
      section suggestion) — no more silent hang. Visible field labels on the
      name/qty/unit/preparation/substitute/note/amount/unit rows currently relying on
      placeholder-only text. "Add to session" button on recipe cards/detail (kickoff decision
      #2) + Undo toast on recipe/ingredient deletion. `?cuisine=`/`?protein=` filter +
      quick-filter chips. Shared Back component swapped into all three files' hardcoded links.
      Draft autosave on the editable forms; numeric steppers; sticky Save/Confirm button. Verify
      at phone width + `pytest tests/frontend/`.

      **Done 2026-09-20 (mockup approved unchanged, then implemented + verified).** Backend:
      `?cuisine=`/`?protein=` exact-match filter on `GET /recipes`
      (`services/recipes.py`/`routers/recipes.py`) — chips are built client-side from the
      library's own already-loaded cuisines, not a fixed vocabulary, so no new "distinct
      cuisines" endpoint was needed. Frontend: the capture progress indicator is a rotating
      status label + spinner, deliberately **not** a checklist with checkmarks — the whole
      capture is one HTTP request (`capture_recipe()` runs all three Gemini calls before
      responding), so there's no real per-step signal to check off; claiming one was honest
      per §0a/UI-UX tone. Ingredient rows (`recipe-edit.js`, `recipe-form.js`,
      `capture-review.js`, and the substitution panel in `ingredient-swap.js`) now use a shared
      labelled `.mini-field`/`.ing-grid` layout with `+`/`−` steppers, replacing the bare
      placeholder-only inputs. "Add to session" split into its own `add-to-session.js` (one
      active session → add directly; several → an inline `<select>` picker; none → confirm and
      create one). Undo toast wired into both per-ingredient delete (re-`addIngredient` +
      a follow-up `updateIngredient` for substitution fields, since `addIngredient`'s own
      schema doesn't carry them) and whole-recipe delete — the latter needed real care: deleting
      a recipe navigates away, and the shared toast dies on navigation (kickoff decision #12),
      so the navigate is deliberately deferred ~5.3s (just past the toast's own auto-dismiss)
      rather than racing it; Undo cancels the deferred navigate and re-renders in place via the
      existing `restore()` endpoint. Draft autosave (`draft-autosave.js`, new shared module) on
      recipe-level fields only, keyed per-recipe-id for edits and one global slot for capture
      review (a household captures one recipe at a time in practice).
      **Two real bugs found and fixed, not just new code**: (1) `.field`'s Chunk 6.1 rule in
      `components.css` had been silently overridden the whole time by an identical-selector
      leftover rule still in `app.css` (loads after components.css) — found while touching
      these files again for Chunk 6.2, fixed by removing the stale copy; (2) the same
      `button.primary`-only-matches-`<button>` gap flagged in Chunk 6.1 for recipes.js's own
      "+ Add recipe" link turned out to have five more instances across the file family, all
      fixed by the same `.primary` selector already shipped. File-size guideline: split
      `add-to-session.js` out of `recipes.js` (467→396 lines) and `recipe-edit-ingredients.js`
      out of `recipe-edit.js` (480→226); `capture-review.js` (412) and `components.css` (466)
      are left slightly over ~400 as one cohesive concern each, not split further this chunk.
      Verified: full suite **535 pass** (unchanged — this chunk touched no backend logic tests
      exercise beyond the new filter, which has its own coverage via the live check below).
      Live headless-CDP pass (phone width): cuisine chips filter correctly (confirmed against
      the real `?cuisine=` query too), Add-to-session creates/attaches to a session and shows
      its toast, the Back link renders on every screen it was added to, ingredient rows show
      real labels with a working stepper, ingredient delete+Undo round-trips correctly (row
      count restored), recipe delete+Undo does not navigate away prematurely and the recipe is
      genuinely un-archived on Undo, draft autosave survives a navigate-away-and-back, and the
      capture progress indicator + labelled review-screen rows render correctly (capture itself
      stubbed at the `api.recipes.captureUrl` boundary, same technique
      `tests/frontend/test_frontend_regressions.py` already uses for its queued-capture test,
      rather than depending on a real network fetch) — 27 checks, zero console errors anywhere.
- [x] **Chunk 6.3 — Planning screens (`sessions.js` + `session-review.js` only — no AnyList
      dependency).** Apply the design; fix the identical bare-placeholder swap-field problem as
      6.2's. Undo toast on removing a session slot. Session slot recipe name linked to
      `#/recipes/<id>`. Shared Back component applied. Step indicator across session→review; the
      sticky primary-action button on review; adding a recipe suggests the next empty day.
      Verify at phone width + `pytest tests/frontend/`.

      **Done 2026-09-20 (mockup approved unchanged, then implemented + verified).** A slot's
      recipe name is now a real link (`sessions.js`'s `renderSlotRow`), matching what
      session-review's own "which recipe" breakdown already did further down the flow.
      Adding a recipe/leftovers slot now suggests the next day not already used in the
      session (`nextEmptyDay()`) — the backend already accepted `day_of_week` at creation
      (`SessionRecipeCreate`/`LeftoversSlotCreate`), so this needed no backend change, just
      the frontend actually sending it. Undo on "Remove" re-creates the slot from a snapshot
      (add, then a follow-up `updateSlot` for `scaled_servings` on a recipe slot — the create
      payload only covers `day_of_week`). The session-review swap form got the identical
      Chunk 6.2 treatment (`.swap-panel`/`.mini-field`, labelled "This recipe's amount" /
      "Substitute amount" etc. instead of four bare inputs). A shared `Plan → Review →
      Checklist → Push` step indicator (own small copy per file, matching this file family's
      self-contained-feature-file precedent) — the last two steps are inactive placeholders
      here since checklist.js's matching indicator is Chunk 6.3b's own job. Skeleton loading
      + `.empty-state`/`.error-state` applied to both screens. File-size guideline: split
      `session-recipe-picker.js` out of `sessions.js` (446→394 lines) once the new additions
      pushed it over. Verified: full suite **535 pass**; live headless-CDP pass at phone
      width — 18 checks covering the Back link, step indicator on both screens, the empty
      state, the next-empty-day default (confirmed server-side: a first recipe added to an
      empty session lands on day 1), the recipe-name link, remove+Undo (confirmed server-side
      that exactly one slot survives the round trip), and the labelled swap panel — zero
      console errors anywhere.
- [x] **Chunk 6.3b — Checklist & AnyList push UI (`checklist.js` only).** Gate lifted (see
      cross-cutting risks above) — **re-read `checklist.py`/`anylist_client.py`'s current state
      before starting**, don't trust this document's description of them. Apply the design.
      Rework the "the usuals" group into the stock-check prompt (kickoff decision #8). A
      "Pushing…" loading state on `doPush()`. A "Last synced with AnyList" indicator, re-checked
      against whichever AnyList strategy has actually shipped. Step indicator continuing from
      6.3; sticky Push button. Verify at phone width, the tap cycle, the needs-review resolve
      control, + `pytest tests/frontend/`.

      **Done 2026-09-20 (mockup approved with one revision — "Much better! Go ahead!" — then
      implemented + verified).** Mockup sign-off round 1 flagged that a plain spinner during
      push "doesn't fill me with confidence anything's happening"; revised to a rotating
      per-item progress label before implementation started (see below) — the actual
      mockup-before-build gate (kickoff decision #13) working as intended, catching this before
      any code was written rather than after.

      **The "Last synced with AnyList" idea from kickoff decision #11 was replaced, not
      built as originally described**, per a maintainer decision made explicitly for this
      chunk: re-reading `checklist.py > load_checklist()` (Chunk 6.3b's own required
      re-verification step) showed `already_on_anylist` is recomputed fresh on *every*
      checklist page load — there is no stale cached value a timestamp could usefully warn
      about, so a plain "last synced: `<time>`" indicator would always just say "just now" and
      add no information. Shipped instead: a quiet **"Checked against AnyList as of this page
      load"** note (replacing the old bare `statusLine` text, same content just given a
      permanent home instead of only appearing on a fetch failure) plus a **discrepancy warning
      banner** — `.push-discrepancy`, shown only when a push returns `confirmed: false`, naming
      the specific items AnyList didn't recognise — replacing the old bare `alert()`. This is
      exactly the "discrepancy/warning indicator instead of a plain freshness timestamp" case
      the cross-cutting risk note flagged as a live possibility back at kickoff.

      **"The usuals" stock-check prompt** (kickoff decision #8): each due item is now a
      `.usual-card` asking "Add it, or do you have enough to last another `<cadence_days>`
      days?" with **Add to list** (queues it into this push, client-side, same as before) or
      **"I'm stocked, skip this time"** — a new `POST /api/v1/checklist/usuals/{id}/skip`
      endpoint (`app/routers/checklist.py`) that calls the *already-existing*
      `usuals_service.mark_added()` with no push at all, exactly the "reuse the existing stamp,
      just not gated on an actual push" design from kickoff. No new service function needed.

      **The push-progress indicator cycles through the actual item names being pushed**
      ("Adding chicken thighs…" → "Adding jasmine rice…", "Item 2 of 3" beneath), not a static
      spinner or a generic phase label — grounded in the real push list (which the frontend
      already has, unlike the opaque multi-step AI capture calls Chunk 6.2 solved the same
      "one HTTP request, no per-step signal" problem for) rather than invented text. Present
      continuous ("Adding X…"), never past tense, so it never claims an item has actually
      landed on AnyList before the response confirms it.

      **File-size split**: `checklist.js` reached 490 lines once the design-system pass, the
      stock-check rework, and the push/discrepancy additions all landed in one file. Split the
      push-specific machinery (the sticky summary/button, the rotating progress label, the
      discrepancy banner) into a new `checklist-push.js` (`ChecklistPush.renderSummary()` /
      `.renderDiscrepancyBanner()` / `.unmount()`), leaving `checklist.js` at 364 lines for the
      load/render/tap-cycle/stock-check logic. `.have-toggle` and the checklist row styling
      moved out of `app.css` into `components-screens.css`, tokenized (no more literal hex
      colours) along with everything else this chunk touches.

      Verified: full suite **535 pass**; a throwaway phone-width (414×896) headless-CDP script
      — **21/21 checks pass**: the step indicator, Back link, sync note, 3 ingredient rows, the
      stock-check prompt's both actions (skip confirmed via the API that `last_added_at` was
      stamped with the usual no longer due, and with no push triggered), the have/need tap
      cycle, the live summary line, the push button's spinner + rotating "Adding `<item>`…"
      label + "Item N of M" note appearing synchronously on click (verified immediately after
      the click event rather than after a delay, since a local fake-mode push resolves faster
      than the 1.1s rotation interval — the real multi-second AnyList round trip the mockup
      modelled isn't reproducible against a local test server), a real push marking the session
      `pushed`, and — via a stubbed `push()` response, the same technique the existing suite
      already uses for the queued-capture case — the discrepancy banner rendering with the
      specific unconfirmed item named. Zero console errors throughout.
- [x] **Chunk 6.4 — Settings & Diagnostics.** Restructure Settings into an index + one
      `#/settings/<section>` sub-page per card (staples, product units, substitutions, usuals,
      ingredient aliases, unit synonyms, coarse ingredients); shared Back returns to the index. A
      new "Appearance" section with the Light/Dark/System toggle (persisted `localStorage`) atop
      Chunk 6.1's tokens. Apply the design to Diagnostics (visual reskin only — functionally
      complete already) and wire its `/recent-errors` check into the nav-badge mechanism. Fix the
      Settings scroll-position bug (in-place DOM update on Save/Delete, not a full rebuild).
      Visible field labels on the bare product-units/staples rows. Undo toast on every Settings
      card's row delete. Verify at phone width with a ~20-row list to confirm the scroll fix
      holds, + `pytest tests/frontend/` (the suite navigates straight to `#/settings` today —
      update it for the new sub-page shape in this same chunk).

      **Done 2026-09-20 (mockup approved unchanged — "All looks and works excellently!" —
      then implemented + verified).** `#/settings` is now an index card (`section-list`) listing
      all 8 rows (Appearance + the 7 existing sections) with a live count per row; each row links
      to its own `#/settings/<section>` route, which `router.js` already passed the hash's
      `param` through to `SettingsView.mount(root, param)` unchanged — no router change needed.
      Appearance is a new Light/Dark/System button group (`aria-pressed`) writing straight to
      `localStorage["theme"]` and the `data-theme` attribute Chunk 6.1's tokens.css already
      switches on; the index's own Appearance row reads the same value back via
      `SettingsAppearanceView.label()` so the two never drift.

      **The scroll-position bug is fixed for every card, not just staples/product-units**: every
      Settings row's Save now mutates the in-memory object and leaves the existing `<input>`s
      alone (no rebuild at all), and every delete uses the shared `settings-row-actions.js` —
      `row.remove()` plus an Undo toast that re-`POST`s from a snapshot and appends the restored
      row in place — replacing the old `listBody.innerHTML = "" ` + full re-fetch on every single
      mutation. The three flat-list cards (staples, product units, usuals — plus
      coarse-ingredients) get full in-place add too; the three grouped-list cards
      (substitutions, ingredient aliases, unit-synonyms) keep in-place delete but a full rebuild
      on add — a deliberate, documented simplification (add always happens at the page bottom,
      where a rebuild doesn't disrupt scroll position, whereas delete commonly happens after
      scrolling down to find a row). Bare product-units/staples inputs now have real
      `<label>`s via a shared `mini-field` pattern, matching Chunk 6.2/6.3's ingredient/swap rows.
      Diagnostics got a skeleton-loading treatment for its status panel; otherwise confirmed
      already compatible with the design system from Chunk 6.1 with no changes needed. The
      Diagnostics nav-badge (red dot on a recent unresolved error) was already wired in Chunk
      6.1's `nav-badges.js` — re-confirmed working here, no new code required.

      **File-size split** (same pattern as every prior chunk): `settings.js` reached 550 lines
      once the index, Appearance, and the 7 sections' worth of new labelled-field/Undo-toast
      logic first landed in one file. Split into `settings-appearance.js` (`renderCard`,
      `label()`), `settings-staples.js`, and `settings-product-units.js` (each self-contained,
      `renderCard` clearing `root` and adding the Back link itself); `settings.js` is now just
      the index + a `SECTION_MOUNTS` dispatch table (100 lines) — the other five sections'
      `renderCard()`s don't self-contain the Back link, so the dispatch wraps those five with a
      small `withBack()` helper instead of duplicating that wrapping five times. `components.css`
      also passed the same guideline (522 lines after four chunks' worth of additions) — split
      into `components.css` (333 lines, core shell/nav/buttons/cards/forms/status/skeleton/toast/
      back-link) and a new `components-screens.css` (199 lines, everything screen-specific:
      capture progress, filter chips, ing-grid/swap-panel, step-list, Settings index/theme-switch,
      Home's continue-card) — mirrors the existing tokens.css/components.css split precedent.
      `index.html` updated with all four new `<script>`/`<link>` tags.

      **One test fixed, not just added**: `tests/frontend/test_frontend_regressions.py`'s
      `test_clearing_a_usual_items_note_persists_after_reload` navigated straight to `#/settings`
      and expected the usuals card's rows immediately — exactly the cross-cutting risk flagged at
      this phase's kickoff. Fixed in the same commit by navigating to `#/settings/usuals` instead
      (the usuals card's own new route), not deferred. Verified: full suite **535 pass**; a
      throwaway phone-width (414×896) headless-CDP script — **28/28 checks pass**: the index's 8
      rows, tap-to-navigate into a sub-page, the Light/Dark toggle (sets `data-theme`, persists to
      `localStorage`, survives navigating away and back within the same browser instance), adding
      6 staples in place, deleting the middle one with **scroll position unchanged**
      (`window.scrollY` identical before/after — the actual bug this chunk fixes) and an Undo
      toast that restores it, product-units' labelled fields, all five remaining sub-pages
      rendering with their Back link, and Diagnostics' status panel — zero console errors
      throughout.
- [x] **Chunk 6.5 — Weekly planner calendar view.** A 7-day grid on the session workspace,
      visual-layer-only (`day_of_week` already set/stored, Phase 4 Chunk 4.4 — no data-model
      change here). Tap-to-assign interaction (kickoff decision #10) — tap a slot, then tap the
      target day. Verify at phone width — the hardest layout in this phase under 400px; a
      horizontally-scrollable week strip or day-at-a-time view are acceptable fallbacks if a
      fixed 7-column grid doesn't fit.

      **Done 2026-09-20 (mockup approved after two revisions — "approved" — then implemented
      + verified).** A strict 7-column grid was confirmed unworkable at phone width during the
      mockup pass itself, per this chunk's own pre-authorised fallback: shipped as a
      **vertically-stacked "day sections" layout** instead (Unassigned, then Mon–Sun, each a
      card showing its slots) — a real 7-day breakdown, just laid out top-to-bottom rather than
      left-to-right, which also means it scrolls naturally on a phone instead of needing a
      horizontal-scroll or day-picker fallback.

      **Two real usability bugs found and fixed during mockup review, before any code was
      written** — the mockup-before-build gate (kickoff decision #13) doing its job twice in
      one chunk: (1) the initial slot row crammed the recipe name alongside the servings
      dropdown, move button, and Remove on one line — the name ellipsis-truncated for anything
      longer than a few words. Fixed by giving the name its own full-width line that wraps,
      with every control on a second line below it. (2) The move-mode highlight covered the
      whole day card, but the click handler was only wired to the header text underneath it —
      tapping the highlighted border or body did nothing, which reads as broken, not just
      confusing. Fixed by moving the click handler to the whole card, matching what the
      highlight visually promises.

      **A third bug — this one only findable by actually building it, not the mockup** — was
      caught by the chunk's own updated regression test (see below), not by hand-testing: the
      "Unassigned" section only rendered when it already had something in it, so once every
      slot in a session had a day assigned, there was no way to tap a target to *unschedule* a
      slot at all — the section a user would need to tap simply didn't exist. Fixed by also
      showing Unassigned whenever a move is in progress, even if it's currently empty.

      **File-size splits**: `sessions.js` reached 431 lines once the grid/tap-to-assign logic
      replaced the old flat list + day `<select>` (removed along with the now-pointless
      "Reorganise by day" button and per-row ↑/↓ reorder arrows — the grid's day-grouping IS
      the reorganisation now). Split into `sessions.js` (232 lines — session list, label
      editing, add/review wiring) and a new `session-week.js` (238 lines — the grid, tap-to-
      assign state machine, and per-slot servings/move/remove controls), matching this file
      family's established self-contained-feature-file precedent
      (session-recipe-picker.js, checklist-push.js). New `.week`/`.day-section`/`.slot-row`/
      `.move-banner` styles added to `components-screens.css`.

      **One pre-existing test updated, not just fixed**:
      `test_unscheduling_a_session_slot_day_persists_after_reload` drove the now-removed day
      `<select>` directly — updated in the same commit to drive the move-button →
      tap-Unassigned flow instead, and this rewrite is exactly what caught the Unassigned-
      target bug above (the test failed against the *new* UI for a real reason, not because
      the selector was stale).

      Verified: full suite **535 pass**. A throwaway phone-width (414×896) headless-CDP script
      — **22/22 checks pass**: an empty session's empty-state + Unassigned section, a long
      recipe name rendering in full with no truncation, 8 sections total (7 days + Unassigned),
      correct day grouping, the move banner naming the right recipe, the highlight applying to
      every non-source section, a real move confirmed via the API, moving *back* to Unassigned
      (the bug fix, confirmed via the API), Cancel leaving `day_of_week` untouched, the
      servings select and Remove-with-Undo still working per-slot — zero console errors
      throughout.
- [ ] **Chunk 6.6 — "Mark cooked" + Session history + Archive session.** A recipe-detail button
      incrementing `recipes.times_made` / stamping `last_made_at` (first code to write either
      column) — instant action, toast confirmation, no dialog. Extend the Plan screen with a
      "past sessions" view (`pushed`/`archived`, most recent first), each row expanding to show
      its recipes (name/day/servings, from `session_recipes`) linking to their detail pages — no
      new bottom-nav destination. Wire the existing but UI-less `POST /sessions/{id}/archive`
      into an "Archive" button (gap found mid-planning — the endpoint existed, nothing called
      it), with the Undo toast reverting `status` to `'active'`. For a pushed session, surface
      its `shopping_history` snapshot alongside the recipe list if cheap to add (nice-to-have).
- [ ] **Chunk 6.7 — User testing with secondary users; gather feedback.** Manual pass with the
      secondary/non-technical household member(s), after the visual/usability work above, not
      before. Quick fixes land in this chunk; bigger findings become
      [Deferred Decisions](../deferred-decisions.md#deferred-decisions) rather than expanding
      Phase 6 indefinitely.
- [ ] **Phase 6 review** — re-check against [UI/UX](../ui-ux.md),
      [Checklist, AnyList Push & Shopping List Layout](../checklist-and-shopping.md) (confirm the
      store-layout deferral note landed correctly and nothing there was silently half-built),
      [Data Model](../data-model.md) (`recipes.times_made`/`last_made_at`),
      [Code Architecture & Maintainability](../code-architecture.md), and
      [Diagnostics & Logging](../diagnostics-and-logging.md), per
      [Phase workflow & progress tracking](./process.md#phase-workflow--progress-tracking).
      Confirm Chunk 6.3b's gate history is recorded accurately (it was lifted before that chunk
      started, not left permanently blocked). Update
      [Deferred Decisions](../deferred-decisions.md#deferred-decisions) rows this phase resolves
      (Home tab content, Settings scroll bug, weekly calendar, mark-cooked).

**Deliverable:** The app looks and feels like a finished, deliberately-designed tool rather than
a series of incrementally-bolted-on phases — consistent visual language, no screen that leaves
the user guessing whether it's working, and every rough edge found during this phase's own
kickoff planning (undo, back navigation, capture/push feedback, Settings scale) actually fixed
rather than just documented.

---
