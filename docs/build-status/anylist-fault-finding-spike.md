# AnyList fault-finding spike (2026-09-18)

Triggered by two household-reported symptoms when pushing the checklist to AnyList: notes
rarely land, and a quantity AnyList clearly *has* (the item-detail "+" jumps from the true
value, not from 0) shows as "Not set" in AnyList's own list view (see the Zucchini screenshots
from the 2026-09-18 report). This spike set out to explain those two specifically, then — per
the maintainer's request — was widened to exercise every use case of the AnyList integration,
not just the two already reported, on the theory that other issues could be hiding behind the
same class of gap: things the app's own tests/diagnostics can't see because they only check what
*our* code thinks happened, not what AnyList's server (or AnyList's own app UI) actually does
with it.

**Authorization.** `.env` pins `ANYLIST_TARGET_LIST_NAME=TestList` with `ANYLIST_ENABLED=true` /
`ANYLIST_FAKE_MODE=false`. The maintainer authorized autonomous live testing against AnyList for
the remainder of the 2026-09-18 session on that basis, scoped strictly to TestList — the real
household list was never targeted, read, or written. That authorization does not carry into a
future session (standing rule, unchanged).

**Tooling.** `spike/anylist_fault_finding_probe.py` (committed, throwaway — matches the Phase
1.5 `spike/anylist_spike.py` precedent) drives the *real* production code
(`app.services.anylist_client` / `anylist_wire`), not a reimplementation, so every finding below
reflects the actual app behaviour. It reaches past the connector's public functions into raw
wire inspection on purpose — decoding protobuf field 21 (`quantityPb`) and field 18
(`deprecatedQuantity`) directly — because the connector's own `get_items()` always merges them,
which is exactly the mechanism under investigation. Every probe item was named with an `FF-`
prefix; probe 10 removed them all again via the wire-level `remove-shopping-list-item` handler
(present in the original derisking spike, never carried into the production connector — see
"Other findings" below). Two illustrative items were left behind afterward for a manual phone
check — see "The phone check — what actually happened" at the end; that check disproved this
spike's original leading theory for symptom #1, so read the "Correction" section right after the
headline table before trusting anything probe 3 concludes about field 21.

## Headline: two confirmed mechanisms, one still open, one new

| # | Symptom | Status | Mechanism |
|---|---|---|---|
| 1 | Quantity shows "Not set" in AnyList's list view, "+" jumps from the true value | **Leading theory FALSIFIED by the phone check — see the correction below. Still unexplained.** | The field-21/18 theory below turned out wrong: a field-18-only item displays its quantity *correctly* on the real AnyList app. The true cause is still open — the best remaining candidate is the update-write failure in probe 3 (a fraction of updates leave the item with **no** quantity in either field), not yet reproduced on demand for a phone check. |
| 2 | Notes rarely come through | **Confirmed, live AND visually on the phone** | A note only ever reaches AnyList on an item's first-ever add; every subsequent push to an item already on the list sends *no* note update at all (accepted, documented limitation — `anylist_client.py:294-308`). Since most household items are recurring staples already on the list every week, most pushes hit this path. |
| 3 | **New** — re-pushing a session duplicates any ingredient that was brand-new on the *first* push | **Confirmed, live and in the code** | `push_to_anylist()` never writes back `already_on_anylist`/`anylist_item_id` onto the checklist row after a successful ADD. A second push before the next `load_checklist()` call (exactly what the UI's "already pushed, push again?" retry does — see `static/js/checklist.js:273-305`) re-adds that same ingredient as a brand-new item instead of updating the one just created. Not a rare edge case: reproduces on every retry, for every ingredient that wasn't already on the list at the time of the first push. |

### Correction (2026-09-18, after the phone check)

The original write-up below (probe 3, and the original "What's left for you to check" section)
proposed that AnyList's list-view quantity chip specifically needs protobuf field 21
(`quantityPb`), and that losing it on every update explains "Not set". **The maintainer's phone
check disproves this**: `FF-CHECK-quantity` (updated to quantity 5, server-confirmed field 21
absent / field 18 = `"5"`) displayed **`(5)`** correctly in the AnyList app's list view — not
"Not set". `FF-CHECK-note` likewise showed its correct quantity (`(3)`) alongside the untouched
"Original note A", confirming mechanism #2 but not #1's theory.

So field 18 *is* readable by AnyList's own UI just fine — the field-21/18 split is not, by
itself, what produces "Not set". What's left standing as the best explanation is the *other*
thing probe 3 found: on a minority of update calls (2 of 3 in that probe's original run), the
item comes back with **no quantity in either field at all** — a genuine write failure, not a
stale-field issue. A `(blank)` item would plausibly render as "Not set", and a phone's locally
cached last-known value (from before the failed write) could plausibly explain the "+" landing
on `true_value + 1` rather than `0 + 1`. This fits the existing
[deferred-decisions](../deferred-decisions.md#deferred-decisions) row on
`set-list-item-quantity` reliability better than the field-21 theory ever did.

**Not yet confirmed live**, though: a follow-up run of ~35 further quantity-update calls today
(tight back-to-back and spaced out) reproduced this "both fields empty" failure **zero** more
times — it's real (directly observed once, with raw wire evidence, in probe 3) but rare and not
reliably triggerable on demand. The three `FF-CHECK-*` items were cleaned up from TestList after
the phone check confirmed/disproved what they could; there is currently no live repro sitting on
TestList for a further phone check. **Next step, whenever it's convenient:** the next time a
real household push comes back `confirmed: false` (the frontend alerts "NOT fully confirmed" —
`static/js/checklist.js:281`), that is the moment to check that specific item in the AnyList app
before pushing again — if it shows "Not set" at that point, mechanism #1 is confirmed as the
write-failure theory rather than the field-21 theory.

## Probe-by-probe findings

**Probe 1 — connectivity.** `check_auth()` succeeded. One `/data/user-data/get` call during this
probe (and one later, in probe 9) timed out after 15s with no response — AnyList's server was
simply slow that moment; the retry immediately after succeeded. Not something the app's fixed
15s `httpx` timeout (`anylist_client.py:_TIMEOUT`) can distinguish from a real outage — worth
knowing this happens even outside any of the bugs below, since a transient timeout mid-push
looks identical to a real failure to whoever's watching the checklist screen.

**Probe 2 — fresh add, 9-item field/value matrix.** Every case landed exactly as sent, confirmed
by our own diff: integer quantity, quantity+unit, decimal quantity (`"1.5 kg"` — the field
carries a plain string, so a decimal is no different from an integer to AnyList's storage; probe
2's own `FF-decimal-qty` item held `f21_value='1.5 kg'` verbatim), quantity+note together, note
only, bare name (mirrors a "usual" — no field 21 written at all when quantity is `None`, which
is correct and matches what "Stain Remover"/"Washing Up Liquid" look like on the real list),
Unicode name+note, a 520-character note, and a punctuation-heavy name. A follow-up standalone
check (not printed to the console, to avoid a Windows-codepage display artifact — the log output
for the Unicode case showed mojibake, e.g. `Cr�me Fra�che`, purely because this session's
terminal isn't UTF-8; the actual bytes were compared programmatically) confirmed the Unicode
note round-trips **byte-for-byte correct** — 39 bytes sent, 39 bytes back, exact string match.
**Not a bug** — logging artifact only, noted here so it isn't mistaken for data corruption.

**Probe 3 — update, same items pushed a second time.** Every updated item lost field 21 entirely
— true, but **see the correction above: this alone does not explain "Not set"**, since a
field-18-only item was confirmed to display correctly on the real AnyList app. Notes were never
touched on update (mechanism #2), confirmed again explicitly through the connector (not just the
checklist-level test added in Part A) and later visually on the phone.
**Also surfaced update flakiness, which turned out to be the more important finding of this
probe**: 2 of the 3 updates in this probe failed to persist *any*
quantity value at all (field 21 and 18 both empty afterward, `confirmed=False`,
`"quantity is None, expected '1200 g'"`), while the third succeeded normally. A dedicated
follow-up (5 consecutive quantity updates on one fresh item, back-to-back) then landed 5-for-5.
This is consistent with — and re-confirms, on live data, the same day — the deferred-decisions
row **"`set-list-item-quantity` reliability on an already-listed item"**: "worked once, early in
the testing session, then failed... consistent with something cumulative across a long
live-testing session... not a fixed code defect." Today's pattern (fail, fail, then succeed, then
5/5 clean on retry) doesn't cleanly fit "works once then always fails" either — it looks more
like intermittent flakiness with no fully understood trigger yet, not a deterministic bug in
this app's request construction (the wire bytes sent were correct in every case). Recommend
leaving this exactly where the deferred-decisions table already has it: known, unconfirmed
mechanism, watch for recurrence.

**Probe 4 — checked-state interference.** Inconclusive by design (this app's connector has no
checked-state write path at all to test properly — see "What's left for you to check").
A guessed `set-list-item-checked` op returned HTTP 200 but produced no visible change
(`before_checked=False, after_checked=False`), so it's unconfirmed whether the handler name
guess was wrong or the op is simply a no-op for another reason. What *is* now confirmed: a
normal quantity update through the real connector does **not** disturb the checked field either
way (`checked_after_update=False`, matching the untouched value) — consistent with the
`_build_operation` code-level fact that an update op carries no item message at all (Part A's
`test_update_op_never_carries_a_checked_field`), so there's no mechanism in this app by which a
routine push could silently un-tick something a household member already checked off by hand.

**Probe 5 — confirm/diff robustness (two ops, one item each, one HTTP request).** Both ops
landed. This **does not reproduce** the 2026-09-12 Chunk 5.7 finding ("AnyList's server silently
drops the second op whenever a request's operation list touches more than one distinct
`list_item_id`"). Unofficial, reverse-engineered APIs can change behaviour without notice, and
one non-reproduction six months later isn't strong enough evidence to relax anything — **the
connector's existing one-op-per-request discipline should stay exactly as it is**; this is
recorded as new information, not a recommendation.

**Probe 6 — empty-quantity update.** Pushing `quantity=None` against an item with no prior
quantity (`existing_id` set, `PushItem.quantity=None` → the real connector sends
`updated_value=""`) left the item with field 18 **absent** afterward (not an empty string) —
i.e. AnyList appears to treat an empty `set-list-item-quantity` value as "no-op" rather than
"set to blank." This probe's target never had a quantity to begin with, so it doesn't settle the
scarier version of the question — whether an empty update would *clear* an item that already had
a real value — but probe 3's much higher-impact finding (a plain, non-empty update failing to
persist anything at all, 2 of 3 times) already covers that risk surface and then some.

**Probe 7 — live name-matching / pre-tick.** Both directions confirmed on a real list, not just
the offline `test_names_match` parametrised cases: an ingredient named `ff-tomato` correctly
pre-ticked against `FF-Tomatoes` (plural→singular fuzzy match), and did **not** false-positive
match against a separately-added `FF-Cherry Tomatoes` — `checklist.py`'s whole-string `_norm`
comparison (not a last-word match) held up exactly as designed.

**Probe 8 — full round trip via the real app endpoints.** This is where mechanism #3 (the
duplicate-on-repush bug) surfaced. `load_checklist → update_item → push_to_anylist` (first push)
added a brand-new ingredient and updated one already on the list, both confirmed correctly. A
second `push_to_anylist(force=True)` — the exact call the UI's retry dialog makes, with **no**
`load_checklist()` re-run in between, matching `static/js/checklist.js:273-305` precisely — added
the *same* "new" ingredient a second time (`matches_on_list=2`) instead of updating the item it
had just created, while correctly updating the one that had been on the list from the start.
Traced to `checklist.py`'s `push_to_anylist()`: it never writes the new AnyList-assigned id (or
`already_on_anylist=True`) back onto the checklist row after a successful add, so the next push
— without an intervening reload — has no way to know that ingredient is already there. The UI's
own retry-confirmation dialog text ("anything it can no longer match will be added as a new
line, which could be a duplicate") describes a narrower, rarer case (an item renamed/removed by
hand since the last push) and doesn't mention this one, which is not an edge case at all — it
reproduces on **every** retry, for **every** ingredient that was new at the time of the first
push.

**Probe 9 — usuals push.** A bare-name, no-quantity item landed cleanly, matching the real
screenshot's "Stain Remover" / "Washing Up Liquid" shape.

**Probe 10 — cleanup.** All 14 `FF-`-prefixed items created across probes 2-9 were removed via
`remove-shopping-list-item` (list-item wire, full item message required — same shape the
original Phase 1.5 spike used in `remove_item()`). Confirmed clean afterward
(`still_on_list=[]`). **Other finding, not a bug:** the production `anylist_client.py` has no
delete/remove function at all — every spike (this one included) has to reach past its public API
to clean up after itself. Worth adding a real `remove_item()` to the connector if AnyList spikes
are going to keep happening; not urgent since nothing in the actual app ever needs to remove an
AnyList item today.

## The phone check — what actually happened

Two items were left on **TestList** (not the household list) after the probe run for the one
visual check that genuinely needed a human (I have no way to view the AnyList app myself), plus
a third added afterward while chasing the correction above:

1. **`FF-CHECK-quantity`** (added qty 2, updated to qty 5 — field 21 absent, field 18 = `"5"`)
   — showed **`(5)`** in the AnyList app's list view. **Not** "Not set". Falsified the field-21
   theory (see the correction above).
2. **`FF-CHECK-note`** (added qty 1 + note "Original note A", updated to qty 3 + attempted note
   "Attempted note B") — showed **`(3)`** and **"Original note A"**, confirming mechanism #2
   both server-side and visually: the attempted note update never took.
3. **`FF-CHECK-blank`** — added afterward to try to reproduce probe 3's "both fields end up
   empty" write failure on demand (~35 further quantity-update calls, tight and spaced). Did not
   reproduce; no phone check was useful for it, so it was cleaned up along with the other two.

All three `FF-CHECK-*` items have been removed from TestList — nothing left over from this spike.

The optional checked-state check (tick an item in-app, then push an update and see if it
survives) was not run — probe 4's write-side finding (an update op has no way to touch checked
at all) already covers the only thing this app's own code could break; whether AnyList's *server*
independently resets checked state on any write remains unconfirmed and is low-priority given
that.

## 2026-09-19 reliability investigation — the real mechanism, at realistic scale

Follow-up to the correction above, per the maintainer's request to fully understand and fix all
three mechanisms, "however long it takes." Session-wide live-testing authorization from
2026-09-18 carried into this continuation (same session), still strictly TestList-only.

**Method.** `spike/anylist_reliability_investigation.py` (committed, throwaway) drove the real
app pipeline (recipe → session → consolidate → `load_checklist` → `push_to_anylist`) through 10
simulated "weekly" cycles over a ~28-item synthetic grocery list (20 "core" items present every
cycle, 8 "occasional" items alternating in/out), instrumenting the live connector to log full
HTTP forensics (status, headers, body length, timing) on **every** call, not just non-200s.
A separate controlled experiment (A3) then re-tested the Chunk 5.7 "`set-list-item-details`
permanently corrupts quantity" finding: a details-touched group vs. a quantity-only control
group, same volume each. Total: 939 real HTTP calls in ~12 minutes.

### The failures are neither random nor batch-wide — they're per-item and (so far) permanent

Every cycle from cycle 2 onward, the **exact same 13 of 20 core items** (`Rx-Bread`,
`Rx-Broccoli`, `Rx-Butter`, `Rx-Cheddar Cheese`, `Rx-Chicken Breast`, `Rx-Garlic`, `Rx-Ginger`,
`Rx-Greek Yoghurt`, `Rx-Milk`, `Rx-Olive Oil`, `Rx-Pasta`, `Rx-Soy Sauce`, `Rx-Spinach`) came
back with **no quantity in either protobuf field at all** — while the other 7 core items
(`Rx-Onion`, `Rx-Brown Rice`, `Rx-Carrot`, `Rx-Eggs`, `Rx-Tomato`, `Rx-Capsicum`, `Rx-Lemon`)
updated correctly **every single cycle, 9/9**. Several "occasional" items showed the same
split. This is not the "rare, ~5%" impression the original spike gave from 3 data points — at
realistic volume it's closer to **65% of items, and once an item starts failing it never
recovers on its own**: cycle 1 (every item's first-ever touch, an ADD) was 100% clean; cycle 2
(every core item's FIRST update) is where the split first appears, and it holds identically for
every cycle after that. Fresh adds were 100% reliable throughout the entire run — every
single failure was on `set-list-item-quantity`, never on `add-shopping-list-item`.

**Confirmed with a dedicated follow-up, directly targeting one of the caught items
(`Rx-Milk`):**
- **Retrying the identical op does not help.** 4 separate calls, each with the app's own new
  retry logic (Phase B1 below) attempting up to 2 retries per call — **12 total write attempts,
  12 failures, 0 successes.** This item is not intermittently flaky; `set-list-item-quantity`
  is completely non-functional for it.
- **Delete + re-add under a brand-new id recovers it — but only for one call.** Removing the
  item and re-adding it worked immediately (quantity landed correctly, field 21 present, clean
  state) — consistent with adds being 100% reliable throughout. But the very next
  `set-list-item-quantity` call against that **brand-new identifier** failed immediately too.
  Whatever determines "cursed," it isn't tied to the old identifier alone — it reappeared
  instantly under a new one, for the same item name, in the same account, in the same live
  session.

**What's still genuinely unresolved: is "cursed" permanent (tied to the item's name/account
state), or is the whole account currently sitting in a rate-limited/degraded state from an
unusually dense burst of testing (939 calls in ~12 minutes, then dozens more in the immediate
follow-ups)?** Both explanations fit the data collected so far equally well, and only time (a
low-volume re-test well after this session, ideally the next day) can tell them apart — a
same-session re-test can't, since the account may still be in whatever state it's in right now.
Two observations lean toward *some* form of rate/load sensitivity rather than a purely static
per-item property: read timeouts (previously rare — 2 across the whole 2026-09-18 spike) became
frequent during and after the densest part of this run (16 timeouts total, clustered around
cycle 10 and the A3 experiment's start), and A3's controlled comparison — run immediately after
the worst of the cycle simulation — came back **clean: 0 failures in 90 calls for the
details-touched group AND 0 failures in 90 calls for the control group.** If failures were a
fixed property of specific items regardless of load, A3's control group (quantity-only updates
on brand-new items) should have shown some failures too, roughly matching the ~65% rate seen
moments earlier — it didn't. That's consistent with the account having been in an active
degraded window specifically during the cycle simulation's densest stretch, not a permanent
per-item curse — but it's also consistent with A3's specific items simply not being among
whichever subset is "cursed" (a real possibility given the deterministic-looking item split).
**Not resolved either way yet.**

A3's clean result does mean: **no evidence survives that `set-list-item-details` specifically
corrupts quantity** — the control and detail-touched groups behaved identically. Combined with
how closely this matches the pattern of the 2026-09-10 finding this project already knows was a
misdiagnosis of a different bug, the Chunk 5.7 "details corrupts quantity forever" finding
looks like it was very likely **also** a misdiagnosis of this same general update-reliability
issue, encountered by coincidence right after testing details. Not proven beyond doubt (see the
unresolved question above), but the balance of evidence no longer supports treating it as an
established, permanent AnyList behaviour.

### Fixes implemented 2026-09-19 (see `app/services/anylist_client.py`, `app/services/checklist.py`)

- **B3 — duplicate-on-repush (mechanism #3): fixed.** `PushResult.added_ids` (name → new AnyList
  identifier) is now populated on every add; `checklist.push_to_anylist()` writes it back onto
  the checklist row immediately. Covered by new offline tests
  (`test_force_repush_does_not_duplicate_a_freshly_added_item` and others).
- **B1 — retry-with-reconfirm: implemented, but demonstrably insufficient on its own for the
  dominant failure mode above.** `add_or_increment_items()` now retries a still-wrong item's
  exact op up to twice more before surfacing a discrepancy. This *is* real, tested, and does no
  harm — but per the `Rx-Milk` follow-up, a cursed item fails all 3 attempts (initial + 2
  retries) every time. It will help if any of the observed failures turn out to be genuinely
  transient once the account is retested at a calmer load; it will not, on its own, fix an item
  that's actually in the "cursed" state.
- **B2 — notes on update: not yet changed.** Blocked on the same open question above — sending
  `set-list-item-details` on every update is reasonable **if** the corruption finding really was
  a misdiagnosis, but risky to ship while that's still not fully settled.

### Open decision for the maintainer

The only mechanism confirmed (twice, live) to reliably restore a cursed item's quantity is
**delete + re-add under a new identifier** — which was deliberately avoided for routine pushes
back at Chunk 5.7 because it resets `checked` to false and would silently discard any note a
future fix might set, i.e. it can undo a household member's own manual edits on that AnyList
item. Given how common "cursed" items turned out to be at realistic scale, this tradeoff is worth
revisiting rather than assuming: this needs the maintainer's call, not a unilateral choice —
see the chat for the specific question and options.

## What this spike does not do

Mechanism #2 (notes on update) is unchanged from the accepted, documented limitation — still not
fixed, pending the open question above. Mechanism #1's exact trigger (permanent per-item state
vs. temporary account-wide load sensitivity) is still not fully settled — the next concrete step
is a low-volume live re-test well after this session, once whatever state the account is
currently in has had time to change, rather than more testing right now while that state itself
is the open question.
