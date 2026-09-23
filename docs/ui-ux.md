# UI / UX

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

