# Decision Dialogues & Historical Record

### Decision Dialogues

When a deferred decision comes due, use the relevant dialogue below to guide the discussion. The Q is
the prompt to raise with the maintainer; the A options are what to ask about; Expected Outcome is what
decision gets documented in this file once made.

#### Australian pack size rounding (Phase 4 kickoff)

**Q:** When a recipe needs 340g of an ingredient and the only seeded pack size is 400g, should we:
- Buy the 400g (overage 60g)
- Or round the requirement UP to 400g before buying, rounding up the quantity too?

**A options:**
1. Always round-trip: scale the consolidated quantity up to the nearest available pack, then resolve purchases. (e.g. need 340g → round to 400g → buy one 400g pack)
2. Calculate exactly: keep the 340g, then resolve to "buy one 400g pack which is 60g overstock". Show the overstock to the user.
3. Defer to Phase 5: ship Phase 4 without this, wire it up when AnyList integration happens and real usage emerges.

**Context:** This is a real-world impact — Australian grocery pack sizes aren't designed around metric halvings. The user will notice if the planner is suggesting weird quantities. Requires either a reference data set of common pack sizes or an algorithm to prefer whole packs and understock avoidance.

**Expected outcome:** Decision + implementation approach documented in [Scaling Logic](./scaling-and-consolidation.md#scaling-logic).

**Resolved 2026-09-06 (Phase 4 kickoff) — option 2 (calculate exactly, show overage).**
Keeps `scaling.py` pure and free of pack-size reference data; the multi-pack resolution
algorithm in [Scaling Logic > Purchase unit resolution](./scaling-and-consolidation.md#scaling-logic) already does the
whole-pack cover job. Option 1 would double-round and distort consolidation inputs; option 3
was unnecessary since the algorithm shape was already settled. Folded into
[Scaling Logic](./scaling-and-consolidation.md#scaling-logic) and Phase 4 Chunks 4.3 / 4.6.

---

#### Scaling: rounding location & rules (Phase 4 kickoff)

**Resolved 2026-09-06 in a detailed grilling with the maintainer. Folded into
[Scaling Logic](./scaling-and-consolidation.md#scaling-logic); this is the record of intent.**

**Q:** CLAUDE.md originally had `scaling.py` scale *and* round (nearest 25 / nearest 5 /
nearest 0.5). Is that what's wanted, and where should rounding actually happen?

**Context gathered:** scaling is *rare* (household target is 4 servings = 2 adults ×
dinner + next-day lunch, which is also the usual `base_servings`, so factor is normally
1.0). The end artifact is a shopping list. The maintainer's instinct: "remove as much admin
as possible", "I don't want this to be a round-to-x question", "tolerances", and a specific
worry that a bare `passata` line with no quantity would lead to buying the wrong amount.

**Decisions:**
1. **`scaling.py` only multiplies.** No rounding, no unit conversion, no pack logic. All of
   that moves to `consolidation.py` / `purchase_units.py` and runs **once, on the summed
   quantity** — not per-recipe-then-summed (which rounds twice and compounds drift).
2. **Round UP, never to nearest.** Clean steps (ceil to 25 for g/ml ≥ 100, ceil to 5 below,
   ceil to whole for counts) so numbers are tidy but a shopping quantity is *never short*.
   This is the "tolerance" the maintainer was reaching for.
3. **`cup` is not clean-rounded** — 2-decimal trim only (a scaled cup is ~always < 1, where
   "nearest 5" would zero it). Chosen from options {nearest 0.25, nearest 0.5, no rounding}.
4. **Australian volume conversions are defined and volumes DO merge**: `tsp`=5 ml,
   `tbsp`=**20 ml** (AU tablespoon), `cup`=250 ml, `kg`=1000 g, `L`=1000 ml. Only
   weight-vs-volume for one ingredient stays irreconcilable (no density data) → flagged,
   both parts shown, review UI is Phase 5.
5. **Discrete items always round up, including when scaling down** (3 eggs → 2 serves = 2
   eggs, not 1) — safety over waste, the maintainer's explicit call. `½ onion` → `1`.
6. **Free-text units** (`can`, `bunch`, `clove`…) → treated as discrete, ceil-to-whole.
   Acknowledged as "sounds good on paper, might bite" → [Deferred Decisions](./deferred-decisions.md#deferred-decisions)
   revisit-after-use item.
7. **Required quantity is never hidden.** No-pack-size line shows the amount; pack-size line
   shows both the pack breakdown *and* `need ~X`. Overage shown only when > ~half a pack.
8. **Multi-pack resolution seeded from day one** (eggs/milk/yoghurt) and properly tested,
   not dormant — small deliberate departure from the "don't pre-enumerate" note.
9. **Re-consolidation merges**, preserving `have_it` / `add_to_list` per line; never a wipe.
10. **Default target servings = 4**, a `DEFAULT_TARGET_SERVINGS` constant (form pre-fill,
    always overridable). Making it a Settings field is a [Deferred Decision](./deferred-decisions.md#deferred-decisions).

---

#### AnyList credential storage: `keyring` vs `.env` (Phase 5 kickoff)

**Resolved 2026-09-07 — option 3 (hybrid).** `config.py` reads `keyring` (Windows Credential
Manager, service name `shoppingapp`) first, falls back to the `.env` vars with a logged
WARNING when it does. `keyring` pinned in `requirements.txt`. NUC setup takes either
`keyring set` or plain `.env` — documented in `SETUP.md` / `DEPLOY.md`. Built in
[Phase 5 Chunk 5.1](./build-status/phase-5-checklist-anylist.md#phase-5--checklist--anylist-integration). Kept below for the record.

**Q:** Where should we store the AnyList email and password?

**A options:**
1. Windows Credential Manager via the `keyring` Python package (preferred, more secure)
2. `.env` file in the project root, `.gitignore`'d but unencrypted on disk
3. Hybrid: try `keyring` on startup; if it fails, fall back to `.env` with a warning

**Context:** AnyList password is as sensitive as an email password — a leak means someone can read/write the shared household list. See [Security](./security.md#security) §2. The `.env` fallback makes deployment simpler if `keyring` proves awkward with the batch scripts.

**Expected outcome:** Decision + implementation (credential retrieval in `app/config.py`) + any deployment script changes documented in `SETUP.md` or `DEPLOY.md`.

---

#### Git branching strategy: `production` / `develop` branches (Phase 2 review)

**Resolved 2026-09-05 — option 2.** See the [Deferred Decisions](./deferred-decisions.md#deferred-decisions) table
row above for what was implemented and verified, and `DEPLOY.md` for the full workflow. Kept
below for the record of what was asked and why.

**Q:** Should we introduce stable/development branch separation to prevent breaking the running app?

**A options:**
1. Keep single `main` branch. Low complexity, okay because the maintainer runs verified phases before moving to production.
2. Introduce `develop` (active work) and `production` (NUC-deployed stable) branches. Updates to deployment scripts (`deploy.bat`, `update.bat`) and backup/restore to target the correct branch.
3. Introduce `main` (stable) and `develop` (active work) branches, flipping which is primary. Same complexity as option 2, different naming.

**Context:** Currently a single `main` branch works fine because Phase work is chunked and tested before the next phase starts. As complexity grows (or if dev/NUC work happens in parallel), separate branches prevent the running app from being broken by in-progress work. Requires coordination updates across multiple shell scripts.

**Expected outcome:** Decision + any branch/script changes. If adopted, update `DEPLOY.md` with the new workflow and `deploy.bat`/`update.bat` with the correct branch targets.

---

#### "The usuals" — recurring household items (Phase 5 kickoff)

**Resolved 2026-09-07 — option 2, day-based cadence, checklist group (not a separate
screen).** New `usual_items` table (`name` / `notes` / `cadence_days` / `last_added_at` +
audit cols), independent of `staples`. An item is "due" when `last_added_at IS NULL` or
`last_added_at + cadence_days` has passed; due items appear as the final group on the
checklist, managed in Settings. **Cadence is days, not sessions** — ad-hoc single-recipe
sessions make "every N sessions" an unreliable clock. Built in
[Phase 5 Chunks 5.4 / 5.5 / 5.6](./build-status/phase-5-checklist-anylist.md#phase-5--checklist--anylist-integration). Kept below for
the record.

**Q:** How should we handle recurring non-recipe household items (laundry powder, dishwashing liquid, etc.) that are bought on a schedule independent of meal planning?

**A options:**
1. **Separate table + optional session step.** New `usual_items` table (like `staples`, but not ingredient-linked); offered as an optional pre/post-checklist step. User selects which items to add to this session's list.
2. **Separate table + always-offered.** Same table, but offered on every session (or every N sessions on a cadence).
3. **Fold into `staples` logic.** Reuse `staples` with an added `is_recipe_ingredient` flag; surface "the usuals" when requested, separately from recipe-triggered staples.
4. **Manual only.** Skip the feature entirely; user adds these items directly to AnyList when needed. Simpler, lower scope, acceptable if the household prefers it.

**A sub-questions (if not option 4):**
- **Cadence:** Every session, weekly, monthly, user-selectable, or user manual-trigger?
- **UI integration:** Part of the existing checklist flow, or a separate optional screen?

**Context:** Raised 2026-09-05 during user testing — the household does buy recurring items that don't fit recipes. It's a distinct workflow from recipe staples. Currently undesigned.

**Expected outcome:** Decision on which option + cadence/UI integration details. Implementation lands in Phase 5 (or defer further if option 4).

---

#### "Substitution flagging" review step (Before Phase 3 AI extraction)

> **Third turn, 2026-09-06 (AI Provider Migration addendum):** substitution flagging is now
> back to being a **capture-time, per-recipe, confirmation-required** feature — much closer
> to the *original* 2026-09-05 framing than to the Phase 4 "global remembered rules" design.
> See [AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39). The
> two notes below are kept as the record of the earlier two turns.

**Superseded 2026-09-06 — see [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution).** The
resolution below answered the question as originally asked (was there a pre-existing feature
Phase 3 should reuse?) correctly — there wasn't. But a follow-up conversation surfaced that a
related, genuinely-wanted feature had been lost in the process of resolving that narrower
question: not a Phase 3 extraction-review concern, but a Phase 4 planning-time one — letting the
user substitute an obscure/hard-to-find ingredient for shopping purposes without repeated
prompting, and easily reverse it. See [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution) for the
real design and the [Deferred Decisions](./deferred-decisions.md#deferred-decisions) table for the current status. The
2026-09-05 resolution below is kept as-is for the historical record of what was actually asked
and answered at the time.

**Resolved 2026-09-05 — option 2 (doesn't exist; not built).** No prior substitution-suggestion
feature exists anywhere in this document — the Shop Layout addendum's reference was a mistaken
cross-reference, not a pointer to a real feature. Phase 3's Chunk 3.4 review UI is a fresh
ingredient + section review: editable name/qty/unit/preparation (same inline-edit pattern as the
Phase 2 recipe editor) plus `suggested_section` (editable dropdown), `cuisine`, `protein` — no
"can't find beef mince, try chicken mince?" suggestion mechanism, no supporting service. Rationale:
building a suggestion service now would be speculative scope the same way pre-guessing the full
staples list or pack-size rounding would be (see [Staples Starter List](./data-model.md#staples-starter-list),
[Deferred Decisions](./deferred-decisions.md#deferred-decisions)) — there's no evidence yet of which substitutions would
actually be useful, and the user already reviews/edits every extracted ingredient manually, which
is the same reasoning [Ingredient Normalisation](./ingredient-handling.md#ingredient-normalisation) already uses to skip
automatic synonym matching. Not reserved as a dedicated future-phase item; revisit only if a real
gap turns up in use, same standing as any other not-yet-needed feature. Kept below for the record
of what was asked.

**Q:** What is "ingredient substitution flagging," and does it exist as a real feature that Phase 3's extraction prompt should reuse?

**A options:**
1. **It exists.** There's a prior review UI for suggesting/flagging ingredient substitutions (e.g. "can't find beef mince, how about chicken?" or "too expensive, try budget option?"). Phase 3 should reuse that same review step for section suggestions.
2. **It doesn't exist.** The Shop Layout addendum reference was a mistaken cross-reference. Phase 3 should just build a fresh ingredient + section review UI, no substitution flagging.
3. **Future feature.** It's not built yet, but worth designing alongside Phase 3 so both reviews can share a common pattern.

**Context:** The Shop Layout addendum assumes this feature exists as prior context for reusing its review UI, but it's not specified anywhere else in CLAUDE.md. Needs clarification before the Phase 3 extraction prompt is written (see [Recipe Capture](./recipe-capture.md#recipe-capture--ai-extraction)).

**Expected outcome:** Clarification + Phase 3 prompt updated accordingly (or substitution-flagging designed as a separate small feature alongside Phase 3).

---

#### Shared basic-auth on API routes (Optional, any phase)

**Q:** Should we add a simple shared password on `/api/v1/*` endpoints as a cheap barrier against other LAN devices?

**A options:**
1. Yes, add it now (before the app goes into regular use). Single shared password in `.env`, checked on every request.
2. Skip it. CORS scoping + the local-network-only design is sufficient. If a real threat emerges, add it then.
3. Add it only if the household is on a shared WiFi (dorm, apartment) where untrusted devices are common. Skip if it's a trusted home network only.

**Context:** See [Security](./security.md#security) §4. Not required for the current trust level, but cheap insurance if the NUC will be on a shared WiFi. The maintainer's trust level should be the deciding factor.

**Expected outcome:** Decision documented in [Security](./security.md#security) §4, and if adopted, implementation in `app/main.py` + .env template update.

---

#### Home tab content (No later than Phase 6 polish)

**Q:** What should the home screen actually show? (Currently just a Phase 1 stub: "Phase 1 foundation is running...")

**A options:**
1. **Recent sessions.** List of the last 5–10 planning sessions, tappable to resume/view. Quick action buttons for "New session", "New recipe".
2. **Current status snapshot.** Summary of active session (if any) + last pushed list date + quick access to settings/diagnostics.
3. **Quick actions only.** Large tappable buttons: "New session", "Browse recipes", "View diagnostics". Minimal, uncluttered.
4. **Activity feed.** Show recent session events + pushed items + recipe captures. More informative but more complex.

**Context:** Flagged 2026-09-05 during user testing — the home screen was never actually designed, just left as a nav placeholder. By Phase 6 polish, it needs a real purpose.

**Expected outcome:** Decision on layout + content. Update `static/js/home.js` (or rename if the current file gets repurposed) + `static/index.html` navigation accordingly.

---

#### Settings list re-render scroll position (Fix before Phase 6)

**Q:** How should we preserve scroll position when the settings list refreshes after Save/Delete?

**A options:**
1. **In-place DOM updates.** When saving/deleting a row, update or remove just that element (DOM manipulation) instead of rebuilding the whole list. Preserves scroll + faster visual feedback.
2. **Scroll restoration.** Keep the full re-render, but save `window.scrollY` before it, then restore after. Simpler to implement, still preserves user's reading position.
3. **Pagination/virtual scroll.** Split the lists into pages or lazy-load rows. Overkill for the expected list size, but clean long-term.

**Context:** Currently `static/js/settings.js`'s `load()` does `innerHTML = ""` + re-append on every Save/Delete, resetting scroll to top. Noticeable and frustrating once a list has more than ~10 rows. Flagged 2026-09-05, not yet fixed.

**Expected outcome:** Fix implemented + verified with a ~20-row staples/product-units list. Option 1 preferred (UX + performance), but option 2 is fine if easier.

---

#### "Suggest something" — recency/variety logic + UI (Phase TBD — bring forward?)

**Q:** When should we implement the "suggest a recipe" feature, and what algorithm should it use?

**A options:**
1. Phase 4 (with planning sessions). Surface via a button in the session view; suggest the least-recently-made, highest-rated recipe that hasn't been used in this session yet.
2. Phase 5 or later. Not critical for end-to-end flow; defer until core features are solid.
3. Skip for now. The library browse is enough; let the user pick recipes manually.

**Context:** Schema prep is done (Phase 1: `cuisine`/`protein`/`rating`/`times_made`/`last_made_at` on `recipes`). The feature logic isn't designed yet. If brought forward, it's a small service function + one UI button.

**Expected outcome:** Decision on phase + signal algorithm (recency, variety, rating, user preference input, etc.). Implement accordingly when that phase arrives.

**Reviewed 2026-09-06 at Phase 4 kickoff — not brought forward; stays deferred with no
reserved phase** (option 2/3 territory). It is not on the Phase 4 deliverable path and the
signal algorithm is still undesigned. Best revisited once planning sessions and "mark cooked"
(Phase 6) exist to give it real recency/variety data to work from.

---

#### Section vocabulary — final list (Before Phase 6 store-setup UI)

**Q:** Is the starter section vocabulary in `SECTION_VOCABULARY` correct for your actual grocery stores, or does it need adjustments?

**A options:**
1. Use as-is. The list (`produce, dairy, meat & seafood, bakery, frozen, pantry, household, deli, drinks, other`) matches real stores.
2. Adjust the list. Add/remove/rename sections to match your specific stores better before building the Phase 6 UI.

**Context:** The list is provisional (seeded in Phase 1, `app/seed_data.py`). It's a dropdown vocabulary for the Phase 6 store-setup UI, so it should match actual store layouts before that UI is built. Not a big change, but easier to do now than to rework later.

**Expected outcome:** Confirmed/updated `SECTION_VOCABULARY` in `app/seed_data.py` before Phase 6 store-setup UI is built.

---

#### Nutrition read-back into the app (Post-MVP — if raised again)

**Q:** Recipe→MFP export is settled. Should the app additionally hold per-recipe macros so it can show a nutrition summary (e.g. per planning session)?

**A options:**
1. **No — export only.** MFP holds nutrition; the app never mirrors it. Current position (2026-09-06).
2. **Manual write-back.** A per-serving kcal/protein/carbs/fat field on the recipe the user fills in once from MFP's computed figures. MFP stays source of truth; ~4 numbers per recipe. No integration, no new dependency.
3. **Scrape MFP.** Unofficial library reads MFP's computed recipe nutrition. Real automation, but AnyList-class fragility + a stricter ToS; needs a derisking spike.
4. **Independent estimate.** App computes its own macros from USDA FoodData Central / Claude / a manual `ingredient_nutrition` table. Always present, no MFP dependency, but won't match MFP's numbers — two sources of truth. Also carries the hard unit-conversion problem (tsp/tbsp/cup/"each" → grams).

**A sub-questions (if not option 1):**
- Where do macros surface — recipe detail, planning-session summary, or both?
- If option 3 or 4: does this get its own phase, or fold into an existing one?

**Context:** Raised 2026-09-06. The secondary user wants recipes in MFP for macro tracking; MFP has no API in either direction (see [Nutrition & MyFitnessPal Export](./nutrition-mfp-export.md#nutrition--myfitnesspal-export)). Export covers the core ask cheaply. Read-back is a want, not a need, and every real option has a notable downside.

**Expected outcome:** Decision documented in [Nutrition & MyFitnessPal Export](./nutrition-mfp-export.md#nutrition--myfitnesspal-export); if option 2–4, a build plan plus any schema / further Decision Dialogue follow-ups.

---

#### Duplicate recipe prevention — fuzzy threshold & live check (Phase 4 kickoff)

**Q:** The design ([Duplicate Recipe Prevention](./duplicate-recipe-prevention.md#duplicate-recipe-prevention)) is settled —
warn-with-override on save, signals `source_url` / name exact / `source_book`+`source_page` /
conservative fuzzy name. Two build details to lock at kickoff:

**A sub-questions:**
1. **Fuzzy match method + threshold.** `difflib` ratio, token-set Jaccard, or both; and how
   strict. Start strict (few false positives, may miss some), loosen during verification only
   if real near-dupes get through.
2. **Live `GET /recipes/check-duplicate` endpoint?** Warn on name-field blur in the
   capture-review / manual-entry screens, or rely solely on the submit-time 409 +
   "Save anyway". Live check is nicer UX and cheap; the 409 alone is less code.
3. **Ingredient-set overlap signal** — still deferred. Only pull it in if signals 1–4 prove
   insufficient in real use.

**Context:** Raised 2026-09-06. Needs the `recipes.source_book` / `source_page` columns from
Chunk 3.7b, hence Phase 4 not Phase 3. No new dependency — fuzzy matching is stdlib only.

**Expected outcome:** Method/threshold and the live-endpoint call recorded in
[Duplicate Recipe Prevention](./duplicate-recipe-prevention.md#duplicate-recipe-prevention); implementation lands as a Phase 4
chunk.

---

#### Substitution quantity/unit transform (Phase 3.9 M8 — record of intent)

**Resolved 2026-09-07 in a planning session. Folded into
[AI Provider Migration > Ingredient Substitution Flagging](./ingredient-handling.md#ingredient-substitution-flagging--the-merged-spec),
[Data Model](./data-model.md#recipe_ingredients), [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution) and
[Scaling Logic](./scaling-and-consolidation.md#consolidation-across-recipes); this is the record of what was asked.**

**Q:** A substitution today swaps only the ingredient *name* — `resolved_ingredient` overrides
`name`, but `quantity`/`unit` carry through. That's wrong for swaps like "2 whole corn cobs" →
"2 cans of corn" or "500 g fresh spinach" → "250 g frozen". Substitutions need an optional
quantity + unit transform. How should it be stored, should the AI suggest the numbers, and
when does it get built?

**Decisions:**
1. **Storage shape** — recipe-level stores the *absolute* (`recipe_ingredients.resolved_quantity`
   / `resolved_unit`); the library (`remembered_substitutions`) stores an *equivalence pair*
   (`original_qty`/`original_unit`/`substitute_qty`/`substitute_unit`) that the quick-pick uses
   to pre-fill the recipe-level absolute for whatever amount that recipe calls for. Mirrors the
   existing `resolved_ingredient` (absolute) vs `substitute_name` (library) split. Rejected:
   equivalence-pair everywhere (assumes linearity, more machinery, and the pair isn't reliably
   linear anyway — "2 cob ≈ 2 can" doesn't guarantee "3 cob ≈ 3 can"); single-ratio everywhere
   (least readable, awkward for non-1:1).
2. **The AI does not suggest the numbers** — `flag_substitutions` stays name + note only.
   Extending its structured output is fresh [§0a](./security.md#0a-prompt-injection-hardening-highest-priority)
   number/unit-validation work for guesses the user must check anyway. Parked as a
   [Deferred Decision](./deferred-decisions.md#deferred-decisions), revisit if hand-entry is tedious.
3. **Its own chunk, M8, before the M-review** — it's substitution work (M4's domain), and
   building it first means the combined Phase 3.9 / Phase 4 review signs off the finished
   shape rather than noting a gap.
4. **Only valid alongside a name change.** "Buy this in a different unit without changing the
   item" is a `product_units` concern. Clearing `resolved_ingredient` clears the qty/unit.
   Schema enforces both-or-neither on each pair.
5. **Resolved in `consolidate_session()` / `_scaled_lines()`, never in pure `consolidate()`** —
   the pure function keeps receiving finished lines. Transform skipped for `NO_SCALE_UNITS`
   ("to taste"); session-override ratio applied only where `original_unit` matches the line's
   unit. No cross-unit conversion table — the entered number is the equivalence.
6. **Known limitation accepted** — no pack breakdown when a line is resolved to a new
   free-text unit ("6 can") without a matching-unit `product_units` row. Documented, not
   solved; [Deferred Decision](./deferred-decisions.md#deferred-decisions).

---

#### Ingredient-specific unit vocabulary (raised 2026-09-10 hand-testing — not yet scoped)

**Resolved 2026-09-12 — none of the three options below, after a further round of
questioning surfaced the actual shape of the problem.** Option 2 (a per-ingredient
vocabulary override) was the maintainer's own floated direction here, but a follow-up
grilling ("I feel this will require some significant planning... ask me as many questions as
possible") surfaced that even option 2 was the wrong frame: one ingredient genuinely has
*several* legitimate units (garlic in cloves, heads, spoons, or grams — not one "correct"
unit to restrict it to), the actual bug causing real friction was unit-*spelling* variance
("clove"/"cloves", "g"/"grams") being treated as genuinely different units, and a distinct
third problem (some ingredients — fresh herbs — shouldn't have precise quantities summed at
all) had gotten folded into the same question. See
[Ingredient Unit Handling](./ingredient-handling.md#ingredient-unit-handling) for the resulting four-layer design
(unit-spelling canonicalisation / per-ingredient known-units derived live / a warn-never-
block duplicate nudge / "coarse ingredients"), none of which is a per-ingredient allowed-unit
table. Kept below for the record of what was actually asked.

**Q:** Free-text units are causing real friction (2026-09-10 hand-testing): recipe photos/URLs
sometimes return non-metric or oddball units the app has no opinion on, and a flat
"pick from {g, kg, ml, L, tsp, tbsp, cup}" list (the original framing of this question) doesn't
fit every ingredient — garlic is naturally a clove or a head, not a weight; eggs are a count;
spices are usually g or a spoon measure; milk is ml/L. How should the app constrain/guide which
units get used, without turning into per-ingredient admin the maintainer explicitly doesn't
want ("I don't want to start having to add individual ingredients to this system, that's adding
admin where it's supposed to be removed")?

**A options:**
1. **Flat global list, no per-ingredient anything.** Every quantity picked from one fixed
   metric vocabulary (g, kg, ml, L, tsp, tbsp, cup, "each"/count). Simplest, but doesn't fit
   garlic-as-clove or similarly discrete, non-weight ingredients — the exact gap hand-testing
   found.
2. **Generic default + opportunistic per-ingredient override**, mirroring how `product_units`
   already works (seeded lightly, grown only when a real gap shows up — CLAUDE.md >
   Pre-seeded Product Units). Everything gets the flat list from option 1 for free, with zero
   setup; a specific ingredient (garlic, eggs, ...) gets a small override — a short list of
   "natural" units/labels for that ingredient — added via Settings only reactively, the same
   way a second `product_units` pack size is added today. Needs: a new small table (e.g.
   `ingredient_units`: `ingredient_name`, a short list of allowed unit labels, optionally
   discrete-vs-continuous), a fallback to the option-1 default when no row exists, and
   `EXTRACTION_SYSTEM_PROMPT` / the manual-entry and edit UIs consulting it. This is the
   maintainer's floated direction (2026-09-10) — "I feel like this will need to be built over
   time."
3. **Full ingredient master-data table now** (garlic, milk, every common ingredient
   pre-populated with its natural units and pack forms in one pass). Explicitly **rejected** by
   the maintainer on the spot — this is exactly the up-front admin burden the app is designed
   to avoid, and duplicates effort the existing staples/product_units seeding already treats as
   an anti-pattern ("don't pre-guess, wait for a real gap to show up in use").

**Context:** Distinct from the already-resolved [Purchase unit resolution](./scaling-and-consolidation.md#scaling-logic)
(pack sizes for *buying*, e.g. eggs come in a dozen) — this is about which units are sensible
when *recording a recipe's quantity* in the first place, upstream of both scaling and purchase
resolution. Also distinct from [Ingredient Normalisation](./ingredient-handling.md#ingredient-normalisation) (same
ingredient, different name) and [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution) (different
ingredient, interchangeable for shopping) — this is neither; it's about the *unit*, not the
*name*, of a correctly-identified ingredient.

**Expected outcome:** A decision on option 2's shape (or a different one) at a proper kickoff —
this needs its own scoping pass (schema, prompt changes, which existing screens consult it),
not a snap decision buried in a bug-triage session. Do not build speculatively before then.

---

### History (superseded designs, kept for the record)

- **2026-09-05** — "substitution flagging" asked about; resolved "doesn't exist, not built"
  (correct for that narrow question). See the Decision Dialogue.
- **2026-09-06 (a)** — reopened as a **Phase 4** feature: a global `ingredient_substitutions`
  table of name-scoped rules, one `is_default` per name **auto-applying silently at
  consolidation**, cross-session memory, a Settings management screen, created reactively
  from a planning-session "Remember this?" prompt. **Built** in Chunks 4.1 / 4.5 / 4.6 / 4.7.
- **2026-09-06 (b)** — the AI Provider Migration addendum's capture-time flagging idea +
  the Phase 4 approach were **merged** (this section). M4 keeps the library table (as
  `remembered_substitutions`, minus `is_default`), the multi-substitute quick-picks, Settings
  management, and the planning-swap plumbing; removes silent auto-apply and the
  `consolidate()` resolution step; adds the capture-time AI call and the
  `recipe_ingredients` columns.

> The detailed 2026-09-06 (a) design text (scope decisions, "where this lives", the open
> item about bulk rename) previously filled this section. It has been removed as defunct;
> `git log` on this file has it if ever needed. The Phase 4 chunk-list entries for 4.5–4.7
> still describe what was built and what M4 changes.

### Diagnostics — replacing "Claude API spend tracking"

- **Daily quota usage indicator** — observed request count today per model (best-effort;
  exact caps aren't reliably documented).
- **Recent capture attempt log** — success/fail per capture task, which model handled it
  (Flash / Flash-Lite / queued), and any error detail.

Cost-in-dollars tracking goes away (Gemini free tier). `calculate_cost_usd_cents`, the
`cost_usd_cents` column, the `api_usage` / `api_usage_resets` tables and the "reset spend
tracker" button are all **removed** (decision #3 below — replace, don't repurpose; there is
essentially no real data — Chunk 3.6 never made a live call). Replacement: a purpose-built
`ai_call_log` table (see [Data Model](./data-model.md#ai_call_log)) recording one row per attempted Gemini
call — task type, model tried (`flash` / `flash-lite`), outcome
(`success` / `quota` / `error` / `queued`), token counts, error detail, timestamp. The
diagnostics quota indicator counts today's `ai_call_log` rows per model; the attempt log
lists the most recent.

### Resolved decisions (2026-09-06)

1. **Sequence & scoping** — its own chunked mini-phase, **Phase 3.9**, chunks M0–M8 (below;
   M8 added 2026-09-07 for the substitution quantity/unit transform).
   The **Phase 4 review** is deferred until Phase 3.9's own review (M-review), which
   re-checks Phase 4 + 3.9 together — running it earlier would sign off substitution code
   that M4 removes. Phase 3.9 builds on top of the completed Phase 4 chunks 4.1–4.4/4.6.
2. **The "prior addendum" isn't in this file** — treat the merged spec above as complete.
   With merge decision #2, it's **two** new columns on `recipe_ingredients`
   (`resolved_ingredient`, `substitution_note`); `name` is the original.
3. **`api_usage` — replace, don't repurpose.** Drop `api_usage` + `api_usage_resets` +
   `cost_usd_cents` + `calculate_cost_usd_cents()` + the reset-spend button; add `ai_call_log`
   (see [Data Model](./data-model.md#ai_call_log)). No real data is lost — Chunk 3.6 never made a live call.
4. **Env var names — provider-neutral for the switches, provider-specific for the key.**
   `ANTHROPIC_API_KEY` → `GEMINI_API_KEY`; `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`;
   `CLAUDE_API_FAKE_MODE` → `AI_EXTRACTION_FAKE_MODE`. (Neutral so the deferred Ollama option
   wouldn't force another rename.) Touches `config.py`, `.env.example`, tests, and the NUC's
   real `.env` (call out in `DEPLOY.md` / the M-review).
5. **No Gemini key assumed.** Phase 3.9 builds and verifies entirely against fake mode +
   mocks (M1–M6). **M7** is the single live call — `AI_EXTRACTION_ENABLED=true`, real key,
   and an explicit in-conversation go-ahead per §0c (a standing "yes" does not carry).
6. **§0c carries over verbatim.** Enable switch off by default; no agent session flips it;
   ask the maintainer before any real call even once it's on; fake mode bypasses everything.
   Same for §0a prompt-injection hardening (provider-agnostic).
7. **Phase numbering** — this is **Phase 3.9** in this document. The addendum's "Phase 1"
   references are wrong for this repo; capture is Phase 3.

