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

**Established reference example:** [The ingredient panel](./checklist-and-shopping.md#the-ingredient-panel-2026-09-30-chunk-75)
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

### Accessibility
- Tap targets minimum 44px.
- Sufficient colour contrast.
- Do not rely on colour alone to convey state.

### Design direction (Phase 6 polish)
- Functional kitchen-utility aesthetic — not a food blog. Clean, fast, practical.
- Palette: neutral warm whites and greys, one functional accent colour (not terracotta/clay).
- Typography: one sans-serif family, clear hierarchy, no decorative type.
- No animations except functional transitions (e.g. checklist item ticked → slides/fades out).

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

