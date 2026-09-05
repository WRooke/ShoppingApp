# AnyList derisking spike — findings

**Date:** 2026-09-05
**Script:** [`spike/anylist_spike.py`](anylist_spike.py) (throwaway, not wired into the app)
**Result: PASS.** Authenticated against the real AnyList account, fetched all 5 lists, added a
test item to `TestList`, confirmed it landed server-side, removed it again, confirmed it was
gone. Full run log below the recommendation.

## Recommendation: Python-native. No Node.js microservice needed.

The Tech Stack section's "first attempt" (native Python: `httpx` + reverse-engineered protobuf,
using the `codetheweb/anylist` Node package purely as a reference) worked cleanly. Total effort
was about two hours, including reading the reference source and finding/fixing one gotcha (below).
Recommend Phase 5 builds directly on this spike's pattern rather than standing up a Node.js
fallback service — no second runtime, no `127.0.0.1`-only microservice to secure/manage.

## What was built

- No `.proto` file exists publicly for AnyList's API. The reference package ships a protobufjs
  JSON descriptor (`lib/definitions.json`) instead. Rather than pull in `protoc`/grpc tooling,
  the spike hand-rolls a ~150-line protobuf wire-format codec (varint + length-delimited
  encode/decode) covering only the ~6 message types actually needed
  (`PBOperationMetadata`, `PBListOperation`, `PBListOperationList`, `ListItem`, `PBItemQuantity`,
  `PBUserDataResponse`/`ShoppingListsResponse`/`ShoppingList`). No `protobuf` or `grpc` package
  dependency required.
- `httpx` handles all HTTP. No `websockets` dependency was needed for this spike's scope
  (see "Not covered" below).

## Endpoints (base `https://www.anylist.com`, header `X-AnyLeaf-API-Version: 3` throughout)

| Call | Method | Body | Notes |
|---|---|---|---|
| `/auth/token` | POST | multipart: `email`, `password` | Returns JSON `{access_token, refresh_token}` |
| `/auth/token/refresh` | POST | multipart: `refresh_token` | Not exercised by this spike; documented from reference source only |
| `/data/user-data/get` | POST | empty | Headers: `authorization: Bearer <token>`, `X-AnyLeaf-Client-Identifier: <uuid>`. Returns raw protobuf bytes as the body (`Content-Type` is misleadingly `text/html`) — decode as `PBUserDataResponse` |
| `/data/shopping-lists/update` | POST | multipart: `operations` = protobuf bytes | Same auth headers. Body is a `PBListOperationList` containing one or more `PBListOperation`s. Used for both add and remove (different `handlerId`) |

`X-AnyLeaf-Client-Identifier` is just a random UUID generated once per client — it does not need
prior registration.

## The one real surprise

Sending the `operations` multipart part with a filename (e.g. `("operations", body, ...)`)
returns **HTTP 200 with no error and silently does nothing** — the item never appears on the
list. The reference Node client's `form-data` library never sets a filename when appending a
`Buffer`. Matching that exactly — sending the part as `(None, body, "application/octet-stream")`
so it has no filename — fixed it immediately. This cost most of the debugging time; worth
flagging because the failure mode (200 OK, no error, no effect) gives no signal that anything is
wrong unless you re-fetch and diff.

## Another quirk (harmless)

The reference client's `PBOperationMetadata.userId` field is never actually populated — the
`uid` it destructures from the `AnyList` instance is never set anywhere in `index.js`. The spike
replicates that omission (doesn't send `userId` at all) and operations still apply correctly, so
ownership/auth is evidently derived entirely from the bearer token, not this field.

## Not covered by this spike (by design — see CLAUDE.md, "do not build the full connector here")

- The WebSocket listener (`wss://www.anylist.com/data/add-user-listener`, heartbeat every 5s,
  receives `refresh-shopping-lists` push notifications). Phase 5's checklist screen can just
  re-call `/data/user-data/get` on load instead of relying on the socket, if a live-push UI
  isn't wanted.
- Token refresh on 401 (`/auth/token/refresh`) — documented from source, not exercised live.
- Credential persistence — this spike reads plaintext from `.env` each run rather than the
  reference client's encrypted-file cache. Storage approach (`keyring` vs `.env`) is still an
  open Phase 5 decision (see CLAUDE.md > Deferred Decisions) — unaffected by this finding.
- Creating a new list — not attempted; `TestList` already existed in the account. Not needed for
  the planned app flow (lists are pre-existing, user-managed in the AnyList app itself).

## Addendum (2026-09-05): crossed-off state is readable

Confirmed the API distinguishes checked/unchecked items. Added one crossed-off and one plain
item to `TestList` by hand in the AnyList app, then re-fetched via this spike's client:

```
name='Not crossed off'  checked=None   (field 6 absent on the wire — optional bool default False)
name='Crossed off'      checked=True
```

So `ListItem.checked` (protobuf field 6, bool) is the "crossed off" flag — `True` when checked,
`None`/absent when not (proto2 omits `optional` fields at their default value, so treat falsy —
not `is True` — as the unchecked test). Relevant to the Checklist Screen Logic section: the
already-on-AnyList pre-tick behaviour can read this field directly instead of just item presence.

## Addendum (2026-09-05): push order is NOT controllable via `manualSortIndex`

Tested with the list's `listItemSortOrder` in both states (confirmed via the enum:
`ListItemSortOrder { Manual = 0, Alphabetical = 1 }`, protobuf field 17 on `ShoppingList`):

- **Alphabetical mode:** pushed 3 items with distinct `manualSortIndex` values out of insertion
  order. API always returns items in plain insertion order regardless — the raw
  `data/user-data/get` response is never server-sorted by anything.
- **Manual mode** (switched live in the AnyList app): repeated the test — added `SORT-3`,
  `SORT-1`, `SORT-2` in that call order, tagged with `manualSortIndex` 3, 1, 2 respectively (so
  ascending-by-index would read 1, 2, 3). Confirmed on the actual phone app: items displayed as
  **3, 1, 2 — i.e. exactly insertion order**. `manualSortIndex` had no effect on real display
  order even in the mode named after it.

**Conclusion: there is no supported way to push items into AnyList in an arbitrary chosen order
via this field.** The one lever that *does* work is insertion order itself — items appear in the
order the `add-shopping-list-item` operations were submitted (whether as separate calls or,
presumably, multiple operations in one `PBListOperationList` — batching not yet verified, see
Phase 5 open checks below). So "pushing in order" is achievable only by controlling the sequence
you submit adds in, not by any explicit ordering field.

This reinforces (doesn't just "not conflict with") the existing Shop Layout Reorganisation
design: don't rely on AnyList's own ordering for the walking-order feature — render that
entirely app-side from `product_sections`/`store_sections`, as already planned. If a specific
push order is wanted for its own sake (e.g. cosmetic — items appear grouped as pushed), submit
adds in that order; don't reach for `manualSortIndex`.

## Open checks before Phase 5 build (not yet run)

Flagging for whoever picks up Phase 5 — none of these are blockers, but each is cheap to verify
now and would be expensive to discover mid-build:

1. **Quantity update on an existing item** (`set-list-item-quantity` handler, via `updatedValue`
   on `PBListOperation` rather than a full `listItem` submessage — different code path than
   add/remove, untested). This is required by CLAUDE.md's AnyList Push Logic: "if already on
   AnyList, increment quantity on existing item rather than adding duplicate."
2. **Batching multiple operations in one `PBListOperationList`/one HTTP call** — every test so
   far sent one operation per call. The real "push to AnyList in one action" flow will want to
   send the whole consolidated list (10-30 items) in a single call. Needs confirming: (a) it
   works at all, (b) order behaves the same as sequential single-item calls per the finding
   above, (c) a partial failure inside a batch doesn't corrupt the list or fail silently.
3. **Arbitrary `display_qty` strings round-trip cleanly** — e.g. `"2 × 500g packs"` (non-ASCII
   `×`). Low risk (it's just a UTF-8 protobuf string) but cheap to confirm since the push logic
   depends on it.

## Addendum (2026-09-05): the three flagged Phase 5 pre-checks — all resolved

Ran all three checks flagged above against the real account (`TestList`), cleaning up every
test item afterward. Script additions live in `spike/anylist_spike.py`
(`build_operation()` gained an `updated_value` parameter; `AnyListSpikeClient` gained
`post_operations()` and `set_item_quantity()`).

### 1. Updating quantity on an existing item — works, but writes a different field than add does

`set-list-item-quantity` (via `PBListOperation.updatedValue`, field 4 — a different code shape
than add/remove's full `listItem` submessage) **does successfully update the item.**

The subtlety: adding an item with a quantity writes `ListItem.quantityPb.amount` (field 21, the
modern nested representation). But `set-list-item-quantity` writes `ListItem.deprecatedQuantity`
(field 18, the legacy flat string) instead — and doing so **removed field 21 entirely** from the
item on the server (confirmed by dumping the item's raw wire fields after the update: only
`{1: identifier, 3: listId, 4: name, 18: "3"}` remained, field 21 was gone).

This was actually caught as a false negative first: this spike's own decoder originally only
read field 21 for quantity, so the first test run reported the update as silently failing
(quantity came back as `None`). Re-checking the raw wire bytes showed the value really was
there, just under field 18. **Fixed:** `ListItem.from_wire` now checks field 21 first, falling
back to field 18 — the same precedence the reference JS client's `Item` constructor uses
(`quantityPb?.amount ?? deprecatedQuantity ?? quantity`). This is worth repeating in the real
Phase 5 connector: any code reading item quantity back from AnyList must check both fields, not
just the modern one, or it will misread the quantity of any item that has ever been updated
(rather than freshly added) via this handler.

**Confirmed working, with correct decoding:**
```
after add:              quantity='1'   (in quantityPb, field 21)
after set_item_quantity: quantity='3'   (moved to deprecatedQuantity, field 18; field 21 gone)
```

### 2a. Batching multiple operations in one HTTP call — works, order preserved

Sent 5 `add-shopping-list-item` operations inside a single `PBListOperationList` in one POST.
Result: HTTP 200, all 5 present on re-fetch, in exactly the submitted order
(`BATCH-1`..`BATCH-5` in, `BATCH-1`..`BATCH-5` out) — consistent with the earlier
insertion-order finding, now confirmed for the batched case specifically (not just sequential
separate calls). **Safe and recommended** for Phase 5's "push the whole consolidated list in one
action": build one `PBListOperationList` with N `add-shopping-list-item` operations and send it
in a single call, in the desired display order.

### 2b. Partial failure inside a batch — bad operations are silently ignored, good ones still apply

Sent one call with three operations: a valid add, a `remove-shopping-list-item` targeting a
list-item ID that was never added (a made-up UUID), then a second valid add. Result: HTTP 200,
and **both valid adds landed** — the bogus remove was silently ignored rather than failing the
whole batch or erroring.

This is good news for robustness (one bad operation in a big consolidated push won't torpedo the
rest) but also a warning: **the API gives no error signal for a no-op/invalid operation.** A
batch push that's supposed to remove-and-replace a stale AnyList item, say, will report HTTP 200
whether or not the remove actually matched anything — the app can't trust the response to know
whether every operation actually took effect. Confirming success needs a re-fetch-and-diff
against what was intended, the same pattern already used throughout this spike's own add/remove
verification (see `main()` in `anylist_spike.py`) — worth carrying that pattern into the real
Phase 5 connector rather than trusting a 200 status alone.

### 3. Non-ASCII `display_qty` strings — round-trip cleanly

Sent `"2 × 500g packs"` (real Unicode multiplication sign, U+00D7) as an item's quantity on add.
Read back byte-for-byte identical. No encoding concerns — it's a plain UTF-8 protobuf string, as
expected.

## Config added

`ANYLIST_TARGET_LIST_NAME` in `.env`/`.env.example`, defaulting to `TestList`, so dev work never
touches the real household list by accident. Switch it to the actual household list name when Phase 5 goes live.

## Full run log

```
=== AnyList derisking spike starting (target list: 'TestList') ===
Authenticating with AnyList...
Authenticated successfully (access token acquired)
Fetching user data (data/user-data/get)
Fetched 5 list(s): ['Household Shopping', 'Other List', 'Misc List', 'TestList', 'TestList']
Target list 'TestList' has 0 item(s) before the spike: []
Adding item 'ShoppingApp spike test item' (08f348fb16814e8c8905fef07c6c1f2b) to list d69095ecbd55414bacdc5e801ccc00f1
Add-item request accepted (HTTP 200)
Fetching user data (data/user-data/get)
Fetched 5 list(s): [...same 5...]
CONFIRMED: test item is present on the list after add.
Removing item 'ShoppingApp spike test item' (08f348fb16814e8c8905fef07c6c1f2b) from list d69095ecbd55414bacdc5e801ccc00f1
Remove-item request accepted (HTTP 200)
Fetching user data (data/user-data/get)
Fetched 5 list(s): [...same 5...]
CONFIRMED: test item is gone from the list after remove.
=== AnyList derisking spike PASSED: auth, fetch, add, and remove all worked. ===
```
