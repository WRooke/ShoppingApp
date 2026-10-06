"""Chunk 6.7 follow-up (2026-10-07): live check of the NAMING change on TestList only. Three real
pushes through checklist.push_to_anylist, each followed by an independent read of the list:

  N1  fresh add of tricky names     household wording ("black beans", "salt", "vegetable oil"), an
                                    "or" name, an apostrophe, a digit-led name -> the exact names
                                    that land on AnyList (title case: "Cheddar Cheese or Monterey Jack",
                                    "Baker's Chocolate", "2% Milk")
  N2  immediate re-push             nothing changed -> every line already-active, ZERO writes, no
                                    duplicates (proves the pushed names match their own rows)
  N3  old spellings on the list     "Salts", "Vegetable Oils", "Black Bean" (what the old display logic
                                    left behind) put there with raw ADDs -> found through the key, not
                                    duplicated, left alone

Refuses any list other than TestList; removes everything it added. `--only-n3` runs just the third
push (one live push instead of three).

    ANYLIST_ENABLED=true ANYLIST_FAKE_MODE=false ANYLIST_TARGET_LIST_NAME=TestList \\
        .venv/Scripts/python -m spike.anylist_push_live_names_test
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
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import anylist_client as ac
from app.services import checklist as cl
from app.services import sessions as sessions_service
from spike.anylist_checked_toggle_test import add_item, list_id_of
from spike.anylist_push_live_test import (
    PROBLEMS, _cleanup, _report, check_invariants, mark_all_need, push, recipe, show, snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("names_live")

TRICKY = [
    {"name": "black beans", "quantity": 800, "unit": "g"},
    {"name": "salt", "quantity": 2, "unit": "tsp"},
    {"name": "vegetable oil", "quantity": 4, "unit": "tbsp"},
    {"name": "cheddar cheese or monterey jack", "quantity": 200, "unit": "g"},
    {"name": "baker's chocolate", "quantity": 100, "unit": "g"},
    {"name": "2% milk", "quantity": 1, "unit": "l"},
]
EXPECT = {"Black Beans", "Salt", "Vegetable Oil", "Cheddar Cheese or Monterey Jack", "Baker's Chocolate", "2% Milk"}


def new_session(db, ings, name):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = recipe(db, name, ings)
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    cl.load_checklist(db, s.id)
    mark_all_need(db, s.id)
    return s


def main() -> int:
    only_n3 = "--only-n3" in sys.argv
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

    tmp = Path(tempfile.mkdtemp(prefix="names_live_"))
    engine = create_engine(f"sqlite:///{tmp / 'live.db'}", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        if not only_n3:
            s = new_session(db, TRICKY, "Names A")
            res1 = push(db, s.id, "N1 fresh add, tricky names", "tok-n1")
            landed = {i.name for i in show("after N1") if i.identifier not in baseline_ids}
            if landed != EXPECT:
                PROBLEMS.append(f"N1: names on the list {sorted(landed)} != expected {sorted(EXPECT)}")
            check_invariants(db, s.id, "N1")
            if not all(i["outcome"] == "added" for i in res1["items"]):
                PROBLEMS.append(f"N1: expected all added, got {[(i['name'], i['outcome']) for i in res1['items']]}")

            cl.load_checklist(db, s.id)  # as the screen would after a push
            before = len(snapshot())
            res2 = push(db, s.id, "N2 immediate re-push", "tok-n2")
            if any(i["outcome"] != "already-active" for i in res2["items"]):
                PROBLEMS.append(f"N2: expected all already-active, got {[(i['name'], i['outcome']) for i in res2['items']]}")
            if len(snapshot()) != before:
                PROBLEMS.append("N2: the number of items on the list changed on a no-change re-push")
            check_invariants(db, s.id, "N2")
            # N3 must start from an empty list: the old spellings are seeded NEXT, and leaving N1's
            # items there would make duplicates of our own making (found on the first live run).
            _cleanup(client, list_id, baseline_ids)

        # N3: the old display logic's spellings, put on the list by raw ADD, matched through the key
        old = {n: add_item(client, list_id, n, q, None) for n, q in (("Salts", "2 tsp"), ("Vegetable Oils", "4 tbsp"), ("Black Bean", "800 g"))}
        time.sleep(0.6)
        s3 = new_session(db, [{"name": "black beans", "quantity": 800, "unit": "g"},
                              {"name": "salt", "quantity": 2, "unit": "tsp"},
                              {"name": "vegetable oil", "quantity": 4, "unit": "tbsp"}], "Names B")
        items, _ok, _d, _b = cl.load_checklist(db, s3.id)
        if not all(i.already_on_anylist for i in items):
            PROBLEMS.append("N3: an old-spelling item was not recognised as already on the list")
        res3 = push(db, s3.id, "N3 old spellings already on the list", "tok-n3")
        for i in res3["items"]:
            if i["outcome"] not in ("already-active", "updated"):
                PROBLEMS.append(f"N3: unexpected outcome {i['name']} -> {i['outcome']}")
        now = snapshot()
        for n in ("salt", "vegetable oil", "black bean"):
            if sum(1 for i in now if cl._names_match(n, i.name) and not i.checked) != 1:
                PROBLEMS.append(f"N3: {n!r} is not on the list exactly once (a duplicate or a loss)")
        show("after N3")
    finally:
        db.close()
        engine.dispose()
        _cleanup(client, list_id, baseline_ids)
    return _report()


if __name__ == "__main__":
    sys.exit(main())
