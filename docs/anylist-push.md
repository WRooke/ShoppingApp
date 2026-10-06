# AnyList push — how it works, how to check it, how to fix it

**Written 2026-10-06 (Phase 6 Chunk 6.7).** This is the single place to start when an item did not
arrive on AnyList, when someone asks "what does a push actually do?", or before changing anything in
`services/anylist_client.py` / `services/checklist.py > push_to_anylist()`. The history of how the
write mechanisms were discovered is in
[build-status/anylist-fault-finding-spike.md](./build-status/anylist-fault-finding-spike.md); the
summary lives in [checklist-and-shopping.md > AnyList Push Logic](./checklist-and-shopping.md#anylist-push-logic).

## 1. The contract

> After a push, every row marked **Need it** (and every ticked due usual) is on the AnyList list,
> **not crossed off**, **exactly once**, with the wanted quantity and note — or the push says, **by
> name and with a reason**, that it is not.

`confirmed` is true only when *every* line passed an independent read-back of the list. An HTTP 200
is never evidence (AnyList returns 200 for operations it silently ignores).

## 2. What the 2026-10-06 investigation found (why this was rewritten)

A live shopping run lost ~4 items ("beef mince", "red capsicum" definitely). Reading the code and the
prod logs (the app wrote `added=27 updated=4 confirmed=True`, then 40 minutes later a second push
needed `added=4`) found several independent defects, any of which fits the symptom. All are fixed and
each has a test (section 9):

| # | Defect | Fix |
|---|---|---|
| A | A "Need it" tick lived on a row keyed by name. An alias / merge / substitute / Settings alias renamed the row; consolidation deleted it and created an "unknown" one — the tick vanished, and if the new name matched an AnyList item it was pre-ticked "Have it" and never pushed. | Consolidation carries the decision to the renamed row. |
| B | A crossed-off AnyList item counted as "already on the list" (first name match wins, `checked` ignored). | Crossed-off ≠ on the list; active matches preferred. |
| C | A pushed crossed-off item stayed crossed off (bare-count updates can't touch `checked`; the replace copied the old `checked`) and the verifier agreed. | Crossed-off lines are un-crossed; every line is verified uncrossed. |
| D | The verifier checked ids and non-empty quantity/note only — not `checked`, not names, not that a replace's old item was gone; no delay; failing items weren't named. | Full per-line read-back (section 5). |
| E | A mid-batch failure lost all per-item results and id write-back; `added_ids` and progress were keyed by display name; an unconfirmed push still marked the session pushed. | Per-line results keyed by row; one failure never aborts; only a confirmed push marks the session pushed. |
| F | `_names_match` re-singularised the stored key; `singularise` isn't idempotent for `-ses` words (`cheeses`→`chees`→`chee`) so such an item never matched its own AnyList entry. | One-pass key comparison (the `singularise` bug itself is logged in [deferred-decisions.md](./deferred-decisions.md)). |

Not proven from logs: why `on_list` fell 36→26 between the two pushes (the app never writes outside a
push, so that is AnyList-side or a rename). The new logging (section 6) makes the next occurrence
diagnosable in one look.

## 3. The AnyList operations in use (regression baseline)

Only these are used. Everything else in the AnyList protocol is unused.

| Operation | Used for | Proven behaviour | Pinned by |
|---|---|---|---|
| `add-shopping-list-item` (full item message, field 6) | new line; the add half of a replace; retries | Reliable for every quantity shape, a note, and `checked`; adding an id that exists is a silent no-op (so a retry reusing the same id cannot duplicate) | `test_fresh_add_is_one_add_op`, `test_replace_whose_add_is_dropped_is_healed_by_the_retry_with_the_same_new_id` |
| `set-list-item-quantity` (plain `updatedValue`) | active item, **bare-count** quantity change | Works for a bare number only; unit-bearing values silently fail (except the literal `kg`/`lb`); an empty value is a no-op; never touches `checked` or the note | `test_bare_count_change_uses_set_quantity_only`, `test_update_op_never_carries_a_checked_field` |
| `remove-shopping-list-item` (**must embed the item message**) | the remove half of a replace | Silently ignored if only ids are sent | `test_unit_bearing_change_is_remove_then_add_under_a_new_id`, `test_real_replace_retries_and_recovers` |
| `set-list-item-checked` (`updatedValue` `'y'`/`'n'`, **no** item message) | un-cross a crossed-off item (`'n'`); cross off an old duplicate that will not go away (`'y'`) | **Live-verified on TestList 2026-10-06** (`spike/anylist_checked_toggle_test.py`): 6/6 each way, name/quantity/note untouched, a later `set-list-item-quantity` still works (3/3), an item that *started* crossed off un-crosses (6/6). The 2026-09-18 probe that said "no checked write path" had sent `"1"` — the reference client sends `'y'`/`'n'`. | `test_crossed_off_item_is_uncrossed_in_place_keeping_id_and_note`, `test_uncross_fallback_to_replace_when_in_place_is_disabled` |

Constraints that must not regress (each has a test): the multipart `operations` part has **no
filename** (else a silent no-op); **one operation per POST**; success is decided by a **re-fetch and
diff**; a 401 triggers one re-login and one retry; `rawQuantity` is always written on add; the note
only syncs on add/replace (a bare-count update cannot carry one); retries reuse the same new id;
`_MAX_RETRIES` bounds re-sends; fake mode uses the same decision function as the real client.

`_UNCROSS_IN_PLACE` (`anylist_client.py`) switches un-crossing between the toggle and the older,
also-proven remove + re-add. Flip it to `False` if AnyList ever stops honouring `set-list-item-checked`
— the read-back would catch the failure either way.

## 4. Decision matrix — what a push does to each line

`_decide()` in `anylist_client.py` (shared by the real and fake clients). "Match" = the caller's name
match against a *fresh* read, falling back to an exact-name match if the stored id is stale.

| What is on the list | Wanted | Action | Result |
|---|---|---|---|
| nothing | anything | add | `added` |
| id given but gone from the list | anything | add (exact-name match tried first) | `added` |
| active, same quantity (and same note where one is set) | same | nothing is sent | `already-active` |
| active, bare-count quantity differs | bare count | `set-list-item-quantity` | `updated` |
| active, unit-bearing quantity or note differs | anything else | remove + add (new id) | `updated` |
| active, has a quantity, none wanted | no quantity | remove + add | `updated` |
| crossed off, same quantity | same | `set-list-item-checked` `'n'` | `un-crossed` |
| crossed off, bare-count quantity differs | bare count | `'n'`, then `set-list-item-quantity` | `un-crossed` |
| crossed off, anything else differs | anything else | remove + add | `un-crossed` |
| both an active and a crossed-off item with the name | anything | the **active** one is used | per the rows above |
| any of the above, the write or read-back fails | | re-read, re-send (bounded) | `failed(reason)` if still wrong |

A household member's own note on an item is never overwritten by a push that has no note of its own
(`_note_ok`; a replace carries the old note across). Quantities compare ignoring case and spacing
(`1 L` on the phone equals `1 l` here).

A ticked **usual** that is also being pushed as an ingredient line is *covered by* that line (reported
`already-active`, "covered by the ingredient line") instead of being written twice.

## 5. The read-back (what "confirmed" means)

After the last write, `_verify_against()` checks every line against one fresh read of the list:
present under its id; **not crossed off**; quantity equal; for add/replace the note and name equal;
for a replace the old item gone (or crossed off) — otherwise `"the old item is still on the list too
(duplicate)"`. Lines still wrong are re-read (a lagging read is not re-sent), then re-sent up to
`_MAX_RETRIES` times; a replace whose remove keeps being ignored gets its old item crossed off. If the
list cannot be read back at all, **every** line is reported `could not confirm` and nothing is re-sent
blindly (that could duplicate). The read itself is retried (`_READ_ATTEMPTS`).

Failure behaviour: one failing line never aborts the batch; after `_MAX_CONSECUTIVE_FAILURES` failed
sends in a row the remaining lines are marked "not sent — AnyList kept failing"; if the *initial*
list read fails, nothing is written and the request returns 502.

## 6. Logging — reading a push after the fact

Every push has an 8-character `push_id`. It appears on **every** line below, in the app log
(`logs/app.log`, daily rotation) **and** in `shopping_history.anylist_response_json`, so a push can be
followed end to end. No credentials, tokens or account identifiers are logged.

```
Checklist push 9d3a1c7e: session_id=5 force=False need_it_rows=31 usuals=3
AnyList push 9d3a1c7e: list='TestList' read: 36 item(s) (26 active, 10 crossed off); 34 line(s) to push
AnyList push 9d3a1c7e: plan 'Beef Mince' [item:12] -> uncross (crossed off on the list — un-crossing it in place); on list: id=… qty='500 g' checked=True; wants qty='500 g' note=no
AnyList push 9d3a1c7e: sent uncheck 'Beef Mince' id=… qty='500 g' -> HTTP 200 in 239ms
AnyList push 9d3a1c7e: plan 'Eggs' [item:13] -> noop (already on the list, uncrossed, same quantity); …
AnyList push 9d3a1c7e: read-back round 1/2 — 1 line(s) not as wanted: {'Salt': 'still crossed off on the list'}   (WARNING)
AnyList push 9d3a1c7e: read-back done: 20 added, 3 updated (2 un-crossed), 11 already active, 0 failed
Checklist push 9d3a1c7e: session_id=5 added=20 updated=3 (un-crossed=2) already_active=11 failed=0 usuals=3 confirmed=True timings={'read': 0.6, 'send': 9.1, 'confirm': 1.2}
```
`WARNING`/`ERROR` lines mark anything unexpected: a name matching several active items, a duplicate
after the push, a retry, a send error, an unconfirmed push. `Checklist state carried across rename:`
(INFO) records a "Need it" preserved across a rename.

## 7. Runbook — "an item didn't arrive on AnyList"

1. **Diagnostics page → AnyList panel → latest push** (or `GET /api/v1/diagnostics/pushes`). Find the
   item by name: its **outcome** (`added` / `updated` / `un-crossed` / `already-active` / `failed`) and
   **reason** say what happened. `already-active` means AnyList already had it uncrossed with that
   quantity — look at the list again (it may be further up/down, or under a different name).
2. **Not in the push at all?** The row was not marked Need it at push time. Check the checklist row;
   look for `Checklist state carried across rename:` and the `Checklist push …: need_it_rows=` count in
   the log. A row renamed *after* the push is a new row.
3. **`failed`?** Take the `push_id` and `grep` the log for it: the `plan` line shows what was decided
   and what was on the list; the `sent` line shows each write and its HTTP status; the read-back lines
   show what AnyList actually held afterwards. The session is *not* marked pushed after a failure —
   push again; only the failed lines are retried.
4. **`confirmed` but missing on the phone?** Check the phone is looking at the target list
   (`ANYLIST_TARGET_LIST_NAME`, shown on Diagnostics) and that the item isn't just sorted elsewhere.
   The read-back proved it was on that list uncrossed under the name shown in the result.
5. **A duplicate?** Look for `DUPLICATE` in the log and `matches N ACTIVE AnyList items`. Duplicates
   made by hand on the phone are left alone (the push writes to the first active one).
6. **Nothing in the log at all?** The server never reached `push_to_anylist` — check the browser
   console/network tab; a 502 means the *initial* list read failed (nothing was written).

## 8. Live verification log (TestList only — never the household list)

2026-10-06, `ANYLIST_TARGET_LIST_NAME=TestList`, `spike/anylist_checked_toggle_test.py` and
`spike/anylist_push_live_test.py` (both refuse to run against any other list and remove everything
they add; TestList was empty and restored to empty):

* **Checked-toggle experiment:** `set-list-item-checked` `'y'`/`'n'` (no item message) — 6/6 to
  checked, 6/6 to unchecked, no collateral on name/quantity/note, later `set-list-item-quantity` 3/3,
  un-cross from a crossed-off start 6/6. The embedded-item-message variant was never needed.
* **Five real pushes** through `checklist.push_to_anylist()` with a throwaway database: P1 fresh mixed
  add (6 lines, bare/unit/note-only) → all `added`, invariants OK; P2 quantities changed + a new item →
  `updated`×2 (one set-quantity, one replace), `already-active`×4, `added`×1; P3 three items crossed off
  on the "phone" → not counted as on the list, two `un-crossed` in place, rest `already-active`; P4 an
  item deleted on the "phone" after load (stale id) → re-`added`; P5 nothing changed → seven
  `already-active`, zero writes, no duplicates, nothing crossed off. Every push was followed by an
  independent read of the list and an invariant check; none failed. AnyList took longer than the 15 s
  request timeout to answer a read a handful of times during these runs — that is why list reads are
  retried (`_READ_ATTEMPTS`).

**2026-10-07 — naming follow-up (4 more live pushes on TestList, `spike/anylist_push_live_names_test.py`):**
N1 fresh add of tricky names → exactly "Black Beans", "Salt", "Vegetable Oil", "Cheddar Cheese or Monterey Jack",
"Baker's Chocolate", "2% Milk" landed (no "Or", no "Baker'S", no "400G"); N2 immediate re-push → all six
`already-active`, zero writes, list unchanged (the pushed names match their own rows); N3 old spellings on the list
("Salts", "Vegetable Oils", "Black Bean", seeded with raw ADDs) → matched through the key, all `already-active`,
nothing added or renamed. A first attempt at N3 reported "duplicates" only because the script had seeded the old
spellings on top of N1's items (duplicates of its own making); the push handled it correctly (warned, wrote to the first
match, added nothing) and the script was fixed to start N3 from an empty list. Reads timed out once or twice and were
retried as designed. TestList restored to empty. Total live pushes this chunk: 5 + 4.

## 9. Test map

| File | What it pins |
|---|---|
| `tests/services/anylist_fake_server.py` | The stateful fake AnyList server (adds, bare-number-only quantity updates, remove-needs-embed, `'y'`/`'n'` toggle, silent no-ops; fault injection; "phone" edits) |
| `tests/services/test_anylist_push_faults.py` | The connector against that server: a generated matrix (8 list states × 5 quantities × 2 notes × 3 id modes × 10 faults ≈ 2,400 scenarios) checked against one oracle (never a false OK, never silent, never a duplicate, bystanders untouched, transient faults heal), idempotence, every row of the decision matrix, every failure rule |
| `tests/services/test_checklist_push_scenarios.py` | The whole push (`load_checklist` + `push_to_anylist` + the real connector): one test per defect A–E, usuals, history/diagnostics shape, progress stages, and a **seeded fuzz** (240 random sequences of user edits, aliases, phone edits and faults; fixed seeds so a failure replays) |
| `tests/services/test_checklist_rename_state.py` | Decisions survive alias / merge / substitute / session merge / Settings alias, never downgrade, drop only truly-gone rows |
| `tests/services/test_anylist_client.py` | Wire codec, no-filename part, one-op-per-POST, re-login, the pre-existing spike findings |
| `tests/services/test_anylist_client_edges.py` | Decision/verify functions directly, auth and decode errors, bounded read retries, empty push, the fake client |
| `tests/routers/test_checklist.py`, `test_diagnostics.py` | `{stage, steps}` progress shape, `GET /diagnostics/pushes`, the push response |
| `spike/anylist_checked_toggle_test.py`, `spike/anylist_push_live_test.py` | The live experiments (section 8); re-runnable against TestList only |

Branch coverage of the push path (`anylist_client`, `checklist`, `session_consolidation`,
`progress_tracker`) at the time of writing: 98–99 %. The uncovered lines are defensive guards for
conditions the code above them already rules out (`_find_match` returning no hit for an empty name,
an unreachable fall-through after the 401 retry loop, a stage write for an expired token).
