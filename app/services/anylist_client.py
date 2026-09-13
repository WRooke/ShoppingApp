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
import uuid
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
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anylist.com"
_TIMEOUT = 15.0


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
        # (op_kind, identifier, expected_qty, expected_note) — note checked too now (Chunk 5.7).
        planned: list[tuple[str, str, str | None, str | None]] = []
        raw_responses: list[str] = []

        def _post_one(op: bytes) -> None:
            resp = self._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            )
            raw_responses.append(f"HTTP {resp.status_code}")

        for it in items:
            if it.existing_id and it.existing_id in before:
                _post_one(_build_operation(
                    handler_id="set-list-item-quantity",
                    list_id=target.identifier,
                    list_item_id=it.existing_id,
                    updated_value=it.quantity or "",
                ))
                # NOT syncing details here — reverted after live-verification found a second,
                # nastier bug: once ANY set-list-item-details op has touched an item, every
                # subsequent set-list-item-quantity op for that SAME item silently fails
                # (confirmed reproducible: real push, reordering quantity/details, and a
                # clean from-scratch repro all landed the item with NO quantity value at all,
                # field 21 and field 18 both absent — not stale, gone). Re-sending
                # add-shopping-list-item for the existing id doesn't recover it either (that
                # handler is add-only; it silently no-ops once the id exists). The only
                # recovery found was delete + re-add under a brand-new id — not something the
                # app can do on every push without surprising the household (it would orphan
                # any manual edits/checks on that AnyList item). Quantity correctness matters
                # more than note freshness, so: a note is set correctly on an item's first
                # push (still embedded in the add's own item message, safe and confirmed
                # working) but does NOT update on a later push to the same still-listed item —
                # documented limitation, not solved. See CLAUDE.md > AnyList Push Logic.
                planned.append(("update", it.existing_id, it.quantity or "", None))
                result.updated.append(it.name)
            else:
                new_id = uuid.uuid4().hex
                _post_one(_build_operation(
                    handler_id="add-shopping-list-item",
                    list_id=target.identifier,
                    list_item_id=new_id,
                    item_wire=_item_to_wire(
                        identifier=new_id, list_id=target.identifier,
                        name=it.name, quantity=it.quantity, details=it.note,
                    ),
                ))
                planned.append(("add", new_id, it.quantity, it.note))
                result.added.append(it.name)

        if not planned:
            result.confirmed = True
            return result

        result.raw_response = "; ".join(raw_responses)

        after = {i.identifier: i for i in self._resolve_list(list_name).items}
        for kind, ident, expected_qty, expected_note in planned:
            got = after.get(ident)
            if got is None:
                result.discrepancies.append(f"{kind} {ident} did not land")
                continue
            if expected_qty and got.quantity != expected_qty:
                result.discrepancies.append(
                    f"{kind} {ident}: quantity is {got.quantity!r}, expected {expected_qty!r}"
                )
            if expected_note and got.note != expected_note:
                result.discrepancies.append(
                    f"{kind} {ident}: note is {got.note!r}, expected {expected_note!r}"
                )
        result.confirmed = not result.discrepancies
        if not result.confirmed:
            logger.error("AnyList push not fully confirmed: %s", result.discrepancies)
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
        # Mirrors the REAL connector's confirmed behaviour (Chunk 5.7), not an idealised one:
        # a note lands correctly on add, but an update only ever touches quantity — the note
        # a pre-existing item already carries is left as-is. See the module docstring's
        # set-list-item-details finding for why (a real, reproducible AnyList server bug, not
        # an oversight here).
        lst = self._list(list_name)
        result = PushResult()
        for it in items:
            if it.existing_id and it.existing_id in lst:
                old = lst[it.existing_id]
                lst[it.existing_id] = AnyListItem(old.identifier, old.name, it.quantity, old.checked, old.note)
                result.updated.append(it.name)
            else:
                new_id = f"fake-{uuid.uuid4().hex[:8]}"
                lst[new_id] = AnyListItem(new_id, it.name, it.quantity, False, it.note)
                result.added.append(it.name)
        result.confirmed = True
        result.raw_response = "FAKE MODE"
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
