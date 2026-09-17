"""AnyList fault-finding spike (2026-09-18) — comprehensive live probe against TestList.

Throwaway script. NOT wired into the app — do not import this from app/.

The household reported two symptoms when pushing the checklist to AnyList: notes rarely land,
and a quantity that AnyList clearly HAS (the item-detail "+" jumps from the true value, not
zero) shows as "Not set" in AnyList's own list view. `docs/build-status/
anylist-fault-finding-spike.md` has the full write-up and root-cause analysis this script's
output feeds into — read that first for context.

Unlike `anylist_spike.py` (the original Phase 1.5 derisking spike, which hand-rolled its own
tiny protobuf codec because the production connector didn't exist yet), this script imports
`app.services.anylist_client` / `anylist_wire` directly, so every probe below exercises the
REAL production code path — not a reimplementation that could silently diverge from it. A few
probes reach past the connector's public functions into its private helpers (`_get_client()`,
`_data_post`, the wire builders) specifically to inspect raw protobuf field presence (does field
21 exist at all after an update?) that the connector's own public API deliberately hides behind
its 21-preferred/18-fallback merge — that merge is exactly the mechanism under investigation.

Every probe item this script creates is named with an `FF-` prefix so a run is trivially
identifiable and safe to distinguish from anything already on TestList. Probe 10 removes them
all again at the end via the wire-level `remove-shopping-list-item` handler (present in the
original Phase 1.5 spike's `remove_item()`, never carried into the production connector — see
the findings doc for that gap).

Always targets `settings.anylist_target_list_name` (TestList per `.env` — this script never
overrides it, and does not touch any other list). Reads `ANYLIST_EMAIL`/`ANYLIST_PASSWORD` the
same way the app does (`app.config.settings`) — never hardcoded, never printed.

Usage:
    .venv\\Scripts\\python.exe -m spike.anylist_fault_finding_probe
"""

from __future__ import annotations

import logging
import sys
import time
import uuid

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem
from app.services.anylist_wire import (
    _b,
    _build_operation,
    _build_operation_list,
    _decode_message,
    _field_message,
    _field_string,
    _item_to_wire,
    _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("anylist_fault_finding_probe")

PREFIX = "FF-"
FINDINGS: list[dict] = []


def record(probe: str, verdict: str, evidence: str) -> None:
    FINDINGS.append({"probe": probe, "verdict": verdict, "evidence": evidence})
    logger.info("[%s] %s — %s", probe, verdict, evidence)


# --- raw wire access (bypasses the connector's own 21/18 merge on purpose) -----------------


def raw_dump() -> tuple[str, dict[str, dict]]:
    """(list_id, {item_id: raw_field_dict}) for the target list, straight off the wire — no
    merging. Reaches past the public API deliberately: this is the one piece of ground truth
    the connector's own `get_items()` can never show, because it always returns the merged
    value."""
    client = ac._get_client()
    resp = client._data_post("/data/user-data/get")
    top = _decode_message(resp.content)
    inner = _decode_message(top[1][0])
    for raw_list in inner.get(1, []):
        lst = _decode_message(raw_list)
        if (_s(lst, 3) or "").strip() == settings.anylist_target_list_name.strip():
            list_id = _s(lst, 1) or ""
            items = {}
            for raw_item in lst.get(4, []):
                f = _decode_message(raw_item)
                items[_s(f, 1) or ""] = f
            return list_id, items
    raise RuntimeError(f"target list {settings.anylist_target_list_name!r} not found")


def describe(f: dict) -> str:
    has21 = 21 in f
    v21 = _s(_decode_message(f[21][0]), 1) if has21 else None
    v18 = _s(f, 18)
    return (
        f"name={_s(f, 4)!r} f21_present={has21} f21_value={v21!r} f18_value={v18!r} "
        f"note={_s(f, 5)!r} checked={_b(f, 6)!r}"
    )


def by_name(items: dict[str, dict], name: str) -> tuple[str, dict]:
    for ident, f in items.items():
        if _s(f, 4) == name:
            return ident, f
    raise KeyError(name)


# --- probes ---------------------------------------------------------------------------------


def probe_1_connectivity() -> dict[str, dict]:
    status = ac.check_auth()
    record("1-connectivity", "OK" if status.ok else "FAILED", status.detail)
    if not status.ok:
        raise SystemExit(1)
    list_id, items = raw_dump()
    logger.info("Baseline: %d item(s) already on %s (list_id=%s)", len(items), settings.anylist_target_list_name, list_id)
    for f in items.values():
        logger.info("  baseline item: %s", describe(f))
    return items


def probe_2_fresh_add_matrix() -> None:
    long_note = "x" * 520 + " (long-note probe)"
    matrix = [
        PushItem(name=f"{PREFIX}int-qty", quantity="3"),
        PushItem(name=f"{PREFIX}unit-qty", quantity="1050 g"),
        PushItem(name=f"{PREFIX}decimal-qty", quantity="1.5 kg"),
        PushItem(name=f"{PREFIX}qty-and-note", quantity="400 g", note="pack breakdown note"),
        PushItem(name=f"{PREFIX}note-only", quantity=None, note="note only, no quantity"),
        PushItem(name=f"{PREFIX}bare-name", quantity=None, note=None),
        PushItem(name=f"{PREFIX}unicode", quantity="2", note="à la crème, Crème Fraîche"),
        PushItem(name=f"{PREFIX}long-note", quantity="1", note=long_note),
        PushItem(name=f"{PREFIX}punctuation (small tin)", quantity="1", note=None),
    ]
    res = ac.add_or_increment_items(matrix)
    record(
        "2-fresh-add-matrix",
        "confirmed" if res.confirmed else "NOT CONFIRMED",
        f"added={res.added} discrepancies={res.discrepancies}",
    )
    _, items = raw_dump()
    for p in matrix:
        try:
            _, f = by_name(items, p.name)
            record("2-fresh-add-matrix/" + p.name, "OK", describe(f))
        except KeyError:
            record("2-fresh-add-matrix/" + p.name, "MISSING", "item not found after add")


def probe_3_update_matrix() -> None:
    _, items = raw_dump()
    updates = [
        (f"{PREFIX}unit-qty", "1200 g", None),
        (f"{PREFIX}qty-and-note", "500 g", "attempted new note on update"),
        (f"{PREFIX}unicode", "5", "attempted new unicode note: crème brûlée"),
    ]
    for name, new_qty, new_note in updates:
        ident, before = by_name(items, name)
        push_items = [PushItem(name=name, quantity=new_qty, existing_id=ident, note=new_note)]
        res = ac.add_or_increment_items(push_items)
        _, after_items = raw_dump()
        after = after_items[ident]
        field21_survived = 21 in after
        note_updated = _s(after, 5) != _s(before, 5) and new_note is not None
        record(
            f"3-update/{name}",
            f"field21_survived={field21_survived} note_updated={note_updated}",
            f"before=[{describe(before)}] after=[{describe(after)}] confirmed={res.confirmed}",
        )


def probe_4_checked_state() -> None:
    """Best-effort: this app's connector never writes a checked-state op, so there's no
    confirmed way to flip it from Python alone. Attempts the `set-list-item-checked` handler
    (a guess, by analogy with `set-list-item-quantity`/`set-list-item-details` — both real,
    both following the same "set-list-item-X" single-field-update naming convention used
    throughout the reference client) and reports whether it actually worked; if not, this is
    exactly the kind of thing that needs a human glance at the phone app — flagged for the
    final visual-confirmation round rather than guessed at further."""
    list_id, items = raw_dump()
    ident, before = by_name(items, f"{PREFIX}int-qty")
    client = ac._get_client()
    op = _build_operation(
        handler_id="set-list-item-checked", list_id=list_id, list_item_id=ident, updated_value="1"
    )
    try:
        resp = client._data_post(
            "/data/shopping-lists/update",
            files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
        )
        _, after_items = raw_dump()
        after = after_items[ident]
        worked = _b(after, 6) is True and _b(before, 6) is not True
        record(
            "4-checked-state",
            "guessed-handler-worked" if worked else "guessed-handler-INCONCLUSIVE",
            f"http={resp.status_code} before_checked={_b(before, 6)!r} after_checked={_b(after, 6)!r} "
            "— needs a manual phone-app check if inconclusive",
        )
        # push a normal quantity update over the same item and see if checked survives
        res = ac.add_or_increment_items([PushItem(name=f"{PREFIX}int-qty", quantity="9", existing_id=ident)])
        _, final_items = raw_dump()
        final = final_items[ident]
        record(
            "4-checked-state/survives-quantity-update",
            f"checked_after_update={_b(final, 6)!r}",
            f"confirmed={res.confirmed}",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort probe, log and move on
        record("4-checked-state", "EXCEPTION", repr(exc))


def probe_5_confirm_diff_robustness() -> None:
    list_id, items = raw_dump()
    id_a, _ = by_name(items, f"{PREFIX}decimal-qty")
    id_b, _ = by_name(items, f"{PREFIX}note-only")
    op_a = _build_operation(handler_id="set-list-item-quantity", list_id=list_id, list_item_id=id_a, updated_value="7.5 kg")
    op_b = _build_operation(handler_id="set-list-item-quantity", list_id=list_id, list_item_id=id_b, updated_value="7")
    client = ac._get_client()
    resp = client._data_post(
        "/data/shopping-lists/update",
        files={"operations": (None, _build_operation_list([op_a, op_b]), "application/octet-stream")},
    )
    _, after = raw_dump()
    a_landed = _s(after[id_a], 18) == "7.5 kg" or (21 in after[id_a] and _s(_decode_message(after[id_a][21][0]), 1) == "7.5 kg")
    b_landed = _s(after[id_b], 18) == "7"
    record(
        "5-confirm-diff-robustness",
        f"http={resp.status_code} a_landed={a_landed} b_landed={b_landed}",
        "spike/FINDINGS.md (2026-09-12) found the SECOND op in a multi-item batch is silently "
        "dropped — expect a_landed=True, b_landed=False if that still holds today",
    )


def probe_6_empty_quantity_update() -> None:
    _, items = raw_dump()
    ident, before = by_name(items, f"{PREFIX}bare-name")
    res = ac.add_or_increment_items([PushItem(name=f"{PREFIX}bare-name", quantity=None, existing_id=ident)])
    _, after_items = raw_dump()
    after = after_items[ident]
    record(
        "6-empty-quantity-update",
        f"confirmed={res.confirmed}",
        f"before=[{describe(before)}] after=[{describe(after)}]",
    )


def probe_7_name_matching_live() -> None:
    from app.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    ac.add_or_increment_items([PushItem(name=f"{PREFIX}Tomatoes", quantity="4")])
    ac.add_or_increment_items([PushItem(name=f"{PREFIX}Cherry Tomatoes", quantity="1 punnet")])

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
        from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
        from app.services import checklist as checklist_service
        from app.services import recipes as recipes_service
        from app.services import sessions as sessions_service

        r = recipes_service.create_recipe(
            db,
            RecipeCreate(
                name="FF probe recipe", source_type="manual", base_servings=1,
                ingredients=[RecipeIngredientCreate(name=f"{PREFIX.lower()}tomato", quantity=2, unit=None)],
            ),
            allow_duplicate=True,
        )
        s = sessions_service.create_session(db, PlanningSessionCreate())
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=1))
        sessions_service.consolidate_session(db, s.id)
        checklist_service.load_checklist(db, s.id)
        row = next(c for c in s.checklist_items if c.ingredient_name == f"{PREFIX.lower()}tomato")
        record(
            "7-name-matching-live",
            f"already_on_anylist={row.already_on_anylist}",
            f"matched anylist_item_id={row.anylist_item_id!r} — should match '{PREFIX}Tomatoes' "
            f"(plural->singular fuzzy), must NOT match '{PREFIX}Cherry Tomatoes'",
        )
    finally:
        db.close()
        engine.dispose()


def probe_8_full_round_trip() -> None:
    from app.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
        from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
        from app.services import checklist as checklist_service
        from app.services import recipes as recipes_service
        from app.services import sessions as sessions_service

        r = recipes_service.create_recipe(
            db,
            RecipeCreate(
                name="FF round-trip recipe", source_type="manual", base_servings=1,
                ingredients=[
                    RecipeIngredientCreate(name=f"{PREFIX.lower()}roundtrip-new", quantity=2, unit="kg"),
                    RecipeIngredientCreate(name=f"{PREFIX.lower()}int-qty", quantity=5, unit=None),
                ],
            ),
            allow_duplicate=True,
        )
        s = sessions_service.create_session(db, PlanningSessionCreate())
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=1))
        sessions_service.consolidate_session(db, s.id)
        checklist_service.load_checklist(db, s.id)
        for c in s.checklist_items:
            checklist_service.update_item(db, s.id, c.id, have_it="no")

        first = checklist_service.push_to_anylist(db, s.id)
        second = checklist_service.push_to_anylist(db, s.id, force=True)
        _, items = raw_dump()
        # push_to_anylist titles the ingredient name (ci.ingredient_name.title()) -- match the
        # same transformation rather than assuming a capitalisation.
        expected_name = f"{PREFIX.lower()}roundtrip-new".title()
        matches = [ident for ident, f in items.items() if _s(f, 4) == expected_name]
        record(
            "8-full-round-trip",
            f"first_confirmed={first['confirmed']} second_confirmed={second['confirmed']} "
            f"no_duplicate={len(matches) <= 1}",
            f"first={first['added']}/{first['updated']} second={second['added']}/{second['updated']} "
            f"matches_on_list={len(matches)}",
        )
    finally:
        db.close()
        engine.dispose()


def probe_9_usuals() -> None:
    ac.add_or_increment_items([PushItem(name=f"{PREFIX}usual-item", quantity=None)])
    _, items = raw_dump()
    _, f = by_name(items, f"{PREFIX}usual-item")
    record("9-usuals", "OK", describe(f))


def probe_10_cleanup() -> None:
    list_id, items = raw_dump()
    client = ac._get_client()
    removed, failed = [], []
    for ident, f in items.items():
        name = _s(f, 4) or ""
        # case-insensitive: push_to_anylist (probe 8) titles the name ("Ff-..."), everything
        # else in this script uses the literal "FF-" prefix.
        if not name.upper().startswith(PREFIX.upper()):
            continue
        item_wire = _item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None)
        op = _build_operation(
            handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident, item_wire=item_wire,
        )
        try:
            client._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            )
            removed.append(name)
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            failed.append((name, repr(exc)))
        time.sleep(0.2)  # be polite — no batching, sequential like the rest of the connector
    _, remaining = raw_dump()
    still_there = [n for n in (_s(f, 4) for f in remaining.values()) if n and n.upper().startswith(PREFIX.upper())]
    record(
        "10-cleanup",
        "clean" if not still_there else "LEFTOVER ITEMS",
        f"removed={removed} failed={failed} still_on_list={still_there}",
    )


def main() -> int:
    if settings.anylist_target_list_name.strip() != "TestList":
        logger.error(
            "Refusing to run: ANYLIST_TARGET_LIST_NAME is %r, not TestList. This spike must "
            "only ever touch TestList.",
            settings.anylist_target_list_name,
        )
        return 1
    if settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: needs ANYLIST_ENABLED=true and ANYLIST_FAKE_MODE=false.")
        return 1

    logger.info("=== AnyList fault-finding probe starting against %s ===", settings.anylist_target_list_name)
    probes = [
        probe_1_connectivity,
        probe_2_fresh_add_matrix,
        probe_3_update_matrix,
        probe_4_checked_state,
        probe_5_confirm_diff_robustness,
        probe_6_empty_quantity_update,
        probe_7_name_matching_live,
        probe_8_full_round_trip,
        probe_9_usuals,
        probe_10_cleanup,
    ]
    for p in probes:
        logger.info("--- running %s ---", p.__name__)
        try:
            p()
        except Exception:
            logger.error("%s raised — continuing with the rest of the probes", p.__name__, exc_info=True)
        time.sleep(0.3)  # avoid hammering AnyList's server back-to-back

    logger.info("=== SUMMARY ===")
    for entry in FINDINGS:
        logger.info("%-45s %-40s %s", entry["probe"], entry["verdict"], entry["evidence"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
