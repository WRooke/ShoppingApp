# UI / UX

## UI / UX

### General principles
- Mobile-first. Primary use is on Android phones in portrait orientation over local WiFi.
- The app is accessed via browser shortcut (not a PWA install), so no service worker needed.
- Rough-but-functional is acceptable for Phase 1–5. Phase 6 is the polish pass.
- Every action should have visible feedback (loading state, success confirmation, error message).
- Navigation: persistent bottom nav bar on mobile with icons for: Home, Recipes, Plan, Settings,
  Diagnostics.

### Design principle: resolve at the point of need, not in Settings

Any data that would otherwise require a trip to the Settings screen to fix or add — ingredient
aliases, purchase units/pack sizes, unit conversions, canonical ingredient mappings, and
anything similar added in future — should be resolvable *live, inline, at the point where the
gap is discovered* (typically the checklist or ingredient-review screen), rather than requiring
navigation away to a settings form.

This generalises a pattern that already runs through the rest of this spec rather than
inventing a new one: [Explicitly Out of Scope](./project-overview.md#explicitly-out-of-scope)
already rules out pantry tracking because it "adds admin overhead the app is designed to
remove," and the "don't pre-guess, wait for a real gap to show up in use" seeding discipline
applied throughout [Ingredient Handling](./ingredient-handling.md#ingredient-handling--normalisation-substitution-aliases--units)
is the same instinct applied to *when data gets added*. This principle is the same instinct
applied to *where* it gets added — the moment a gap becomes visible (an unmerged duplicate, an
item with no known pack size, an unmapped alias) is also the moment the user has the most
context to fix it; sending them to a separate screen for later usually means it doesn't get
fixed at all, and the underlying data problem recurs indefinitely.

**Guardrail — this must not create UI clutter.** The inline-resolution affordance must be
contextual and dormant by default, not a permanent extra control cluttering every row:
- Only surface the fix-it action when the gap actually exists for that item — not as a
  persistent icon/button shown regardless of whether it's needed.
- Prefer tap-to-reveal (tapping the ambiguous value itself opens the inline edit) over
  always-visible secondary buttons.
- The row's default, common-case appearance should look no busier than it does today.

**Established reference example:** [The ingredient panel](./checklist-and-shopping.md#the-ingredient-panel)
— tapping a checklist row expands pack size / substitute / alias / coarse-item / merge editing
inline, each with an explicit "this list only" vs. "Always" choice, no Settings trip required
unless "Always" is deliberately chosen.

**What this means for future feature planning:** before adding a new Settings-screen field or
table, ask whether a point-of-use screen (checklist, review, plan) could capture or correct the
same data instead, feeding the same underlying store. Settings remains useful for bulk
management, initial setup, and reviewing/auditing existing mappings — but should not be the
primary or only way most of this data gets created or corrected day-to-day.

### Tone & copy
- Plain language. No jargon. Sentence case everywhere.
- Actions describe exactly what happens: "Add to list" not "Submit". "Save recipe" not "Confirm".
- Error messages explain what went wrong and what to do: "Couldn't reach AnyList — check your
  connection and try again" not "Error 500".

### Plain language & no ambiguity

*(2026-10-11, Chunk 6.7, user-feedback batch)*

**Rule: every piece of user-facing text must be unambiguous to a non-technical household member
who has never seen the code.** Set after phone testing found an alias form where "what gets
replaced by what" was unclear, followed by a whole-app copy audit that found the same defect
in ~100 places. "Plain language" above is the aim; this section is the testable standard.
Apply it to every new label, button, placeholder, toast, empty state, error and helper line.

1. **Say what happens, and to what scope.** A control's text (or a line beside it) states
   the *effect* and its *reach*: this recipe / this plan / every plan from now on; before or
   after pushing to AnyList; reversible or not. "Save" and "Delete" alone are not enough on a
   card whose effect is global.
2. **State the direction of any "A becomes B" relationship, in words.** Never a bare `=`, `→`,
   `≈`. Forms that define a rename/swap/conversion show a live preview sentence, e.g.
   "“lemon juice” in a recipe will appear as “lemon” on your shopping list."
3. **No jargon.** Do not show: alias, canonical, coarse, session, product unit, extract, queue,
   quota, equivalence, base servings, section (use *aisle*). Use the vocabulary table below.
4. **No bare symbols or colour-only meaning.** `✓`, `▾`, `▴`, `›`, `≈`, `×`, `~` need words or
   a visible legend; icon-only buttons need visible text or at least `aria-label` + `title`.
5. **Destructive actions state their consequence and offer Undo:** "Removed “lemon juice”. It
   will show as itself again. Undo".
6. **Never show a raw `err.message`.** Map known error codes to plain copy; fall back to
   "Something went wrong — try again". The detail is not lost: the server logs it at the point
   of failure and `error-report.js` sends browser-side failures to the log
   ([Failure logging](./diagnostics-and-logging.md#failure-logging)), so the
   maintainer finds it in Status > Recent errors rather than the household reading it.
7. **Never silently drop or ignore input.** A half-filled pair, a row with only a unit, an
   unknown unit that will never match: show an inline message saying what was ignored/why.
8. **The copy must be true.** Read the backend behaviour before writing a label. (The
   checklist "Always for this recipe" label claimed to change a recipe; it only saved a
   suggestion. A false label is worse than a vague one.)
9. **UI-visible copy changes go through the mockup approval step** (an approved mockup is needed before any UI change is built), like any other UI change.

**Vocabulary (one word per concept, everywhere) — approved 2026-10-11:**

| Say | Not | Meaning |
|---|---|---|
| **plan** | session, planning session, shopping session | one planning session: recipes + days + its checklist (statuses: In progress / Sent to AnyList / Archived) |
| **AnyList** | "the list", "your list" | the destination app; "list" alone is never AnyList |
| **meals** | items (for recipes on Plan) | "items" is only ever ingredients, on the Checklist |
| **Same item, different names** (Settings) · **Also called** (checklist chip) · **Combine** (checklist action) | alias, canonical, merge, ingredient group | one name shown as another on shopping lists |
| **Pack sizes** · chip **Pack size** | product units | how an ingredient is sold |
| **Bought by the bunch** · chip **By the bunch** | coarse item/ingredients | amount ignored; count recipes instead |
| **Saved ingredient swaps** · chip **Substitute** | substitutions, quick-pick | "buy this instead" suggestions, never applied automatically |
| **Status** | Diagnostics (user-facing label) | the health page; developer detail is behind "Advanced"/log |
| **Send to AnyList** (results: added / amount changed / put back / already on AnyList) | push (user-facing), un-crossed | the checklist action |
| **Just this plan** / **Always** + a caption saying where "Always" is saved | this list only / Always (edits Settings) | scope of a checklist-panel change |
| **aisle** | section | supermarket aisle |
| **Import a recipe** | capture, fetch & extract | URL/photo import |

### UI label ↔ code name table

What each screen element is actually called on screen (copied from the code, exact text) and what it
is called in the code, the database and the other docs. Use the **on-screen text** when describing a
screen, and the code name when describing code. The vocabulary table above is the *approved* wording;
the rows marked "differs" are where the screen still shows other words.

| On-screen text (exact) | Where it appears | Code / docs name |
|---|---|---|
| Home · Recipes · Plan · Settings · Status | bottom navigation | routes `#/home`, `#/recipes`, `#/plan`, `#/settings`, `#/diagnostics` (the **Status** page is the "diagnostics" page) |
| New plan · Continue | Home screen | a `planning_sessions` row (called a "session" in code and docs) |
| Active · Past | tabs on the Plan screen | sessions with status `active`, and sessions with status `pushed` or `archived` |
| In progress · Sent to AnyList · Archived | a plan's status | session status `active` · `pushed` · `archived` |
| Archive plan | button on a plan | archives the session (status `archived`) |
| I cooked this | button on a recipe | the "mark cooked" counter on a recipe |
| Checklist | page title | the checklist view (`session_checklist_items` rows) |
| Have it · Need it | buttons on each checklist row | `have_it` = `'yes'` (Have it) or `'no'` (Need it); untouched rows are not sent |
| Send to AnyList | checklist button | the "push" (`static/js/checklist-push.js`, `POST /checklist/{id}/push`) |
| Add to AnyList | button on a due usual | sends that one usual to AnyList |
| The usuals | checklist group and Settings card | `usual_items` |
| Edit ingredient ▾, then the buttons Pack size · Substitute · Also called · By the bunch · Combine | panel opened from a checklist row's name | `product_units` row · substitute · `ingredient_aliases` row · `coarse_ingredients` row · merge (`session_ingredient_merges`) |
| Combine rows · Combine (N) · Combine for this plan | checklist multi-select mode | the checklist-time merge |
| Pack sizes · Saved ingredient swaps · The usuals · Same item, different names · Unit spellings · Bought by the bunch | Settings index | `product_units` · `remembered_substitutions` · `usual_items` · `ingredient_aliases` · `unit_synonyms` · `coarse_ingredients` |
| Import from a web page · Import from a photo | buttons on Recipes | start a recipe "capture" |
| Capture from a web page · Capture from a photo · Fetch & extract · Upload & extract · Review extracted recipe | the import screens (differs: the approved word is "Import") | "capture" (`capture.js`, `capture-review.js`) |
| Section · No section · Loading section list… | import review screen (differs: the approved word is "aisle") | a "section" is a supermarket aisle (`SECTION_VOCABULARY`, `store_sections`) |
| Base servings | recipe form and import review (differs: the approved wording avoids "base servings") | `recipes.base_servings` |
| Recent errors · Recent pushes · Capture queue · Advanced | Status page (developer detail) | log tail, push history, `capture_queue`, raw log |

**Copy length (2026-10-11):** Settings forms keep their explanatory sentence(s); every other
screen gets one short line per control (key lines such as "Need it = sent · Have it = skipped ·
untouched = not sent" beat sentences). Fields on a phone are stacked, so copy never says
"left/right" — it names the field ("When a recipe says …", "count it as …").

**Pre-merge copy checklist** (answer each for every new/changed string): What exactly happens
when I tap this? To what — one recipe, this plan, everything? Can I undo it? Which name wins?
Is any word here one my household wouldn't use? Is anything I typed being ignored? Is this
statement actually true of the code? Does any doc or comment I touched use a private label, slang, or a
section symbol instead of plain words ([Plain-language documentation standard](./code-architecture.md#plain-language-documentation-standard))?

### UI state must not silently vanish

*(2026-10-11, Chunk 6.7)*

A whole-app audit found controls, data and typed input disappearing or resetting with no
signal. The root case: the checklist PATCH response left `recipe_breakdown` at its default
`[]` and the client `Object.assign`-ed it over the row, so the "which recipe" list vanished
after any Have it / Need it tap. Rules:

- **A re-render or reload preserves**: expanded rows/panels, typed-but-unsaved input, selected
  chips/filters/tabs, merge selection, scroll position, and in-flight feedback. Hold such
  state in module state keyed by id, not only in the DOM.
- **Never replace richer cached state with a thinner response.** Update a cached object from
  *every* field the server returned for what changed; never copy a few fields and leave an
  Undo payload built from the stale rest.
- **Async completion is guarded.** A response arriving after the user navigated away (or after
  a newer request) must not write to the screen: use a mount token / request-sequence number.
- **A silent side effect is a bug**: nothing applied, remembered or dropped without the user
  seeing it. If something is pre-filled for them, show it expanded and say so.
- **Back/forward must never create records** (`#/plan/new` creates on click, then navigates).
- **Failures leave a visible trace** that survives a re-render (toast or held per-item error),
  **and** a log line: no `catch(function () {})` that swallows a failure (see the "silent masks
  are not allowed" rule in [Failure logging](./diagnostics-and-logging.md#failure-logging)).
  A fallback the server applies on the user's behalf (e.g. a conversion skipped because the
  units differ) logs a WARNING with the ids *and* is reported back to the user in the response.
- **Tests for these rules follow the suite's one-assertion-per-behaviour rule**
  ([Tests](./code-architecture.md#tests--pytest-tests-mirroring-app)): the backend rule in
  `tests/services/`, the response shape in `tests/routers/`, only the DOM/state-survival
  behaviour in `tests/frontend/`. Extend an existing test before adding a sibling.

### New UI must match the current style

*(2026-10-11)*

Every UI tweak is consistent with what is already on screen; nothing gets a one-off look.
Concretely: all text-entry controls (text, number, url, search, select, textarea) share the one
appearance defined in `static/css/components.css` (44px high, `--surface` fill, `--border-strong`
border, `--r-sm` radius) — a new input type or screen gets that rule extended, never a local
override, so a number box can never look different from the text box beside it. Reuse the existing
components (`.mini-field`, `.pair-box`/`.pair-row`, `.inline-card`, `.persist-toggle`,
`.settings-group-card`, `.btn-sm`, toasts) and the colour/spacing tokens; no literal colours.
Check a change in light and dark and at phone width, and compare the screenshot against a
neighbouring screen before calling it done (`scripts/cdp.py` + a screenshot is enough).

### Accessibility
- Tap targets minimum 44px.
- Sufficient colour contrast.
- Do not rely on colour alone to convey state.

### Design direction (Phase 6 polish)
- Functional kitchen-utility aesthetic — not a food blog. Clean, fast, practical.
- Palette: neutral warm whites and greys, one functional accent colour (not terracotta/clay).
- Typography: one sans-serif family, clear hierarchy, no decorative type.
- No animations except functional transitions (e.g. checklist item ticked → slides/fades out).

### No native dialogs — ask and report inline

*(2026-10-06, Chunk 6.7)*

**Rule: the app never uses the browser's own `alert()`, `confirm()` or `prompt()`.** They are clunky,
hide the page, can't say what a button does ("OK"/"Cancel"), and on a phone show the server's raw
address in their title. Questions and errors appear **inline, in plain words, where they happened**,
and buttons are named for what they do. Enforced by `tests/test_no_native_dialogs.py` (fails with file
and line if one is added) and, in the browser tests, a trap on `window.alert/confirm/prompt`.
Approved mockups: [`docs/mockups/chunk-6.7/popups.html`](./mockups/chunk-6.7/popups.html).

**Which tool to use when** (all in `static/js/inline-feedback.js` + `toast.js`):

| Situation | Use | Example |
|---|---|---|
| An error next to the thing you just did | `Feedback.error(slot, msg, {retry})` — one red line, `role="alert"` | "Couldn't save — … Tap again to retry." under a checklist row; "Enter an amount greater than 0." beside "use this" |
| A whole section failed | `Feedback.error(slot, msg, {box: true, retry})` — the boxed `.error-state` | "Couldn't push to AnyList. Nothing was changed." + Try again |
| A question that needs a decision | `Feedback.card(host, {title, body, confirmLabel, cancelLabel, tone, onConfirm})` — an inline card right under what triggered it; focus on the first button, **Escape = the cancel action** | "Already pushed to AnyList" → **Push again** / **Not now**; "No shopping session yet" → **Start one with this recipe** / **Not now** |
| The thing you tapped is already gone (an Undo that failed) | `Toast.show(msg, {tone: "error", actionLabel: "Retry", onAction})` — danger toast, wraps, `role="alert"`, stays 9 s | "Couldn't restore “olive oil” — …" after deleting a Settings row |
| An action that is easy to reverse | do it, then a toast with **Undo** (never ask first) | "Merged into “parmesan” — this list only  Undo" |

Rules: errors say what went wrong and what to do, with no apology; one error per slot (a new one
replaces the old); nothing blocks the page; tap targets stay ≥44 px; a card never needs a "close" because
it always has a named cancel. The library row (`<a>`) and detail header wrap so a card/error can take its
own line. Where an error needs to survive a screen change (a delete that is about to navigate away) the
failure is shown *in* the screen and the deferred navigation is kept running so the user is never stranded.

**What was replaced** (3 `confirm()`, 22 `alert()`): merge "Always treat these as the same ingredient?" →
the merge panel below; "already pushed, push again?" → inline card; "start a new session?" → inline card;
push failure → error box / failed-item list; save/skip/resolve/rename/archive/add/move/update failures →
`Feedback.error` on the row/button/section; every "Couldn't undo" → error toast with Retry.

**The merge panel** (`checklist.js > mergePanel`): shows what will happen — **parmesans + parmesan → parmesan**
(the radio chooses the surviving name) — and the choice *is* the two buttons: **Merge for this shopping list only**
or **Merge every time — all future recipes**, with a plain sentence under them ("any future recipe that says
“parmesans” will list it as “parmesan”. You can undo this any time in Settings → Ingredient groups."), plus an
optional collapsed amount-equivalence field and a Cancel. Afterwards a toast offers **Undo**:
`POST /checklist/{id}/undo-merge` removes the session merge rows and/or the saved groups the merge created and
hands the merged line's Need it / Have it back to the restored lines.

**Reviewing and reversing a learned merge:** Settings → Ingredient groups lists every group with Delete + Undo.
A group made by "merge every time" is tagged **from a checklist merge** (`ingredient_aliases.source = "merge"`),
migration-seeded groups are tagged **built-in** (`"system"`), hand-made ones have no tag. A "this list only"
merge lives only as long as that shopping list (and has Undo right after).

---

### Client auto-update notification

**Built 2026-09-23, rewritten 2026-10-06 (Chunk 6.7).** When the NUC is updated (`update.bat` pulls
a new commit and restarts the server), a phone that already has the app open can't know. A small
persistent banner — "Update available — tap to refresh" — tells it; the user decides when to reload
(never a forced reload: that could interrupt a capture or a checklist edit), and the reload really
does fetch the new code. No service worker (deliberately — see "no PWA install" above).

**How it works, why the first version never fired, the failure modes and every test:** see
[Deployment & Operations > How an open phone learns the NUC was updated](./deployment-and-operations.md#how-an-open-phone-learns-the-nuc-was-updated).
Short version: the page's baseline is the build id the server stamped into the page it served
(`<meta name="app-build">`), compared with `GET /api/v1/health`'s `build_id` (a hash of the code);
checks run when they can be noticed (load, tab visible, `pageshow`, back online, focus, navigation,
every 90 s while visible) with retries across the restart gap; the tap navigates to `/?b=<build>` so
every asset is fetched fresh.

**Look and behaviour** (`static/js/update-banner.js`, `.update-banner` in `components.css`; mockups
in `docs/mockups/chunk-6.7/banner.html`):
- Not the shared `Toast` (auto-dismisses after 5 s, torn down on every route change). Its own
  app-shell component, fixed at the top, never a modal/overlay.
- The page and its sticky header sit **below** the banner (it used to cover the header title);
  it clears a phone's status bar (`env(safe-area-inset-top)`), is ≥44 px tall, a `role="button"`
  reachable by keyboard.
- Two states: **"Update available — Tap to refresh"** and, if a tap didn't bring the new build,
  **"Update didn't load — Tap to try again"** (so it can never silently loop).
- "Update pending" survives a reload (`sessionStorage`); nothing reloads on its own.
- `window.UpdateBanner.getState()` / `.getLoadedVersion()` / `.checkNow()` exist for tests and for
  debugging from a phone console.

---

