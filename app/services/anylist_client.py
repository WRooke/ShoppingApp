"""AnyList connector — Python-native, Phase 5 (see CLAUDE.md > Build Phases > Phase 5 and
> Tech Stack > AnyList integration).

One external integration behind one small, stable interface (CLAUDE.md > Code Architecture >
"External integrations sit behind a small, stable interface"): the rest of the app calls
``get_items()`` / ``add_or_increment_items()`` / ``check_auth()`` and never touches
``httpx`` or the protobuf wire format directly. No ``fastapi`` import.

The wire codec and message shapes are lifted from ``spike/anylist_spike.py`` (Phase 1.5
derisking spike) — AnyList's API is unofficial, reverse-engineered from the Node package
``codetheweb/anylist``, and speaks raw protobuf with no public ``.proto``. Several findings
are load-bearing here, the last two from live-verification against the real API at Chunk 5.7
(2026-09-12), which corrected an earlier (2026-09-10) misdiagnosis — see the third bullet:

  * **Quantity lives in two fields.** A freshly *added* item carries ``quantityPb.amount``
    (field 21); an item whose quantity was later *updated* via ``set-list-item-quantity``
    carries the legacy flat ``deprecatedQuantity`` (field 18) instead. Read field 21 first,
    fall back to field 18.
  * **The ``operations`` multipart part must have no filename.** With one, the server returns
    HTTP 200 and silently does nothing.
  * **One operation per HTTP request — never batch, even across different items.** Live
    testing against the real API found AnyList's server silently drops an operation whenever
    a single request's operation list touches more than one distinct ``list_item_id`` —
    reproduced with 2 and 3 items, whether combined in one POST or split into separate ones
    (immediately back-to-back, or several seconds apart). A single item's own op(s) always
    applied correctly. The reference ``codetheweb/anylist`` client independently confirms
    this discipline — every one of its list-mutation methods POSTs exactly one operation,
    alone, every time. This *supersedes* a 2026-09-10 finding that used to live here
    ("a brand-new item's quantity needs a chained ``set-list-item-quantity`` op, embedding it
    on add alone doesn't work") — that finding was almost certainly this same bug, misread
    from a test that (in hindsight) can't be confirmed as single-item. Confirmed live:
    quantity embedded *only* in the add's own item message (field 21) renders correctly with
    no follow-up op, one item per request, exactly matching the reference client's own
    ``_encode()``.
  * **A batch POST returns 200 even if an op was a no-op** (folds into the point above, but
    worth its own line): push success can't be trusted from the HTTP status — always re-fetch
    and diff against intent, which is what makes the finding above detectable at all.
  * **``set-list-item-details`` (present in the reference client's field→handler mapping,
    not previously used here) works for setting a note on an item's own creation — but
    calling it on an item AFTER creation permanently breaks that item's quantity.** Confirmed
    live, reproduced from a clean single-item test: add (quantity + details together) ->
    ``set-list-item-details`` alone (quantity still fine) -> ``set-list-item-quantity`` alone
    (fails from here on — the item's quantity comes back completely absent, field 21 *and*
    18 both gone, not just stale). Order didn't matter, waiting didn't matter, and re-sending
    ``add-shopping-list-item`` for the same id doesn't recover it either (that handler is
    add-only — it silently no-ops once the id already exists). The only recovery found was
    delete + re-add under a brand-new id, which the app can't do on every push without
    orphaning any manual edits/checks a household member made on that AnyList item.
    **Consequence:** a note is set correctly on an item's first push (still embedded in the
    add's own item message — safe, and the mechanism this finding doesn't touch) but does
    **not** update on a later push to an item that's already on the list — a real, accepted
    limitation, not a bug left unfixed by oversight. See CLAUDE.md > AnyList Push Logic.
  * **RESOLVED 2026-09-20 — "Not set" is a confirmed, permanent AnyList server-side limitation
    of ``set-list-item-quantity`` for anything but a bare number.** The field-21/18 split
    doesn't explain it (falsified by phone check, 2026-09-18: a field-18-only item displayed
    correctly). Exhaustive live testing (a 36-cell shape×mechanism factorial, then a targeted
    format/unit sweep, ~80 calls) found no value format survives an update except the literal
    tokens ``"kg"``/``"lb"`` — nowhere near enough to build a fix on. Neither of AnyList's other
    quantity-shaped fields (``packageSizePb``, ``priceQuantityPb``) offers a working update
    path either (no handler exists for either; three tried approaches each failed cleanly).
    **Decisive**: the real, unmodified reference ``anylist`` npm package (real ``protobufjs``
    encoding, not this connector's hand-rolled one) fails identically on the same case, ruling
    out a bug in this app's own wire encoding. See the fault-finding spike's 2026-09-19/20
    addenda for the full trail. **Fix**: see the "replace" branch in
    ``add_or_increment_items()`` below.
  * **The fix: unit-bearing updates go through delete + re-add, not ``set-list-item-quantity``,
    at all.** A bare AnyList-native count (no unit) stays on the original, reliable
    ``set-list-item-quantity`` path. Anything else — the common case, since most ingredients
    here have a unit — deletes the existing item and adds a fresh one under a new id instead,
    since ADD is 100% reliable for any quantity shape. Checked-state and the note both carry
    across explicitly (never silently dropped, per the maintainer's hard requirement): checked
    from the pre-push snapshot, note from the freshly computed value (an improvement over the
    bare-count path, which still never syncs notes — see the point above). Live-confirmed (both
    wire-level and phone-checked) that quantity, note, and checked all survive the cycle intact,
    and re-validated at realistic scale (8 simulated weekly cycles, ~24 items, zero
    discrepancies — see ``spike/anylist_replace_fix_revalidation.py``).
  * **A successful add must write its new identifier back onto the caller's own state.**
    2026-09-18 fault-finding, mechanism #3: without this, a checklist row that was just freshly
    added has no way to know it's now on the list, so a same-session re-push (in particular the
    checklist screen's own "already pushed, push again?" retry, which never reloads first) adds
    it a second time as a duplicate. Fixed 2026-09-19: every add's identifier is returned via
    ``PushResult.added_ids`` (name -> new id); ``checklist.push_to_anylist()`` writes it back
    onto the checklist row immediately. See CLAUDE.md > AnyList Push Logic.

Safety (CLAUDE.md > Security §2, mirrors §0c for the AI): every real call is gated on
``settings.anylist_enabled`` (default off — no agent flips it). ``settings.anylist_fake_mode``
swaps in an in-memory fake list so the whole checklist + push flow runs offline. Manual
verification runs only against ``settings.anylist_target_list_name`` (dev default
``TestList``); the real household list is never touched without a fresh per-occasion
go-ahead.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.config import settings
from app.database import utcnow
from app.services.anylist_wire import (  # noqa: F401 -- re-exported, see anylist_wire.py's docstring
    AnyListItem,
    _WireList,
    _build_operation,
    _build_operation_list,
    _decode_message,
    _field_message,
    _field_string,
    _item_from_wire,
    _item_to_wire,
    _parse_user_data,
    _split_quantity,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anylist.com"
_TIMEOUT = 15.0

# 2026-09-18/19 fault-finding (docs/build-status/anylist-fault-finding-spike.md): a fraction of
# set-list-item-quantity/add-shopping-list-item calls intermittently persist nothing at all -- a
# real AnyList-side failure, HTTP 200 either way, no reliably identified trigger. A bounded
# retry-on-discrepancy turns this from a silent, user-visible data loss into either a
# self-healing no-op or a clearly surfaced discrepancy -- see add_or_increment_items(). See the
# spike doc's 2026-09-19 reliability-investigation addendum for the retry's measured
# effectiveness at realistic scale.
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.0


# --- public types ---------------------------------------------------------------------
#
# AnyListItem itself now lives in anylist_wire.py (the wire codec constructs it directly) and
# is re-exported above — kept documented here too since this is the module every other caller
# actually imports it from.


@dataclass(frozen=True)
class PushItem:
    """One line the app wants on the list. ``existing_id`` set => update that item's quantity
    in place (don't add a duplicate); ``None`` => add a new item. ``note`` -> AnyList's
    ``details`` field (protobuf field 5) — e.g. a purchase-unit overage hint or "to taste"
    (2026-09-10 hand-testing: CLAUDE.md > Checklist Screen Logic asks for notes to reach the
    real list, not just the app's own checklist screen)."""

    name: str
    quantity: str | None
    existing_id: str | None = None
    note: str | None = None


@dataclass
class PushResult:
    added: list[str] = field(default_factory=list)     # names added
    updated: list[str] = field(default_factory=list)   # names whose quantity was set
    confirmed: bool = False                            # re-fetch + diff matched intent
    discrepancies: list[str] = field(default_factory=list)
    raw_response: str | None = None                    # for shopping_history / diagnostics
    added_ids: dict[str, str] = field(default_factory=dict)
    # name -> the new AnyList-assigned identifier, for every item added this call. checklist.py
    # writes this back onto the checklist row (already_on_anylist/anylist_item_id) so a later
    # push -- in particular the UI's own "already pushed, push again?" retry, which doesn't
    # reload first -- updates that item instead of re-adding it as a duplicate. See the
    # 2026-09-18 fault-finding spike's mechanism #3 (docs/build-status/
    # anylist-fault-finding-spike.md).
    retried: list[str] = field(default_factory=list)
    # names that needed at least one retry (see _MAX_RETRIES above) before confirming -- kept
    # here rather than only logged so real-world frequency is visible through
    # shopping_history/diagnostics without needing another spike.


@dataclass(frozen=True)
class AuthStatus:
    ok: bool
    detail: str
    checked_at: datetime


# --- exceptions ---------------------------------------------------------------------


class AnyListError(Exception):
    """Any AnyList failure the app should surface (network, protocol, unexpected shape).
    Translated to a 502 envelope in app/main.py."""


class AnyListAuthError(AnyListError):
    """Authentication with AnyList failed (bad credentials, or a 401 that a re-login didn't
    fix). 502 with its own code."""


class AnyListDisabledError(Exception):
    """A real AnyList call was attempted with settings.anylist_enabled False. 503 in
    app/main.py — same shape as AiExtractionDisabledError."""


@dataclass(frozen=True)
class _PlannedOp:
    """One op `add_or_increment_items` has sent (or is about to retry) — what to check for on
    the next re-fetch, and how to resend the exact same op if it's still wrong. `kind` is
    "add", "update" (a bare-count quantity change via `set-list-item-quantity`), or "replace"
    (a unit-bearing quantity change, via delete + re-add under a new id — see the "replace"
    branch below for why)."""

    kind: str
    ident: str
    name: str
    rebuild: Callable[[], bytes]
    expected_qty: str | None = None
    expected_note: str | None = None
    expected_checked: bool | None = None


# --- real connector ---------------------------------------------------------------------


class _RealAnyList:
    """Talks to www.anylist.com. Instantiated once per process and cached; a 401 on a data
    call triggers one fresh full re-login + retry (the spike didn't exercise token refresh,
    so we just re-auth with the credentials we already hold)."""

    def __init__(self, email: str, password: str) -> None:
        if not email or not password or "REPLACE_ME" in email or "REPLACE_ME" in password:
            raise AnyListAuthError("AnyList credentials are not configured (see Security §2)")
        self._email = email
        self._password = password
        self._client_id = uuid.uuid4().hex
        self._token: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT)

    # -- auth --
    def login(self) -> None:
        logger.info("AnyList: authenticating as %s", self._email)
        try:
            resp = self._http.post(
                "/auth/token",
                headers={"X-AnyLeaf-API-Version": "3"},
                files={"email": (None, self._email), "password": (None, self._password)},
            )
        except httpx.HTTPError as exc:
            raise AnyListAuthError(f"could not reach AnyList to authenticate: {exc}") from exc
        if resp.status_code != 200:
            logger.error("AnyList auth failed: status=%s body=%s", resp.status_code, resp.text[:300])
            raise AnyListAuthError(f"AnyList rejected the credentials (HTTP {resp.status_code})")
        try:
            self._token = resp.json()["access_token"]
        except (ValueError, KeyError) as exc:
            raise AnyListAuthError("AnyList auth response had no access_token") from exc
        logger.info("AnyList: authenticated")

    def _headers(self) -> dict[str, str]:
        return {
            "X-AnyLeaf-API-Version": "3",
            "X-AnyLeaf-Client-Identifier": self._client_id,
            "authorization": f"Bearer {self._token}",
        }

    def _data_post(self, path: str, *, files=None) -> httpx.Response:
        """POST to a /data/ endpoint, logging in first if needed and re-logging once on a 401."""
        if self._token is None:
            self.login()
        for attempt in (1, 2):
            try:
                resp = self._http.post(path, headers=self._headers(), files=files)
            except httpx.HTTPError as exc:
                raise AnyListError(f"AnyList request to {path} failed: {exc}") from exc
            if resp.status_code == 401 and attempt == 1:
                logger.warning("AnyList: 401 on %s — re-authenticating and retrying once", path)
                self.login()
                continue
            if resp.status_code != 200:
                logger.error("AnyList %s failed: status=%s body=%r", path, resp.status_code, resp.content[:300])
                raise AnyListError(f"AnyList {path} returned HTTP {resp.status_code}")
            return resp
        raise AnyListError(f"AnyList {path} still 401 after re-authenticating")

    # -- reads --
    def _get_lists(self) -> list[_WireList]:
        resp = self._data_post("/data/user-data/get")
        try:
            return _parse_user_data(resp.content)
        except AnyListError:
            raise
        except Exception as exc:  # noqa: BLE001 — a decode failure is still an AnyListError
            raise AnyListError(f"could not parse AnyList user-data response: {exc}") from exc

    def _resolve_list(self, list_name: str) -> _WireList:
        lists = self._get_lists()
        match = next((l for l in lists if (l.name or "").strip() == list_name.strip()), None)
        if match is None:
            raise AnyListError(
                f"AnyList list {list_name!r} not found on this account "
                f"(available: {[l.name for l in lists]})"
            )
        return match

    def get_items(self, list_name: str) -> list[AnyListItem]:
        return list(self._resolve_list(list_name).items)

    def check_auth(self) -> AuthStatus:
        try:
            self.login()
            return AuthStatus(True, "Authenticated", utcnow())
        except AnyListError as exc:
            return AuthStatus(False, str(exc), utcnow())

    # -- writes --
    def add_or_increment_items(self, list_name: str, items: list[PushItem]) -> PushResult:
        """Add/update each item, then re-fetch + diff to confirm (spike finding #3: a 200
        doesn't mean every op landed).

        **One operation per HTTP request — never batched, even across different items.**
        Chunk 5.7 live-verification (2026-09-12) found that AnyList's server silently drops
        an operation whenever a request's ``PBListOperationList`` contains ops targeting more
        than one distinct ``list_item_id`` — reproduced against the real API with 2 and 3
        items, whether the ops were combined in one POST or split into separate POSTs sent
        back-to-back or several seconds apart (ruling out both a batching-format issue and a
        "new item needs to settle" timing issue). A single item's own op(s) always applied
        correctly, batched or not. The reference ``codetheweb/anylist`` Node client (the
        project this connector was adapted from — see CLAUDE.md > Tech Stack) independently
        confirms this discipline: every method in its ``lib/list.js``/``lib/item.js``
        (``addItem`` / ``removeItem`` / ``save``) builds a ``PBListOperationList`` with
        exactly one operation and POSTs it alone — it never combines operations for
        different items into one request either.

        This *also* means the previous "chain a set-list-item-quantity op immediately after
        add, in the same batch" workaround (2026-09-10) was superseded, not just superfluous:
        that workaround was almost certainly compensating for this exact bug, misread at the
        time as "the embedded quantityPb.amount field doesn't work" when a single-item test
        would have looked identical either way. Confirmed live: quantity embedded *only* in
        the add's own item message (field 21, matching the reference client's ``_encode()``)
        renders correctly with no follow-up op, one item per request. ``set-list-item-details``
        (present in the reference client's ``OP_MAPPING``, not previously used here) is real
        and working — used below to fix the second live-verification finding: the old
        update path only ever sent ``set-list-item-quantity``, silently leaving a stale note
        forever on an item that already existed on the list.
        """
        target = self._resolve_list(list_name)
        before = {i.identifier: i for i in target.items}
        result = PushResult()
        planned: list[_PlannedOp] = []
        raw_responses: list[str] = []

        def _post_one(op: bytes) -> None:
            resp = self._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            )
            raw_responses.append(f"HTTP {resp.status_code}")

        # NOT syncing details on any update path below — reverted after live-verification found
        # a second, nastier bug: once ANY set-list-item-details op has touched an item, every
        # subsequent set-list-item-quantity op for that SAME item silently fails (confirmed
        # reproducible: real push, reordering quantity/details, and a clean from-scratch repro
        # all landed the item with NO quantity value at all, field 21 and field 18 both absent —
        # not stale, gone). Re-sending add-shopping-list-item for the existing id doesn't
        # recover it either (that handler is add-only; it silently no-ops once the id exists).
        # The only recovery found was delete + re-add under a brand-new id — not something the
        # app can do on every push without surprising the household (it would orphan any manual
        # edits/checks on that AnyList item). A note is set correctly on an item's first push
        # (still embedded in the add's own item message, safe and confirmed working) but does
        # NOT update on a later push to the same still-listed item — documented limitation, not
        # solved. See CLAUDE.md > AnyList Push Logic. (A 2026-09-19 controlled A/B found no
        # differential failure rate between details-touched and untouched items, casting doubt
        # on this finding — but not yet re-verified enough to act on, see the fault-finding
        # spike's 2026-09-19 addendum.)
        for it in items:
            if it.existing_id and it.existing_id in before:
                # 2026-09-20 fault-finding (Stage 1 of the reliability investigation, plus a
                # live parity check against the real, unmodified reference `anylist` npm
                # package — see docs/build-status/anylist-fault-finding-spike.md): no
                # request-shape fixes `set-list-item-quantity` for a unit-bearing value. A full
                # item-message embed on this handler does no better than a plain value; no
                # quantity *format* survives an update except two literal unit tokens
                # ("kg"/"lb") that don't cover this app's actual units; the real reference
                # client, using real `protobufjs` encoding, fails identically on the exact same
                # case (ruling out a bug in this app's own wire encoding); and neither of
                # AnyList's other quantity-shaped fields (`packageSizePb`, `priceQuantityPb`)
                # offers a working update path either (Phase A of the same investigation — no
                # handler exists for either, three live approaches each 0/4 or ruled out by
                # what they display). Confirmed AnyList server-side limitation, not something
                # any client can work around by sending it differently.
                #
                # A bare AnyList-native count (no unit, e.g. "3") is unaffected by any of the
                # above and stays on the simple, reliable `set-list-item-quantity` path.
                raw_q, amount, unit = _split_quantity(it.quantity or "")
                is_bare_count = not it.quantity or (unit is None and amount == raw_q)
                if is_bare_count:
                    def rebuild(it=it):
                        return _build_operation(
                            handler_id="set-list-item-quantity",
                            list_id=target.identifier,
                            list_item_id=it.existing_id,
                            updated_value=it.quantity or "",
                        )
                    _post_one(rebuild())
                    planned.append(_PlannedOp("update", it.existing_id, it.name, rebuild, expected_qty=it.quantity or ""))
                else:
                    # 2026-09-20 fix (Phase B of the same investigation): for anything
                    # unit-bearing, delete the old item and add a fresh one under a new id
                    # instead — ADD is 100% reliable for any quantity shape (unlike UPDATE),
                    # including the checked state and note, both live-confirmed (6/6) to land
                    # correctly when set on add. The old item's checked state and note are
                    # carried across explicitly (never silently dropped) — checked from
                    # `before` (already known, no extra fetch), note from `it.note` (the
                    # freshly computed value for this push, matching what a working update
                    # would have shown rather than leaving last week's stale text). The
                    # checklist row's own `anylist_item_id` gets updated to the new id via
                    # `added_ids` below, same mechanism the duplicate-on-repush fix already
                    # uses, or the *next* push would look for the now-deleted old id.
                    old = before[it.existing_id]
                    new_id = uuid.uuid4().hex

                    def rebuild_remove(it=it):
                        return _build_operation(
                            handler_id="remove-shopping-list-item",
                            list_id=target.identifier,
                            list_item_id=it.existing_id,
                            item_wire=_item_to_wire(
                                identifier=it.existing_id, list_id=target.identifier,
                                name=it.name, quantity=None,
                            ),
                        )
                    _post_one(rebuild_remove())

                    def rebuild_add(it=it, new_id=new_id, was_checked=bool(old.checked)):
                        return _build_operation(
                            handler_id="add-shopping-list-item",
                            list_id=target.identifier,
                            list_item_id=new_id,
                            item_wire=_item_to_wire(
                                identifier=new_id, list_id=target.identifier,
                                name=it.name, quantity=it.quantity, details=it.note,
                                checked=was_checked,
                            ),
                        )
                    _post_one(rebuild_add())
                    planned.append(_PlannedOp(
                        "replace", new_id, it.name, rebuild_add,
                        expected_qty=it.quantity, expected_note=it.note, expected_checked=bool(old.checked),
                    ))
                    result.added_ids[it.name] = new_id
                result.updated.append(it.name)
            else:
                new_id = uuid.uuid4().hex

                def rebuild(it=it, new_id=new_id):
                    return _build_operation(
                        handler_id="add-shopping-list-item",
                        list_id=target.identifier,
                        list_item_id=new_id,
                        item_wire=_item_to_wire(
                            identifier=new_id, list_id=target.identifier,
                            name=it.name, quantity=it.quantity, details=it.note,
                        ),
                    )
                _post_one(rebuild())
                planned.append(_PlannedOp(
                    "add", new_id, it.name, rebuild, expected_qty=it.quantity, expected_note=it.note,
                ))
                result.added.append(it.name)
                result.added_ids[it.name] = new_id

        if not planned:
            result.confirmed = True
            return result

        result.raw_response = "; ".join(raw_responses)

        def _check(subset: list[_PlannedOp]) -> dict[str, str]:
            """ident -> discrepancy string, for `subset` entries still wrong after a fresh
            fetch. A full-list re-fetch either way (matches the pre-retry behaviour) — the
            `subset` only narrows which entries are checked, not what's fetched."""
            after = {i.identifier: i for i in self._resolve_list(list_name).items}
            bad: dict[str, str] = {}
            for p in subset:
                got = after.get(p.ident)
                if got is None:
                    bad[p.ident] = f"{p.kind} {p.ident} did not land"
                    continue
                if p.expected_qty and got.quantity != p.expected_qty:
                    bad[p.ident] = f"{p.kind} {p.ident}: quantity is {got.quantity!r}, expected {p.expected_qty!r}"
                    continue
                if p.expected_checked is not None and got.checked != p.expected_checked:
                    bad[p.ident] = f"{p.kind} {p.ident}: checked is {got.checked!r}, expected {p.expected_checked!r}"
                    continue
                if p.expected_note and got.note != p.expected_note:
                    bad[p.ident] = f"{p.kind} {p.ident}: note is {got.note!r}, expected {p.expected_note!r}"
            return bad

        bad = _check(planned)
        outstanding = [p for p in planned if p.ident in bad]
        # 2026-09-18/19 fault-finding: a fraction of ops silently persist nothing at all (real
        # AnyList-side flakiness, not a bug in what this app sends — see _MAX_RETRIES' comment
        # above). Retry just the still-wrong items, each with its own fresh confirm, before
        # giving up — turns a silent loss into either a self-heal or a clearly surfaced
        # discrepancy, never both invisible and wrong.
        for attempt in range(_MAX_RETRIES):
            if not outstanding:
                break
            logger.warning(
                "AnyList push: retry %d/%d for %d item(s): %s",
                attempt + 1, _MAX_RETRIES, len(outstanding), [p.name for p in outstanding],
            )
            time.sleep(_RETRY_BACKOFF_S)
            for p in outstanding:
                _post_one(p.rebuild())
                result.retried.append(p.name)
            bad = _check(outstanding)
            outstanding = [p for p in outstanding if p.ident in bad]

        result.discrepancies = list(bad.values())
        result.confirmed = not result.discrepancies
        if not result.confirmed:
            logger.error("AnyList push not fully confirmed after retries: %s", result.discrepancies)
        return result


# --- in-memory fake ---------------------------------------------------------------------

# Deterministic seed so the checklist pre-tick path always has something to match against in
# fake mode. Keyed by list name -> {item_id: AnyListItem}.
_FAKE_SEED = {
    "milk": ("2L bottle", False),
    "eggs": ("1 dozen", False),
    "butter": (None, True),
}


class _FakeAnyList:
    def __init__(self) -> None:
        self._lists: dict[str, dict[str, AnyListItem]] = {}
        target = settings.anylist_target_list_name
        self._lists[target] = {
            f"seed-{name}": AnyListItem(f"seed-{name}", name, qty, checked)
            for name, (qty, checked) in _FAKE_SEED.items()
        }

    def _list(self, list_name: str) -> dict[str, AnyListItem]:
        return self._lists.setdefault(list_name, {})

    def get_items(self, list_name: str) -> list[AnyListItem]:
        return list(self._list(list_name).values())

    def check_auth(self) -> AuthStatus:
        return AuthStatus(True, "FAKE MODE — no real AnyList call", utcnow())

    def add_or_increment_items(self, list_name: str, items: list[PushItem]) -> PushResult:
        # Mirrors the REAL connector's confirmed behaviour, not an idealised one. A bare count
        # (no unit) updates in place, note untouched (Chunk 5.7 — set-list-item-details on an
        # existing item permanently breaks its quantity on the real API). A unit-bearing
        # quantity instead replaces the item under a new id (2026-09-20, Phase B) — the note
        # and checked state both carry across, since that's what the real "replace" does too.
        lst = self._list(list_name)
        result = PushResult()
        for it in items:
            if it.existing_id and it.existing_id in lst:
                old = lst[it.existing_id]
                raw_q, amount, unit = _split_quantity(it.quantity or "")
                is_bare_count = not it.quantity or (unit is None and amount == raw_q)
                if is_bare_count:
                    lst[it.existing_id] = AnyListItem(old.identifier, old.name, it.quantity, old.checked, old.note)
                else:
                    del lst[it.existing_id]
                    new_id = f"fake-{uuid.uuid4().hex[:8]}"
                    lst[new_id] = AnyListItem(new_id, it.name, it.quantity, old.checked, it.note)
                    result.added_ids[it.name] = new_id
                result.updated.append(it.name)
            else:
                new_id = f"fake-{uuid.uuid4().hex[:8]}"
                lst[new_id] = AnyListItem(new_id, it.name, it.quantity, False, it.note)
                result.added.append(it.name)
                result.added_ids[it.name] = new_id
        result.confirmed = True
        result.raw_response = "FAKE MODE"
        # never fails, so `retried` stays empty -- fake mode doesn't model the real connector's
        # intermittent-silent-failure quirk (see _MAX_RETRIES' comment), only its confirmed
        # behaviour.
        return result


# --- module surface -------------------------------------------------------------------

_lock = threading.Lock()
_instance: _RealAnyList | _FakeAnyList | None = None
_last_ok_at: datetime | None = None


def _mark_ok() -> None:
    global _last_ok_at
    _last_ok_at = utcnow()


def last_success_at() -> datetime | None:
    """When a real (or fake) AnyList call last succeeded this process. Diagnostics reads this
    rather than doing a live round-trip on every auto-poll."""
    return _last_ok_at


def _get_client() -> _RealAnyList | _FakeAnyList:
    """The process-wide connector. Fake when settings.anylist_fake_mode; otherwise a real
    client gated on settings.anylist_enabled. Cached — a real client keeps its token across
    calls (and re-logs in on a 401 itself)."""
    global _instance
    with _lock:
        if settings.anylist_fake_mode:
            if not isinstance(_instance, _FakeAnyList):
                _instance = _FakeAnyList()
            return _instance
        if not settings.anylist_enabled:
            raise AnyListDisabledError(
                "AnyList is disabled — set ANYLIST_ENABLED=true (and see Security §2) to make "
                "real calls, or ANYLIST_FAKE_MODE=true for offline development."
            )
        if not isinstance(_instance, _RealAnyList):
            _instance = _RealAnyList(settings.anylist_email, settings.anylist_password)
        return _instance


def reset_client() -> None:
    """Drop the cached connector (used by tests, and after a config change)."""
    global _instance
    with _lock:
        _instance = None


def get_items(list_name: str | None = None) -> list[AnyListItem]:
    """Current items on the target list (defaults to settings.anylist_target_list_name)."""
    name = list_name or settings.anylist_target_list_name
    result = _get_client().get_items(name)
    _mark_ok()
    return result


def add_or_increment_items(
    items: list[PushItem], *, list_name: str | None = None
) -> PushResult:
    """Push a batch: add new items, set the quantity on ones already present (no duplicates),
    then re-fetch + diff to confirm. See CLAUDE.md > AnyList Push Logic."""
    name = list_name or settings.anylist_target_list_name
    result = _get_client().add_or_increment_items(name, items)
    _mark_ok()
    return result


def check_auth() -> AuthStatus:
    """For the diagnostics panel — does a real (or fake) auth round-trip and returns a
    timestamped status. Never raises."""
    try:
        status = _get_client().check_auth()
        if status.ok:
            _mark_ok()
        return status
    except AnyListDisabledError as exc:
        return AuthStatus(False, str(exc), utcnow())
    except AnyListError as exc:
        return AuthStatus(False, str(exc), utcnow())
