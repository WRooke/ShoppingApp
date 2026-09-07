# Phase 4 — hand test plan

Manual verification of the **Phase 4 deliverable**: *"User can create a session, add recipes,
scale them, substitute an ingredient they don't want to buy, and see a consolidated shopping
list with purchase units resolved."*

Covers chunks 4.1 (migrations), 4.2 (duplicate prevention), 4.3 (scaling), 4.4 (session CRUD
+ slots), 4.5 (substitution persistence + Settings), 4.6 (consolidation + purchase units +
summary endpoint), 4.7 (session UI). Automated tests already pass — this is the click-through
pass for the Phase 4 review.

> **Note:** Chunks 4.5 / 4.6 / 4.7 substitution behaviour was reshaped by Phase 3.9 **M4**
> (no silent auto-apply; `remembered_substitutions` is a quick-pick library; session swaps
> are client-held overrides). Section 5 below tests the **M4** behaviour, not the original
> `is_default` design.

---

## Setup

- Dev server running (`start.bat` or `uvicorn`), `AI_EXTRACTION_FAKE_MODE=true`,
  `AI_EXTRACTION_ENABLED=false`.
- Library has a handful of recipes — manual entry is fine; include:
  - one at `base_servings = 4` using **beef mince** (e.g. 300 g) and **olive oil** (a staple).
  - one using **beef mince** again (e.g. 400 g) and **soy sauce** `2 tbsp`.
  - one using **soy sauce** `100 ml`, **cream** `100 g`, and a `pinch` of **saffron**.
  - one using **cream** `200 ml`, **eggs** (`3`), **passata** (`400 g`, no product_unit).
  - one using **bulgarian feta** `400 g` (obscure ingredient for the swap test).
- Seeded reference data intact: beef mince 500 g pack; eggs ½ dozen + dozen; milk 1 L + 2 L;
  yoghurt 500 g + 1 kg; staples salt / black pepper / olive oil / vegetable oil / plain flour.
- Keep `/diagnostics` (recent errors) open in a second tab — it must stay clean throughout.
- Frontend drive: browser on a phone, or `scripts/cdp.py` per `HEADLESS_VERIFY.md`.

---

## 1. Duplicate recipe prevention (4.2)

1. Create a manual recipe **"Pancakes"**. Create a second **"Pancakes"** → a warn panel lists
   the existing match with **Open existing** and **Save anyway**. Click **Save anyway** →
   both recipes now exist (no hard block).
2. Start a new manual recipe, type `Pancakes` in the name field, blur it → an inline
   "you might already have this" hint appears (live `GET /recipes/check-duplicate`).
3. Capture a recipe from a URL and confirm-save it. Capture the **same URL** again → an
   immediate duplicate warning with **no** new `ai_call_log` row on `/diagnostics`
   (short-circuit before extraction). "Capture again anyway" proceeds.
4. Archive a recipe, then create a new one with the **same name** → the match is shown with
   **Restore existing**. Restore → the archived recipe comes back (`archived_at` cleared),
   no new duplicate created.
5. Fuzzy name: create "Spaghetti Bolognese", then try "Spaghetti bolognaise" → flagged as a
   possible duplicate (difflib ratio / token-set). "Chicken Curry" vs "Beef Curry" → **not**
   flagged.

   TESTED - PASS

## 2. Session CRUD + slots (4.4)

1. **Plan** tab → **New session**. Edit its label inline (e.g. "Week of testing") → persists.
2. Add 2 library recipes from the picker (use the search box). Each becomes a slot.
3. Set one slot to **8** servings via the dropdown; give both slots a day-of-week.
4. Reorder the two slots with ↑ / ↓ (`PUT /sessions/{id}/slots/order`).
5. Add a **leftovers** slot for a day → it has no recipe and no servings control.
6. Remove one slot.
7. Reload `#/plan/<id>` → label, slots, servings, days, order all persisted.
8. API spot checks: `GET /api/v1/sessions?limit=1&offset=0` paginates;
   `GET /api/v1/sessions/999999` → `{"ok": false, "error": {"code": "SESSION_NOT_FOUND"}}`;
   a bad slot-order list → `422 SLOT_ORDER_MISMATCH`.

   TESTED - PASS

## 3. Scaling (4.3)

Checked via consolidation output:

1. A `base_servings = 4` recipe in a slot set to **8** → its quantities are doubled on the
   consolidated list.
2. Same recipe in a slot set to **2** → quantities halved, and discrete items round **up**
   (a recipe with `3 eggs` ÷2 = 1.5 → shows **2 eggs**, never 1).
3. A `pinch` / `to taste` ingredient is unaffected by scaling (see §4).

   TESTED - PASS

## 4. Consolidation + unit rules + purchase units (4.6) — core

Build one session that exercises each case, then `POST /sessions/{id}/consolidate` (or the
Review screen) and check the consolidated list:

1. **Cross-recipe sum + packs:** two recipes using beef mince (300 g + 400 g) → **one** line,
   `need ~700 g`, breakdown `2 × 500g pack`, overage note shown (300 g spare > half a pack).
2. **Volume merge (AU tbsp = 20 ml):** `2 tbsp soy sauce` + `100 ml soy sauce` → `140 ml`
   summed, rounded up → `150 ml` on one line.
3. **Irreconcilable mass + volume:** `100 g cream` + `200 ml cream` → line flagged
   **needs review**, both parts shown (`100 g + 200 ml`), no single quantity, no pack.
4. **Multi-pack selection:**
   - a recipe needing ~15 eggs → `1 × dozen + 1 × half dozen · need ~15` (3 spare, not shown).
   - a recipe needing ~750 g yoghurt → `1 × 1kg tub`, **not** `2 × 500g tub`.
5. **To taste:** `pinch` of saffron → shown with **no number** ("saffron — to taste").
6. **No product_unit:** passata → `passata — 400 g` (rounded raw quantity, no pack breakdown,
   still shows an amount).
7. **Staples:** the recipe using **olive oil** → its line is flagged as a staple on the
   checklist. A staple not used by any recipe in the session (e.g. plain flour) → **absent**.
8. **Rounding steps:** a summed g/ml value ≥ 100 rounds up to the nearest 25; < 100 rounds up
   to the nearest 5. Confirm a value like 137 g → 150 g, 82 g → 85 g.
9. **Re-consolidation is a merge, not a wipe:** on one line set `have_it = yes` and tick
   add-to-list. Add another recipe to the session and re-run consolidate → that line **keeps**
   `have_it` / `add_to_list`, its quantity is recomputed, newly-added lines default to
   `unknown`, and any line no longer needed is dropped.

   TESTED - PASS

## 5. Ingredient substitution (4.5 + 4.7, M4 behaviour)

1. **Settings → Saved ingredient swaps:** add `bulgarian feta` → `regular feta` with a note.
   Edit the note. Delete the row → no error, no effect on any recipe.
2. In a **session review** with the bulgarian-feta recipe: use **Swap** on that ingredient →
   type `regular feta` (and try the quick-pick button sourced from the saved swap). Re-run
   consolidate → the line now reads **regular feta** and merges with any other recipe's
   `regular feta` line.
3. The **"Remember this substitution?"** prompt after a swap:
   - **No** → nothing written to Settings; the override is client-held only. Leave the
     session and come back, re-consolidate → the swap is **gone** (session-only, not
     persisted server-side).
   - **Yes** → a `remembered_substitutions` row appears in Settings.
4. **No silent auto-apply:** start a *fresh* session containing the bulgarian-feta recipe and
   consolidate **without** doing a swap → the line stays `bulgarian feta`. The saved swap is
   only ever offered as a quick-pick, never applied on its own.
5. Clearing a swap in the **recipe editor** (`recipe-edit.js`) reverts the ingredient to its
   original `name` — the original is never lost.

   TESTED - PASS

## 6. End-to-end deliverable

One clean run, no shortcuts:

1. New session → add 3 recipes, mixed servings, one leftovers day.
2. Swap one awkward ingredient in review; decline "remember".
3. Consolidated summary shows: resolved purchase units, `need ~X` alongside each pack
   breakdown, staple flags, overage notes where > half a pack, and any needs-review lines.
4. No browser console errors; `/diagnostics` recent-errors still empty; every API response
   is the `{"ok": ...}` envelope with SCREAMING_SNAKE_CASE error codes.

   TESTED - PASS

---

## Result log

| Section | Pass / Fail | Notes |
|---|---|---|
| 1. Duplicate prevention | | |
| 2. Session CRUD + slots | | |
| 3. Scaling | | |
| 4. Consolidation + units | | |
| 5. Substitution (M4) | | |
| 6. End-to-end | | |
