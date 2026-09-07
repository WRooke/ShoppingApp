# Phase 5 — hand test plan

Manual verification of the **Phase 5 deliverable**: *"Full end-to-end flow works. User can
complete a planning session and push the result to AnyList (`TestList` in dev)."*

Covers chunks 5.1 (config/credentials), 5.2 (connector), 5.3 (checklist load), 5.4 ("the
usuals"), 5.5 (checklist UI), 5.6 (push + history + diagnostics), and 5.7 (one live AnyList
call against `TestList`). Automated tests already pass (`pytest -q` → 356). This is the
click-through pass for the Phase 5 review.

> **Sections 1–7 run entirely offline** — `ANYLIST_FAKE_MODE=true`, no account, no network.
> **Section 8 is the only live AnyList call.** It needs `ANYLIST_ENABLED=true`,
> `ANYLIST_TARGET_LIST_NAME=TestList`, real credentials, and a **fresh, explicit
> in-conversation go-ahead** for that specific run (a standing "yes" does not carry — see
> CLAUDE.md > Security §2). **The real household shopping list is never touched.**

---

## Setup (sections 1–7)

- **Seed the disposable fixture DB** (does not touch `data/mealplanner.db`):
  ```
  .venv\Scripts\python -m scripts.seed_phase5_fixtures --reset
  ```
  This creates `data/phase5-test.db` with the schema, the app's reference data (staples incl.
  **olive oil**; product_units incl. the **beef mince** 500 g pack + the eggs/milk/yoghurt
  multi-packs), and three manual recipes:
  - **P5 — Milk & Passata** — `milk` 1 L (matches the fake AnyList list) + `passata` 400 g
  - **P5 — Beef & Oil** — `beef mince` 500 g (seeded pack) + `olive oil` 2 tbsp (a staple)
  - **P5 — Cream Conflict** — `cream` 100 g + `cream` 200 ml in one recipe → a Chunk 4.6
    `needs_review` line at consolidation
  It creates no sessions and no usuals — those are test-plan steps.
- **Start the server against it**, fake modes on:
  ```
  DATABASE_PATH=data/phase5-test.db AI_EXTRACTION_FAKE_MODE=true ANYLIST_FAKE_MODE=true \
    PORT=8099 ALLOWED_ORIGINS=http://127.0.0.1:8099 .venv/Scripts/python -m app.main
  ```
- The fake AnyList list (`TestList`) is auto-seeded with **milk**, **eggs**, **butter** on
  first call.
- Keep `/#/diagnostics` open in a second tab — recent-errors must stay clean throughout
  (the one expected `WARNING` at startup is the keyring/plaintext nudge; that's fine).
- Frontend drive: a phone browser, or `scripts/cdp.py` per `HEADLESS_VERIFY.md`.

---

## 1. Config & credential resolution (5.1)

1. `GET /api/v1/health` → `data.config` shows `anylist_enabled: false`,
   `anylist_fake_mode: true` (for this run), `anylist_target_list_name: "TestList"`,
   `anylist_secret_source` one of `keyring` / `env` / `missing`.
2. Start the server with real creds only in `.env` (no keyring entries) → the log shows one
   `WARNING ... AnyList credentials loaded from .env (plaintext)`.
3. `keyring set shoppingapp anylist_email` / `... anylist_password` with any dummy values,
   restart → the warning is gone and `anylist_secret_source` is `keyring`. Remove them again
   (`keyring del shoppingapp anylist_email` / `... anylist_password`) to restore.
4. Set `ANYLIST_ENABLED=ture` (typo), restart → still `false` (fails safe).

## 2. AnyList connector — fake mode (5.2)

1. `GET /api/v1/checklist/<sid>` on a consolidated session that contains **milk** → the
   milk line comes back `already_on_anylist: true`, `anylist_item_id: "seed-milk"`.
2. With `ANYLIST_FAKE_MODE=false` and `ANYLIST_ENABLED=false`, hit any checklist load →
   `data.anylist_ok: false`, `data.anylist_detail` mentions the disabled gate; the checklist
   items still load (no pre-tick). Put fake mode back on afterwards.

## 3. Checklist load + edits (5.3)

1. Build a session, add the milk/passata recipe, run **Review → consolidate**, then open
   **Next: checklist →**.
2. `milk` is pre-ticked (**have it**, styled as "on AnyList", shows "✓"); `passata` is
   unticked (`?`).
3. Tap `passata` once → **have it**; again → **need it** (and `add_to_list` becomes true —
   check via `GET /api/v1/checklist/<sid>`); again → back to `?`.
4. Set `milk` to **need it** by hand, reload the page → `milk` stays **need it** (a user
   choice is never overwritten by the pre-tick) but is still flagged `already_on_anylist`.
5. `PATCH /api/v1/checklist/<sid>/items/<id>` with `{"have_it":"maybe"}` → `422`.
6. Load a checklist for a session that was never consolidated → `409`
   `CHECKLIST_NOT_CONSOLIDATED`.

## 4. "The usuals" (5.4)

1. **Settings → The usuals** → add "laundry powder", cadence **14** days. Row shows
   **due now** (never added).
2. Edit its cadence to 30, Save → persists. Add a second usual "dish soap" cadence 7.
3. Duplicate name (add "Laundry Powder" again) → inline error, `409`
   `DUPLICATE_USUAL_ITEM_NAME`. Cadence `0` → rejected (`422`).
4. `GET /api/v1/settings/usuals` → both items, `is_due: true`.

## 5. Checklist UI walkthrough (5.5)

Build one session covering every group, consolidate, open the checklist:

1. **Status line** reads "Checked against AnyList — items already on the list are
   pre-ticked."
2. **Needs review** group at the top: the `cream` line shows `100 g + 200 ml`. Click
   **use 100 g** → the line is resolved (drops out of the review group, becomes a normal
   `cream — 100 g` line). Redo on a fresh session with the **manual** entry (`250` / `ml` →
   use this) instead.
3. **Ingredients** group: the binary tap cycle works; `beef mince` shows its pack breakdown
   (`… need ~X`).
4. **Staples used this session** group: `olive oil` appears with an "add to list" checkbox
   (unchecked). Tick it → `GET …/checklist/<sid>` shows `add_to_list: true` for that line.
   A staple **not** used by any recipe this session does not appear.
5. **The usuals — due now** group: the due usuals appear with checkboxes; ticking is
   client-held (no request yet).
6. No browser console errors anywhere.

## 6. Push to AnyList — fake (5.6)

1. On the checklist: mark `passata` **need it**, leave `milk` as pre-ticked **have it**,
   tick one usual, then **Push to AnyList**.
2. The confirmation names how many were added / updated / usuals. `milk` (have it) is **not**
   pushed; `passata` is added; the ticked usual is added.
3. `GET /api/v1/sessions/<sid>` → `status: "pushed"`, `pushed_at` set.
4. `GET /api/v1/settings/usuals` → the pushed usual now has `last_added_at` set and
   `is_due: false`.
5. Press **Push to AnyList** again → `409` `SESSION_ALREADY_PUSHED`; confirm the "push
   anyway" prompt → it proceeds (`?force=true`).
6. **Diagnostics → AnyList connection**: shows `enabled/fake/list/creds`, a **last success**
   timestamp, and a **last push** line (`session N … (confirmed)`). Click **Check AnyList
   now** → "OK — FAKE MODE …".
7. There is one `shopping_history` row per push (check the DB or a future history page):
   `items_json` lists what was pushed, `anylist_response_json` has the raw summary.

## 7. End-to-end deliverable — fake (all chunks)

One clean run, no shortcuts:

1. New session → add 2–3 recipes, mixed servings, one leftovers day → Review → consolidate.
2. Resolve any needs-review line. Swap one awkward ingredient (Phase 4 flow still works).
3. Open the checklist → walk every item (have / need), tick a staple, tick a due usual,
   resolve nothing outstanding.
4. Push → confirmation is sensible, session goes `pushed`, `shopping_history` written,
   diagnostics AnyList block updates.
5. `/#/diagnostics` recent-errors still empty; every API response is the `{"ok": …}`
   envelope with SCREAMING_SNAKE_CASE error codes.

---

## 8. Live AnyList verification — `TestList` only (5.7) — **needs a fresh go-ahead**

> Do **not** run this section without an explicit, current in-conversation "yes" for this
> specific check. `ANYLIST_ENABLED=true`, `ANYLIST_FAKE_MODE=false`,
> `ANYLIST_TARGET_LIST_NAME=TestList`, real credentials (keyring or `.env`). The real
> household list is out of bounds.

1. **Diagnostics → Check AnyList now** → "OK — Authenticated". `last_success` populates;
   the block goes **green** (or amber if no push yet).
2. Note `TestList`'s current items in the AnyList app (so you can clean up).
3. Build a small session (2–3 cheap items, at least one that is **not** already on
   `TestList` and, ideally, one that **is** — e.g. add "milk" to `TestList` by hand first).
4. Checklist load → the item you pre-added to `TestList` comes back `already_on_anylist`
   and pre-ticked; the others don't.
5. Mark the not-on-list items **need it**, push.
6. Confirmation says added N / updated M, **confirmed: true**. Open the AnyList app →
   the new items are on `TestList` with the expected names + quantities; the pre-existing
   item's quantity was updated in place (no duplicate).
7. `shopping_history` row written; diagnostics AnyList block shows the real
   `last_push … (confirmed)`.
8. **Clean up:** remove the test items from `TestList` in the AnyList app (or via a
   throwaway `anylist_client.add_or_increment_items` isn't a remove — just delete them in
   the app). Confirm `TestList` is back to its pre-test state.
9. Set `ANYLIST_ENABLED=false` again when done.

If §8 passes, tick **Chunk 5.7** in CLAUDE.md.

---

## Result log

| Section | Pass / Fail | Notes |
|---|---|---|
| 1. Config & credentials | | |
| 2. Connector (fake) | | |
| 3. Checklist load + edits | | |
| 4. The usuals | | |
| 5. Checklist UI | | |
| 6. Push (fake) + history + diagnostics | | |
| 7. End-to-end (fake) | | |
| 8. Live AnyList (`TestList`) | | |
