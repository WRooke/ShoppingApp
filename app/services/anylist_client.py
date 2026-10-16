"""AnyList connector — Python-native, Phase 5 (see docs/build-status/phase-5-checklist-anylist.md and
> Tech Stack > AnyList integration).

One external integration behind one small, stable interface (docs/code-architecture.md > Code Architecture >
"External integrations sit behind a small, stable interface"): the rest of the app calls
``get_items()`` / ``add_or_increment_items()`` / ``check_auth()`` and never touches
``httpx`` or the protobuf wire format directly. No ``fastapi`` import.

The wire codec and message shapes are lifted from ``spike/anylist_spike.py`` (Phase 1.5
derisking spike) — AnyList's API is unofficial, reverse-engineered from the Node package
``codetheweb/anylist``, and speaks raw protobuf with no public ``.proto``. Several findings
are essential to get right here, the last two from live-verification against the real API at Chunk 5.7
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
    limitation, not a bug left unfixed by oversight. See docs/anylist-push.md > AnyList Push Logic.
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
    onto the checklist row immediately. See docs/anylist-push.md > AnyList Push Logic.

Safety (docs/security.md > AnyList credentials, mirrors the AI enable switch in docs/security.md > API enable switch): every real call requires
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
from dataclasses import dataclass, field, replace
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
# After this many lines in a row fail to SEND (network down, repeated 5xx), stop attempting the
# rest instead of waiting out a 15 s timeout per line; the unsent lines are reported as failed.
_MAX_CONSECUTIVE_FAILURES = 3
# AnyList sometimes takes longer than _TIMEOUT to answer a read (seen ~3 times in a few minutes of
# live TestList runs, 2026-10-06). A read is idempotent, so it is retried before giving up; a
# WRITE is never blindly retried at this layer (see add_or_increment_items for how those are
# re-sent safely, after a read-back).
_READ_ATTEMPTS = 3

# 2026-10-06 (Chunk 6.7, user-feedback batch), live-verified on TestList (spike/anylist_checked_toggle_test.py): the
# reference client's `set-list-item-checked` op ('y'/'n' as `updatedValue`, NO item message) really
# does cross an item off / un-cross it — 6/6 each way, with name, quantity and note untouched, a
# later `set-list-item-quantity` still working (3/3) and an item that STARTED crossed off
# un-crossing correctly (6/6). The 2026-09-18 probe that concluded "no checked write path" had sent
# `"1"`. So a crossed-off item is un-crossed IN PLACE (same AnyList id, the household's own note
# survives) instead of being removed and re-added. Flip to False to fall back to remove + re-add
# (also proven) if AnyList ever stops honouring it; the read-back would catch it either way.
_UNCROSS_IN_PLACE = True


# --- public types ---------------------------------------------------------------------
#
# AnyListItem itself now lives in anylist_wire.py (the wire codec constructs it directly) and
# is re-exported above — kept documented here too since this is the module every other caller
# actually imports it from.


@dataclass(frozen=True)
class PushItem:
    """One line the app wants on the list, always in its final state "needed": on the list,
    NOT crossed off, with this quantity and note.

    ``existing_id`` is the AnyList item the caller believes is this line (found by name match
    against a fresh read of the list — see ``checklist.push_to_anylist``); ``None`` means "not
    on the list". The connector re-checks it against its own fresh read and decides what to
    actually send (see ``_decide``), so a stale id is harmless. ``note`` -> AnyList's
    ``details`` field (protobuf field 5). ``key`` is the caller's stable id for the line
    ("item:12", "usual:3") — per-item results and progress are reported by it, never by name,
    because two lines can share a display name (Chunk 6.7: results are keyed by line id, not display name)."""

    name: str
    quantity: str | None
    existing_id: str | None = None
    note: str | None = None
    key: str = ""

    @property
    def ref(self) -> str:
        return self.key or self.name


# Per-item outcomes (PushItemResult.outcome). "failed" always carries a human-readable reason.
OUTCOME_ADDED = "added"
OUTCOME_UPDATED = "updated"
OUTCOME_UNCROSSED = "un-crossed"
OUTCOME_ACTIVE = "already-active"
OUTCOME_FAILED = "failed"


@dataclass
class PushItemResult:
    """What happened to one pushed line, as confirmed by the post-push read-back — never what
    the HTTP status said. ``intended`` is the outcome that was attempted (useful when
    ``outcome`` is "failed"); ``retries`` counts how many times the write was re-sent."""

    key: str
    name: str
    outcome: str
    intended: str
    reason: str | None = None
    ident: str | None = None
    retries: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome != OUTCOME_FAILED

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "outcome": self.outcome,
            "intended": self.intended, "reason": self.reason, "ident": self.ident,
            "retries": self.retries,
        }


@dataclass
class PushResult:
    push_id: str | None = None
    items: list[PushItemResult] = field(default_factory=list)  # one per pushed line, in order
    confirmed: bool = False  # every line passed the post-push read-back
    discrepancies: list[str] = field(default_factory=list)  # "<name> — <reason>", failed lines only
    raw_response: str | None = None  # for shopping_history / diagnostics
    added_ids: dict[str, str] = field(default_factory=dict)
    # PushItem.ref -> the AnyList identifier the line lives under now (a fresh add, or the new id a
    # replace created). The caller writes it back onto its own row so a later push finds the item
    # without a name match (see checklist.push_to_anylist).
    retried: list[str] = field(default_factory=list)  # names that needed at least one re-send
    after_items: list[AnyListItem] = field(default_factory=list)  # the final read-back snapshot
    timings: dict[str, float] = field(default_factory=dict)  # seconds: read / send / confirm

    # Name lists, kept for the existing API/UI shape (derived from `items`).
    @property
    def added(self) -> list[str]:
        return [r.name for r in self.items if r.outcome == OUTCOME_ADDED]

    @property
    def updated(self) -> list[str]:
        return [r.name for r in self.items if r.outcome in (OUTCOME_UPDATED, OUTCOME_UNCROSSED)]

    @property
    def uncrossed(self) -> list[str]:
        return [r.name for r in self.items if r.outcome == OUTCOME_UNCROSSED]

    @property
    def already_active(self) -> list[str]:
        return [r.name for r in self.items if r.outcome == OUTCOME_ACTIVE]

    @property
    def failed(self) -> list[str]:
        return [r.name for r in self.items if r.outcome == OUTCOME_FAILED]


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
class _Decision:
    """What to send for one wanted line, given a fresh read of the list. ``kind``:

    * ``"add"``     — not on the list: ``add-shopping-list-item`` under a new id.
    * ``"noop"``    — already on the list, NOT crossed off, same quantity (and, where a note can
      be synced, same note): send nothing.
    * ``"update"``  — active item, bare-count quantity change: ``set-list-item-quantity``
      (reliable for a bare number only, see the module docstring).
    * ``"uncross"`` — item is crossed off, quantity/note already right: `set-list-item-checked`
      'n' (see ``_UNCROSS_IN_PLACE``).
    * ``"uncross_update"`` — crossed off AND a bare-count quantity change: un-cross, then
      `set-list-item-quantity`.
    * ``"replace"`` — anything else that must change on an existing item: remove it and re-add
      it under a new id (ADD is the one reliable write for every quantity shape, the note and
      the checked flag). Also the fallback for un-crossing when ``_UNCROSS_IN_PLACE`` is off.
    """

    kind: str
    outcome: str  # the PushItemResult.outcome this lands as
    reason: str  # why — logged on every push so the next oddity explains itself


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip() == (b or "").strip()


def _note_ok(old: AnyListItem, it: PushItem) -> bool:
    """Is the note already as wanted? When this push has NO note to set (``it.note is None``) the
    item's existing note is none of its business - a household member may have typed their own
    ("organic only") - so it counts as fine; only a note we actually want to set can differ."""
    return it.note is None or _same(old.note, it.note)


def _same_qty(a: str | None, b: str | None) -> bool:
    """Quantities are equal ignoring case and runs of spaces: "1 L" typed on the phone is the same
    amount as the "1 l" this app wrote, and rewriting it would only churn the item."""
    return " ".join((a or "").casefold().split()) == " ".join((b or "").casefold().split())


def _exact_name(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def _resolve_existing(it: PushItem, before: dict[str, AnyListItem]) -> PushItem:
    """The caller says which AnyList item this line is (``existing_id``) from its own fuzzy name
    match against a fresh read — but the id can be missing or stale (the list changed in the
    moments between that read and this one, or the caller found no match). Adding anyway would
    create a duplicate, so as a last safety net, if the id is not on the list, fall back to an
    item with exactly the same name (case/space-insensitive), preferring an active one. Anything
    fuzzier is the caller's job (checklist._names_match); this only stops the obvious duplicate."""
    if it.existing_id and it.existing_id in before:
        return it
    same = [i for i in before.values() if _exact_name(i.name) == _exact_name(it.name)]
    best = next((i for i in same if not i.checked), same[0] if same else None)
    return replace(it, existing_id=best.identifier if best else None)


def _is_bare_count(quantity: str | None) -> bool:
    raw_q, amount, unit = _split_quantity(quantity or "")
    return not quantity or (unit is None and amount == raw_q)


def _decide(it: PushItem, before: dict[str, AnyListItem]) -> _Decision:
    """The one place that decides how a wanted line is written. Shared by the real connector
    and the in-memory fake so they cannot drift apart. Every outcome ends with the line on the
    list, uncrossed, with the wanted quantity — that is the whole contract of a push.

    Compared with the pre-6.7 behaviour: a crossed-off item is no longer left crossed off (it is
    replaced uncrossed); an identical active item is left alone instead of being re-written (a
    redundant write is only a chance for AnyList's flaky quantity handler to corrupt it); and a
    wanted-empty quantity on an item that has one is a replace, because an empty
    ``set-list-item-quantity`` is a silent no-op (spike probe 6)."""
    if not it.existing_id:
        return _Decision("add", OUTCOME_ADDED, "not on the list")
    old = before.get(it.existing_id)
    if old is None:
        return _Decision(
            "add", OUTCOME_ADDED,
            "recorded AnyList id is no longer on the list (deleted since it was read) — adding fresh",
        )
    bare = _is_bare_count(it.quantity)
    if old.checked:
        if _UNCROSS_IN_PLACE:
            if _same_qty(old.quantity, it.quantity) and (bare or _note_ok(old, it)):
                return _Decision("uncross", OUTCOME_UNCROSSED, "crossed off on the list — un-crossing it in place")
            if bare and it.quantity:
                return _Decision(
                    "uncross_update", OUTCOME_UNCROSSED,
                    "crossed off on the list and the bare-count quantity changed — un-cross, then set quantity",
                )
        return _Decision("replace", OUTCOME_UNCROSSED, "crossed off on the list — re-adding it uncrossed")
    if _same_qty(old.quantity, it.quantity) and (bare or _note_ok(old, it)):
        return _Decision("noop", OUTCOME_ACTIVE, "already on the list, uncrossed, same quantity")
    if bare and it.quantity:
        return _Decision("update", OUTCOME_UPDATED, "active item, bare-count quantity changed")
    return _Decision(
        "replace", OUTCOME_UPDATED,
        "active item, quantity/note changed and cannot be edited in place" if it.quantity
        else "active item has a quantity but none is wanted (an empty update is a no-op)",
    )


@dataclass
class _PlannedOp:
    """One wanted line's write, remembered so the read-back can check it and the retry loop can
    re-send exactly the same op. ``ident`` is the id the line must be found under afterwards;
    ``old_ident`` (replace only) is the id that must be GONE (else the replace left a
    duplicate). Mutable: ``errors`` collects send failures, ``retries`` the re-sends."""

    item: PushItem
    kind: str
    intended: str
    ident: str | None = None
    old_ident: str | None = None
    # The ordered writes for this line, each (label, builder): re-sent in full on a retry (every
    # one is idempotent — a toggle to the same state, a set to the same quantity, an ADD of an id
    # that exists is a silent no-op). A replace's remove is separate: it is only re-sent while the
    # old item is still on the list.
    steps: list[tuple[str, Callable[[], bytes]]] = field(default_factory=list)
    rebuild_remove: Callable[[], bytes] | None = None
    # Last-resort for a replace whose remove keeps being ignored: cross the OLD item off so it is
    # not an active duplicate on the shopping list (uses the verified set-list-item-checked op).
    rebuild_cross_off_old: Callable[[], bytes] | None = None
    expected_qty: str | None = None
    expected_note: str | None = None
    check_note: bool = False  # only add/replace set a note; a bare-count update can't
    check_name: bool = False  # only add/replace set the name
    errors: list[str] = field(default_factory=list)
    retries: int = 0
    not_sent: bool = False


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
        logger.info("AnyList: authenticating")  # never log the account email (PII policy)
        started = time.monotonic()
        try:
            resp = self._http.post(
                "/auth/token",
                headers={"X-AnyLeaf-API-Version": "3"},
                files={"email": (None, self._email), "password": (None, self._password)},
            )
        except httpx.HTTPError as exc:
            # 2026-10-07 logging audit: a transport failure here used to be logged nowhere at the
            # point it happened. Log what failed (exception type, how long we waited) — the
            # request that surfaces it gets the traceback from the 502 handler.
            logger.warning(
                "AnyList auth: could not reach AnyList after %.1fs (%s: %s)",
                time.monotonic() - started, type(exc).__name__, exc,
            )
            raise AnyListAuthError(f"could not reach AnyList to authenticate: {exc}") from exc
        if resp.status_code != 200:
            # Status and size only — the body can echo account details back (PII policy).
            logger.error(
                "AnyList auth failed: status=%s body_bytes=%d after %.1fs",
                resp.status_code, len(resp.content), time.monotonic() - started,
            )
            raise AnyListAuthError(f"AnyList rejected the credentials (HTTP {resp.status_code})")
        try:
            self._token = resp.json()["access_token"]
        except (ValueError, KeyError) as exc:
            logger.error(
                "AnyList auth response was not usable (%s: %s); body_bytes=%d",
                type(exc).__name__, exc, len(resp.content),
            )
            raise AnyListAuthError("AnyList auth response had no access_token") from exc
        logger.info("AnyList: authenticated in %.1fs", time.monotonic() - started)

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
            started = time.monotonic()
            try:
                resp = self._http.post(path, headers=self._headers(), files=files)
            except httpx.HTTPError as exc:
                logger.warning(
                    "AnyList request %s failed after %.1fs (attempt %d/2): %s: %s",
                    path, time.monotonic() - started, attempt, type(exc).__name__, exc,
                )
                raise AnyListError(f"AnyList request to {path} failed: {exc}") from exc
            if resp.status_code == 401 and attempt == 1:
                logger.warning("AnyList: 401 on %s — re-authenticating and retrying once", path)
                self.login()
                continue
            if resp.status_code != 200:
                logger.error(
                    "AnyList %s failed: status=%s body_bytes=%d after %.1fs (attempt %d/2)",
                    path, resp.status_code, len(resp.content), time.monotonic() - started, attempt,
                )
                raise AnyListError(f"AnyList {path} returned HTTP {resp.status_code}")
            logger.debug("AnyList %s ok in %.2fs", path, time.monotonic() - started)
            return resp
        logger.error("AnyList %s still 401 after re-authenticating", path)
        raise AnyListError(f"AnyList {path} still 401 after re-authenticating")

    # -- reads --
    def _get_lists(self) -> list[_WireList]:
        resp = None
        for attempt in range(1, _READ_ATTEMPTS + 1):
            try:
                resp = self._data_post("/data/user-data/get")
                break
            except AnyListAuthError:
                raise  # bad credentials won't fix themselves
            except AnyListError as exc:
                if attempt == _READ_ATTEMPTS:
                    raise
                logger.warning(
                    "AnyList list read failed (attempt %d/%d) — %s", attempt, _READ_ATTEMPTS, exc
                )
                time.sleep(_RETRY_BACKOFF_S)
        assert resp is not None
        try:
            return _parse_user_data(resp.content)
        except AnyListError:
            raise
        except Exception as exc:  # noqa: BLE001 — a decode failure is still an AnyListError
            logger.error(
                "Could not parse the AnyList user-data response (%d bytes): %s: %s",
                len(resp.content), type(exc).__name__, exc, exc_info=True,
            )
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
            # Reported to the caller as a status, never raised — so nothing else would log it.
            logger.error("AnyList auth check failed: %s: %s", type(exc).__name__, exc)
            return AuthStatus(False, str(exc), utcnow())

    # -- writes --
    def add_or_increment_items(
        self,
        list_name: str,
        items: list[PushItem],
        on_item=None,
        on_stage=None,
        push_id: str | None = None,
    ) -> PushResult:
        """Make every wanted line be on the list, uncrossed, with the wanted quantity/note — then
        PROVE it with a fresh read of the list (spike finding #3: a 200 never means an op landed).

        What is sent per line is decided by ``_decide`` from a fresh read taken at the top of
        this call (so a stale id from an earlier page load is harmless). The write mechanisms
        are exactly the ones the spike proved — one op per POST, ADD for anything new or
        re-created, ``set-list-item-quantity`` only for a bare-count change, remove-then-add for
        everything else (including un-crossing). See ``docs/anylist-push.md`` for the table of
        what was learned and which test pins each rule.

        ``on_item(ref, status)`` is called ``"active"`` right before a line's op(s) and
        ``"done"`` / ``"failed"`` right after they were sent (sent, not yet confirmed);
        ``on_stage(stage)`` with ``"sending"`` then ``"confirming"``. Both are optional and keep
        this class free of any progress-tracker import (docs/code-architecture.md > Code Architecture).

        One failing line never aborts the batch: its error is recorded against it and the next
        line is attempted (a circuit breaker stops after ``_MAX_CONSECUTIVE_FAILURES`` in a row
        so an outage doesn't take minutes of timeouts). Nothing here raises for a per-line
        problem; only the initial list read can raise ``AnyListError``.
        """
        tag = f"AnyList push {push_id}" if push_id else "AnyList push"
        t0 = time.monotonic()
        target = self._resolve_list(list_name)
        before = {i.identifier: i for i in target.items}
        result = PushResult(push_id=push_id)
        result.timings["read"] = round(time.monotonic() - t0, 2)
        logger.info(
            "%s: list=%r read: %d item(s) (%d active, %d crossed off); %d line(s) to push",
            tag, list_name, len(before),
            sum(1 for i in before.values() if not i.checked),
            sum(1 for i in before.values() if i.checked), len(items),
        )

        raw_responses: list[str] = []

        def _post_one(op: bytes, what: str) -> None:
            started = time.monotonic()
            resp = self._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            )
            raw_responses.append(f"HTTP {resp.status_code}")
            logger.info(
                "%s: sent %s -> HTTP %s in %dms", tag, what, resp.status_code,
                int((time.monotonic() - started) * 1000),
            )

        def _notify(ref: str, status: str) -> None:
            if on_item:
                on_item(ref, status)

        def _stage(stage: str) -> None:
            if on_stage:
                on_stage(stage)

        planned: list[_PlannedOp] = []
        send_started = time.monotonic()
        _stage("sending")
        consecutive_failures = 0
        for given in items:
            _notify(given.ref, "active")
            it = _resolve_existing(given, before)
            if it.existing_id != given.existing_id:
                logger.info(
                    "%s: %r — caller's id %r %s; using exact-name match %r",
                    tag, it.name, given.existing_id,
                    "is not on the list" if given.existing_id else "was empty", it.existing_id,
                )
            old = before.get(it.existing_id) if it.existing_id else None
            decision = _decide(it, before)
            logger.info(
                "%s: plan %r [%s] -> %s (%s); on list: %s; wants qty=%r note=%s",
                tag, it.name, it.ref, decision.kind, decision.reason,
                f"id={old.identifier} qty={old.quantity!r} checked={bool(old.checked)}" if old else "no",
                it.quantity, "yes" if it.note else "no",
            )
            p = _PlannedOp(item=it, kind=decision.kind, intended=decision.outcome)
            planned.append(p)
            if decision.kind == "noop":
                p.ident = it.existing_id
                p.expected_qty = it.quantity
                _notify(it.ref, "done")
                continue
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                p.not_sent = True
                p.errors.append(
                    f"not sent — AnyList kept failing ({consecutive_failures} errors in a row)"
                )
                _notify(it.ref, "failed")
                continue
            self._build_write(p, decision, target.identifier, it, old)
            try:
                if p.rebuild_remove is not None:
                    _post_one(p.rebuild_remove(), f"remove {it.name!r} id={p.old_ident}")
                for label, build in p.steps:
                    _post_one(build(), f"{label} {it.name!r} id={p.ident} qty={it.quantity!r}")
                consecutive_failures = 0
                _notify(it.ref, "done")
            except AnyListError as exc:
                consecutive_failures += 1
                p.errors.append(str(exc))
                logger.error("%s: send failed for %r — %s", tag, it.name, exc)
                _notify(it.ref, "failed")
        result.timings["send"] = round(time.monotonic() - send_started, 2)

        confirm_started = time.monotonic()
        _stage("confirming")
        after_items, reasons = self._verify(list_name, planned)
        # A read that merely lagged behind the write (stale read) shouldn't cost a re-send, so
        # each round first waits and RE-READS; only lines still wrong afterwards are re-sent.
        # Re-sends reuse the same new id (ADD is a silent no-op once the id exists), and a
        # replace whose old item survived gets its remove re-sent too. If the list can't be read
        # back at all (`after_items is None`), re-sending blind would only risk duplicates: every
        # line is reported "could not confirm" instead.
        for attempt in range(_MAX_RETRIES):
            if after_items is None:
                break
            outstanding = [p for p in planned if id(p) in reasons and p.kind != "noop"]
            if not outstanding:
                break
            logger.warning(
                "%s: read-back round %d/%d — %d line(s) not as wanted: %s", tag, attempt + 1,
                _MAX_RETRIES, len(outstanding),
                {p.item.name: reasons[id(p)] for p in outstanding},
            )
            time.sleep(_RETRY_BACKOFF_S)
            after_items, reasons = self._verify(list_name, planned)  # maybe it just lagged
            if after_items is None:
                break
            for p in [p for p in outstanding if id(p) in reasons]:
                p.retries += 1
                result.retried.append(p.item.name)
                try:
                    if p.rebuild_remove is not None and p.old_ident in {i.identifier for i in after_items or []}:
                        _post_one(p.rebuild_remove(), f"RETRY remove {p.item.name!r} id={p.old_ident}")
                        if attempt >= 1 and p.rebuild_cross_off_old is not None:
                            logger.warning(
                                "%s: the old %r (id=%s) will not go away — crossing it off instead "
                                "so it is not an active duplicate", tag, p.item.name, p.old_ident,
                            )
                            _post_one(p.rebuild_cross_off_old(), f"cross off old {p.item.name!r} id={p.old_ident}")
                    for label, build in p.steps:
                        _post_one(build(), f"RETRY {label} {p.item.name!r} id={p.ident}")
                except AnyListError as exc:
                    p.errors.append(str(exc))
                    logger.error("%s: retry send failed for %r — %s", tag, p.item.name, exc)
            after_items, reasons = self._verify(list_name, planned)
        result.timings["confirm"] = round(time.monotonic() - confirm_started, 2)

        result.after_items = after_items or []
        result.raw_response = "; ".join(raw_responses) if raw_responses else None
        for p in planned:
            reason = reasons.get(id(p))
            if reason is not None and p.errors:
                reason = f"{reason} (last send error: {p.errors[-1]})"
            elif reason is None and p.not_sent:
                reason = p.errors[-1]
            outcome = OUTCOME_FAILED if reason is not None else p.intended
            result.items.append(PushItemResult(
                key=p.item.ref, name=p.item.name, outcome=outcome, intended=p.intended,
                reason=reason, ident=p.ident if reason is None else None, retries=p.retries,
            ))
            if reason is None and p.ident and p.kind in ("add", "replace"):
                result.added_ids[p.item.ref] = p.ident  # a NEW id (in-place updates keep theirs)
        result.discrepancies = [f"{r.name} — {r.reason}" for r in result.items if not r.ok]
        result.confirmed = not result.discrepancies
        logger.info(
            "%s: read-back done: %d added, %d updated (%d un-crossed), %d already active, %d failed",
            tag, len(result.added), len(result.updated), len(result.uncrossed),
            len(result.already_active), len(result.failed),
        )
        if not result.confirmed:
            logger.error("%s: NOT fully confirmed — %s", tag, result.discrepancies)
        return result

    def _build_write(
        self, p: _PlannedOp, decision: _Decision, list_id: str, it: PushItem,
        old: AnyListItem | None = None,
    ) -> None:
        """Fill in a planned op's ids, expectations and (re-sendable) op builders. A replace
        re-creates the item, so when this push has no note of its own the OLD note is carried
        across - whatever a household member wrote on the item must survive a quantity change."""

        def set_quantity() -> bytes:
            return _build_operation(
                handler_id="set-list-item-quantity", list_id=list_id,
                list_item_id=it.existing_id, updated_value=it.quantity or "",
            )

        def uncheck() -> bytes:
            # The reference client's shape: 'n', no item message (spike/anylist_checked_toggle_test.py).
            return _build_operation(
                handler_id="set-list-item-checked", list_id=list_id,
                list_item_id=it.existing_id, updated_value="n",
            )

        if decision.kind in ("update", "uncross", "uncross_update"):
            p.ident = it.existing_id
            p.expected_qty = it.quantity
            if decision.kind != "update":
                p.steps.append(("uncheck", uncheck))
            if decision.kind != "uncross":
                p.steps.append(("set-quantity", set_quantity))
            return
        new_id = uuid.uuid4().hex
        note = it.note if it.note is not None or old is None else old.note
        p.ident = new_id
        p.expected_qty = it.quantity
        p.expected_note = note
        p.check_note = True
        p.check_name = True
        p.steps.append((
            "add",
            lambda: _build_operation(
                handler_id="add-shopping-list-item", list_id=list_id, list_item_id=new_id,
                item_wire=_item_to_wire(
                    identifier=new_id, list_id=list_id, name=it.name,
                    quantity=it.quantity, details=note, checked=False,
                ),
            ),
        ))
        if decision.kind == "replace":
            p.old_ident = it.existing_id
            # The remove must embed the item message or the server silently ignores it (phase-5
            # Chunk 5.7). Name/quantity in the embed are not compared by the server.
            p.rebuild_remove = lambda: _build_operation(
                handler_id="remove-shopping-list-item", list_id=list_id,
                list_item_id=it.existing_id,
                item_wire=_item_to_wire(
                    identifier=it.existing_id, list_id=list_id, name=it.name, quantity=None,
                ),
            )
            p.rebuild_cross_off_old = lambda: _build_operation(
                handler_id="set-list-item-checked", list_id=list_id,
                list_item_id=it.existing_id, updated_value="y",
            )

    def _read_back(self, list_name: str) -> list[AnyListItem]:
        """A fresh read of the list for confirming a push (the read itself is retried inside
        `_get_lists`; raises AnyListError only after every attempt failed)."""
        return list(self._resolve_list(list_name).items)

    def _verify(
        self, list_name: str, planned: list[_PlannedOp]
    ) -> tuple[list[AnyListItem] | None, dict[int, str]]:
        """One fresh read of the list; (the items, {id(planned op): reason}) for every planned
        op whose line is NOT now on the list uncrossed with the wanted quantity/note/name.
        If the list cannot be read back at all the items are None and EVERY sent line is
        reported as unconfirmed (never silently assumed fine)."""
        try:
            after_items = self._read_back(list_name)
        except AnyListError as exc:
            msg = f"could not confirm — reading the list back failed ({exc})"
            return None, {id(p): msg for p in planned if not p.not_sent}
        return after_items, _verify_against(after_items, planned)


def _verify_against(after_items: list[AnyListItem], planned: list[_PlannedOp]) -> dict[int, str]:
    """The read-back check, as a pure function over a snapshot (shared with the tests and the
    in-memory fake). Returns {id(op): human-readable reason} for ops that are NOT satisfied."""
    by_id = {i.identifier: i for i in after_items}
    bad: dict[int, str] = {}
    for p in planned:
        if p.not_sent:
            continue
        got = by_id.get(p.ident or "")
        if got is None:
            bad[id(p)] = "not on the list after sending"
        elif got.checked:
            bad[id(p)] = "still crossed off on the list"
        elif not _same_qty(got.quantity, p.expected_qty):
            bad[id(p)] = f"quantity shows {got.quantity!r}, expected {p.expected_qty!r}"
        elif p.check_note and (got.note or "").strip() != (p.expected_note or "").strip():
            bad[id(p)] = f"note shows {got.note!r}, expected {p.expected_note!r}"
        elif p.check_name and (got.name or "").strip() != p.item.name.strip():
            bad[id(p)] = f"name shows {got.name!r}, expected {p.item.name!r}"
        elif p.old_ident and p.old_ident in by_id and not by_id[p.old_ident].checked:
            bad[id(p)] = "the old item is still on the list too (duplicate)"
    return bad


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

    def add_or_increment_items(
        self, list_name: str, items: list[PushItem], on_item=None, on_stage=None,
        push_id: str | None = None,
    ) -> PushResult:
        # Mirrors the REAL connector's decisions (it shares `_decide`) and its confirmed write
        # behaviour, not an idealised one: a bare-count change updates in place (note untouched);
        # everything else removes the old item and re-adds it under a new id, uncrossed — which
        # is also how a crossed-off item is un-crossed. Reads back through the same pure
        # `_verify_against` the real client uses, so fake mode exercises the same result shapes.
        # It never fails or lags, so only the happy path is modelled here; failure behaviour is
        # covered against the real client with a fault-injecting fake server (tests/services/
        # test_anylist_push_faults.py).
        lst = self._list(list_name)
        result = PushResult(push_id=push_id)
        if on_stage:
            on_stage("sending")
        planned: list[_PlannedOp] = []
        for it in items:
            if on_item:
                on_item(it.ref, "active")
            decision = _decide(it, {i.identifier: i for i in lst.values()})
            p = _PlannedOp(item=it, kind=decision.kind, intended=decision.outcome)
            planned.append(p)
            if decision.kind == "noop":
                p.ident, p.expected_qty = it.existing_id, it.quantity
            elif decision.kind in ("update", "uncross", "uncross_update"):
                old = lst[it.existing_id]
                qty = it.quantity if decision.kind != "uncross" else old.quantity
                lst[it.existing_id] = AnyListItem(old.identifier, old.name, qty, False, old.note)
                p.ident, p.expected_qty = it.existing_id, it.quantity
            else:
                old_item = lst.get(it.existing_id) if it.existing_id else None
                if decision.kind == "replace":
                    p.old_ident = it.existing_id
                    del lst[it.existing_id]
                new_id = f"fake-{uuid.uuid4().hex[:8]}"
                carried = it.note if it.note is not None or old_item is None else old_item.note
                lst[new_id] = AnyListItem(new_id, it.name, it.quantity, False, carried)
                p.ident, p.expected_qty, p.expected_note = new_id, it.quantity, carried
                p.check_note = p.check_name = True
            if on_item:
                on_item(it.ref, "done")
        if on_stage:
            on_stage("confirming")
        reasons = _verify_against(list(lst.values()), planned)
        for p in planned:
            reason = reasons.get(id(p))
            result.items.append(PushItemResult(
                key=p.item.ref, name=p.item.name,
                outcome=OUTCOME_FAILED if reason else p.intended, intended=p.intended,
                reason=reason, ident=None if reason else p.ident,
            ))
            if not reason and p.ident and p.kind in ("add", "replace"):
                result.added_ids[p.item.ref] = p.ident
        result.after_items = list(lst.values())
        result.discrepancies = [f"{r.name} — {r.reason}" for r in result.items if not r.ok]
        result.confirmed = not result.discrepancies
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
    client that requires settings.anylist_enabled. Cached — a real client keeps its token across
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
    items: list[PushItem], *, list_name: str | None = None, on_item=None, on_stage=None,
    push_id: str | None = None,
) -> PushResult:
    """Make every wanted line be on the list, uncrossed, with the wanted quantity/note, and
    confirm it by reading the list back. See ``docs/anylist-push.md`` and docs/anylist-push.md > AnyList
    Push Logic.

    `on_item(ref, status)` / `on_stage(stage)` — see `_RealAnyList.add_or_increment_items`'s
    docstring — are forwarded straight through to whichever client is active (real or fake);
    this module-level function itself has no progress-tracking logic of its own, same "small
    stable interface" discipline as the rest of this file. `push_id` only tags log lines."""
    name = list_name or settings.anylist_target_list_name
    result = _get_client().add_or_increment_items(
        name, items, on_item=on_item, on_stage=on_stage, push_id=push_id
    )
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
        return AuthStatus(False, str(exc), utcnow())  # the AnyList enable switch being off is working as designed
    except AnyListError as exc:
        # e.g. credentials not configured — _get_client() raises before the connector can log.
        logger.error("AnyList auth check failed: %s: %s", type(exc).__name__, exc)
        return AuthStatus(False, str(exc), utcnow())
