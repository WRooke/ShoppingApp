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

**Established reference example:** [Inline pack-size entry](./checklist-and-shopping.md#inline-pack-size-entry-2026-09-24)
— tapping a raw quantity with no known pack size on the checklist expands an inline form that
writes straight into the `product_units` table, no Settings trip required.

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

**Built 2026-09-23.** When the NUC is updated (`scripts/update.py` pulls a new commit and
restarts the server), a phone that already has the app open in a browser tab has no way to
know the running server changed — the page itself is unchanged until reloaded. Rather than a
service worker (deliberately not used — see "no PWA install, no service worker needed" above)
or a forced silent reload (jarring mid-use, and could interrupt an in-progress capture or
checklist edit), a small persistent banner: "Update available — tap to refresh", user-initiated
only.

- **Mechanism:** `GET /api/v1/health` gains a `version` field (`app/services/version.py >
  get_version()`, `git describe --tags --always`, computed once at process startup and cached
  — matches exactly what `scripts/update.py` already logs after a NUC update, see [Deployment &
  Operations](./deployment-and-operations.md#deployment--operations)). `static/js/update-banner.js` fetches
  `/api/v1/health` once on load to record the version the page was served with, then polls the
  same endpoint every 5 minutes; a mismatch means the server process has restarted since this
  page loaded.
- **Not the shared `Toast` component.** `Toast` (`static/js/toast.js`) auto-dismisses after 5s
  and is torn down by `router.js` on every hash change (Phase 6 kickoff decision #12) — both
  wrong here: an update notice must persist until the user actually acts, across as many
  navigations as it takes them to notice it. The banner is its own small app-shell component,
  fixed at the top of the viewport, non-blocking (no overlay/modal).
- **User-initiated only** — tapping the banner reloads the page; nothing reloads on its own.

---

