"""Chunk 6.7 (2026-10-06): live end-to-end check of the REAL push path (checklist.push_to_anylist ->
anylist_client) against the TestList, replacing guesswork about the dropped-items report with
evidence. Throwaway DB, TestList ONLY (refuses anything else), removes everything it added.

Five pushes, each followed by an INDEPENDENT read of the list and an invariant check ("every
Need-it row is on the list exactly once, uncrossed, with the wanted quantity"):

  P1  fresh mixed add            bare-count, unit-bearing, note-only ("to taste"), several lines
  P2  quantities change          a second recipe changes some quantities -> updates / already-active
  P3  crossed off on the "phone" three items crossed off externally -> must NOT count as on the
                                 list, must come back un-crossed (bare-count, unit-bearing, note)
  P4  deleted on the "phone"     an item removed externally between load and push (stale id)
  P5  final regression           push again, nothing changed -> everything already-active, no
                                 duplicates, nothing crossed off

Usage (live; the maintainer allowed up to 5 TestList pushes on 2026-10-06):
    ANYLIST_ENABLED=true ANYLIST_FAKE_MODE=false ANYLIST_TARGET_LIST_NAME=TestList \\
        .venv/Scripts/python -m spike.anylist_push_live_test
"""
from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import anylist_client as ac
from app.services import checklist as cl
from app.services import progress_tracker
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service
from spike.anylist_checked_toggle_test import _retry, list_id_of, post, remove_item, toggle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("push_live")

PROBLEMS: list[str] = []


def snapshot():
    return _retry(ac.get_items)


def show(title):
    items = snapshot()
    log.info("--- TestList %s: %d item(s)", title, len(items))
    for i in items:
        log.info("      %-22s qty=%-10r checked=%-5s note=%r", i.name, i.quantity, bool(i.checked), i.note)
    return items


def check_invariants(db, session_id, label):
    """Independent of the push's own claims: re-read the list and check every Need-it row."""
    rows = [r for r in sessions_service.get_session(db, session_id).checklist_items
            if r.add_to_list or r.have_it == "no"]
    items = snapshot()
    ok = True
    for r in rows:
        matches = [i for i in items if cl._names_match(r.ingredient_name, i.name)]
        active = [m for m in matches if not m.checked]
        want = cl._anylist_quantity(r)
        if len(active) != 1:
            ok = False
            PROBLEMS.append(f"{label}: {r.ingredient_name!r} has {len(active)} active item(s) (matches={len(matches)})")
            continue
        if (active[0].quantity or "").strip() != (want or "").strip():
            ok = False
            PROBLEMS.append(f"{label}: {r.ingredient_name!r} quantity {active[0].quantity!r} != wanted {want!r}")
    log.info("INVARIANTS %s: %s (%d Need-it rows)", label, "OK" if ok else "FAILED", len(rows))
    return ok


def push(db, session_id, label, token):
    log.info("=== %s: pushing", label)
    res = cl.push_to_anylist(db, session_id, force=True, progress_token=token)
    log.info("%s -> confirmed=%s added=%s updated=%s uncrossed=%s already_active=%s failed=%s",
             label, res["confirmed"], res["added"], res["updated"], res["uncrossed"],
             res["already_active"], res["failed"])
    for it in res["items"]:
        log.info("      %-22s %-15s intended=%-14s retries=%d %s", it["name"], it["outcome"],
                 it["intended"], it["retries"], it["reason"] or "")
    log.info("%s progress stage=%s timings=%s", label, progress_tracker.get_stage(token),
             {k: v for k, v in res.items() if k == "push_id"})
    if not res["confirmed"]:
        PROBLEMS.append(f"{label}: push not confirmed: {res['discrepancies']}")
    return res


def mark_all_need(db, session_id):
    for r in list(sessions_service.get_session(db, session_id).checklist_items):
        cl.update_item(db, session_id, r.id, have_it="no", add_to_list=True)


def recipe(db, name, ings):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(name=name, source_type="manual", base_servings=4,
                     ingredients=[RecipeIngredientCreate(**i) for i in ings]),
        allow_duplicate=True,
    )


def run_p4_p5(db, session_id, client, list_id):
    # P4 -----------------------------------------------------------------------------------
    victim = next(i for i in snapshot() if i.name.lower().startswith("red capsicum"))
    remove_item(client, list_id, victim.identifier, victim.name)  # deleted on the "phone"
    time.sleep(0.6)
    # deliberately NO reload: rows still carry the now-stale AnyList id
    res4 = push(db, session_id, "P4 item deleted on the list after load (stale id)", "tok-p4")
    r = next((i for i in res4["items"] if i["name"].lower().startswith("red capsicum")), None)
    if not r or r["outcome"] != "added":
        PROBLEMS.append(f"P4: expected the deleted item to be re-added, got {r and r['outcome']}")
    show("after P4")
    check_invariants(db, session_id, "P4")

    # P5 -----------------------------------------------------------------------------------
    res5 = push(db, session_id, "P5 final regression (nothing changed)", "tok-p5")
    if res5["added"] or res5["updated"] or res5["failed"]:
        PROBLEMS.append(f"P5: expected everything already-active, got added={res5['added']} "
                        f"updated={res5['updated']} failed={res5['failed']}")
    items5 = show("after P5")
    names = [i.name.lower() for i in items5]
    for n in set(names):
        if names.count(n) > 1:
            PROBLEMS.append(f"P5: duplicate {n!r} x{names.count(n)}")
    if any(i.checked for i in items5):
        PROBLEMS.append("P5: something is still crossed off")
    check_invariants(db, session_id, "P5")


def seed_list_directly(client, list_id):
    """For the P4/P5-only mode: put the post-P3 state on TestList with raw ADD ops (NOT pushes),
    so the two remaining pushes of the 5-push budget can be spent on P4 and P5."""
    from spike.anylist_checked_toggle_test import add_item
    for name, qty, note in (("Beef Mince", "750 g", None), ("Eggs", "8", None),
                            ("Olive Oil", "2 tbsp", None), ("Red Capsicums", "2", None),
                            ("Salt", None, "to taste"), ("Spring Onion", "1 bunch", None),
                            ("Milk", "1 L", None)):
        add_item(client, list_id, name, qty, note)
        time.sleep(0.3)


def main() -> int:
    only_p4_p5 = "--only-p4-p5" in sys.argv
    if (settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode
            or not settings.anylist_enabled):
        log.error("Refusing to run: target list must be TestList with ANYLIST_ENABLED=true and fake mode off.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()
    list_id = list_id_of(client)
    baseline_ids = {i.identifier for i in snapshot()}
    show("baseline")

    tmp = Path(tempfile.mkdtemp(prefix="push_live_"))
    engine = create_engine(f"sqlite:///{tmp / 'live.db'}", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        if only_p4_p5:
            seed_list_directly(client, list_id)
        r1 = recipe(db, "Live A", [
            {"name": "beef mince", "quantity": 500, "unit": "g"},
            {"name": "red capsicum", "quantity": 2, "unit": None},
            {"name": "egg", "quantity": 6, "unit": None},
            {"name": "olive oil", "quantity": 2, "unit": "tbsp"},
            {"name": "salt", "quantity": 1, "unit": "to taste"},
            {"name": "spring onion", "quantity": 1, "unit": "bunch"},
        ])
        s = sessions_service.create_session(db, PlanningSessionCreate())
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
        cl.load_checklist(db, s.id)
        mark_all_need(db, s.id)

        if only_p4_p5:
            r2 = recipe(db, "Live B", [
                {"name": "beef mince", "quantity": 250, "unit": "g"},
                {"name": "egg", "quantity": 2, "unit": None},
                {"name": "milk", "quantity": 1, "unit": "l"},
            ])
            sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
            cl.load_checklist(db, s.id)
            mark_all_need(db, s.id)
            run_p4_p5(db, s.id, client, list_id)
            return _finish(db, engine, client, list_id, baseline_ids)

        # P1 -------------------------------------------------------------------------------
        push(db, s.id, "P1 fresh add", "tok-p1")
        show("after P1")
        check_invariants(db, s.id, "P1")

        # P2 -------------------------------------------------------------------------------
        r2 = recipe(db, "Live B", [
            {"name": "beef mince", "quantity": 250, "unit": "g"},
            {"name": "egg", "quantity": 2, "unit": None},
            {"name": "milk", "quantity": 1, "unit": "l"},
        ])
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
        cl.load_checklist(db, s.id)
        mark_all_need(db, s.id)
        push(db, s.id, "P2 quantities changed + new item", "tok-p2")
        show("after P2")
        check_invariants(db, s.id, "P2")

        # P3 -------------------------------------------------------------------------------
        crossed = []
        for prefix in ("egg", "beef mince", "salt"):
            it = next((i for i in snapshot() if i.name.lower().startswith(prefix)), None)
            if it is not None:
                crossed.append(prefix)
                toggle(client, list_id, it.identifier, True, embed=False)  # the "phone" crosses it off
                time.sleep(0.4)
        show("after crossing off " + ", ".join(crossed))
        items, ok, _d, _b = cl.load_checklist(db, s.id)
        for row in items:
            if row.ingredient_name.startswith(tuple(crossed)) and row.already_on_anylist:
                PROBLEMS.append(f"P3: crossed-off {row.ingredient_name!r} still counted as on the list")
        mark_all_need(db, s.id)
        res3 = push(db, s.id, "P3 crossed-off items need re-buying", "tok-p3")
        for n in crossed:
            r = next((i for i in res3["items"] if i["name"].lower().startswith(n)), None)
            if not r or r["outcome"] != "un-crossed":
                PROBLEMS.append(f"P3: expected {n!r} un-crossed, got {r and r['outcome']}")
        show("after P3")
        check_invariants(db, s.id, "P3")

        run_p4_p5(db, s.id, client, list_id)
    finally:
        db.close()
        engine.dispose()
        _cleanup(client, list_id, baseline_ids)
    return _report()


def _cleanup(client, list_id, baseline_ids):
    for i in snapshot():
        if i.identifier not in baseline_ids:
            try:
                remove_item(client, list_id, i.identifier, i.name or "")
            except Exception as exc:  # noqa: BLE001
                log.error("cleanup failed for %s: %s", i.name, exc)
            time.sleep(0.2)
    time.sleep(0.6)
    left = {i.identifier for i in snapshot()}
    log.info("TestList restored to baseline: %s", left == baseline_ids)


def _report() -> int:
    print("\nPROBLEMS:" if PROBLEMS else "\nNO PROBLEMS FOUND")
    for p in PROBLEMS:
        print("  -", p)
    return 1 if PROBLEMS else 0


def _finish(db, engine, client, list_id, baseline_ids) -> int:
    db.close()
    engine.dispose()
    _cleanup(client, list_id, baseline_ids)
    return _report()


if __name__ == "__main__":
    sys.exit(main())
