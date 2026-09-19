"""Phase B step 6 (2026-09-20) — realistic-scale live re-validation of the "replace" fix.

The 2026-09-19 investigation (spike/anylist_reliability_investigation.py) ran the SAME ~28-item
synthetic grocery list through 10 weekly cycles against the pre-fix connector and found ~65% of
unit-bearing items entered a permanently-broken quantity state. This script re-runs the same
list and cycle count against the FIXED connector (bare counts still use set-list-item-quantity;
unit-bearing items now go through delete+re-add under a new id, preserving checked/note) and
measures the same thing: does anything come back wrong.

Throwaway, TestList only, continuing this session's standing authorization.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_replace_fix_revalidation
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import AnyListError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("replace_fix_revalidation")


def with_retry(fn, *, attempts: int = 4, label: str = ""):
    """Script-level resilience against a transient AnyList timeout (this environment hits them
    periodically) so a long run doesn't die on one slow response -- not the app-level retry
    (that's already in anylist_client.py), just keeping this investigation itself running."""
    for n in range(attempts):
        try:
            return fn()
        except AnyListError as exc:
            if n == attempts - 1:
                raise
            logger.warning("%s: attempt %d/%d failed (%s) -- retrying", label, n + 1, attempts, exc)
            time.sleep(2.0)


RX = "RV-"
DISCREPANCIES: list[dict] = []
N_CYCLES = 8

# Same list as the 2026-09-19 investigation (spike/anylist_reliability_investigation.py),
# generic grocery names, no household data.
GROCERY_ITEMS = [
    ("onion", 2, None, "core"), ("garlic", 1, "bulb", "core"), ("olive oil", 500, "ml", "core"),
    ("chicken breast", 600, "g", "core"), ("brown rice", 1, "kg", "core"), ("carrot", 4, None, "core"),
    ("broccoli", 1, "head", "core"), ("milk", 2, "L", "core"), ("eggs", 12, None, "core"),
    ("butter", 250, "g", "core"), ("cheddar cheese", 200, "g", "core"), ("bread", 1, "loaf", "core"),
    ("tomato", 6, None, "core"), ("capsicum", 3, None, "core"), ("spinach", 200, "g", "core"),
    ("greek yoghurt", 500, "g", "core"), ("lemon", 3, None, "core"), ("ginger", 1, "piece", "core"),
    ("soy sauce", 250, "ml", "core"), ("pasta", 500, "g", "core"),
    ("beef mince", 500, "g", "occasional"), ("salmon fillet", 400, "g", "occasional"),
    ("coconut milk", 400, "ml", "occasional"), ("chickpeas", 400, "g", "occasional"),
    ("basil", 1, "bunch", "occasional"), ("mushroom", 250, "g", "occasional"),
    ("sweet potato", 3, None, "occasional"), ("zucchini", 2, None, "occasional"),
]


def run_cycles(n_cycles: int) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
    from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
    from app.services import checklist as checklist_service
    from app.services import recipes as recipes_service
    from app.services import sessions as sessions_service

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()

    core = [g for g in GROCERY_ITEMS if g[3] == "core"]
    occasional = [g for g in GROCERY_ITEMS if g[3] == "occasional"]

    for cycle in range(n_cycles):
        active = list(core) + [g for i, g in enumerate(occasional) if (i + cycle) % 2 == 0]
        ings = [
            RecipeIngredientCreate(name=f"{RX.lower()}{name}", quantity=qty + (cycle % 3), unit=unit)
            for name, qty, unit, _ in active
        ]
        logger.info("--- cycle %d/%d (%d items) ---", cycle + 1, n_cycles, len(ings))

        r = recipes_service.create_recipe(
            db, RecipeCreate(name=f"RV cycle {cycle}", source_type="manual", base_servings=1, ingredients=ings),
            allow_duplicate=True,
        )
        s = sessions_service.create_session(db, PlanningSessionCreate())
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=1))
        sessions_service.consolidate_session(db, s.id)
        with_retry(lambda: checklist_service.load_checklist(db, s.id), label=f"cycle{cycle}-load")
        for c in s.checklist_items:
            checklist_service.update_item(db, s.id, c.id, have_it="no")

        result = with_retry(lambda: checklist_service.push_to_anylist(db, s.id), label=f"cycle{cycle}-push")
        logger.info(
            "cycle %d: added=%d updated=%d confirmed=%s discrepancies=%s",
            cycle + 1, len(result["added"]), len(result["updated"]), result["confirmed"], result["discrepancies"],
        )
        if result["discrepancies"]:
            DISCREPANCIES.append({"cycle": cycle + 1, "detail": result["discrepancies"]})
        time.sleep(0.3)

    db.close()
    engine.dispose()


def cleanup() -> None:
    from app.services.anylist_wire import (
        _build_operation, _build_operation_list, _decode_message, _item_to_wire, _s,
    )
    client = ac._get_client()
    resp = client._data_post("/data/user-data/get")
    top = _decode_message(resp.content)
    inner = _decode_message(top[1][0])
    list_id, items = "", {}
    for raw_list in inner.get(1, []):
        lst = _decode_message(raw_list)
        if (_s(lst, 3) or "").strip() == settings.anylist_target_list_name.strip():
            list_id = _s(lst, 1) or ""
            for raw_item in lst.get(4, []):
                f = _decode_message(raw_item)
                items[_s(f, 1) or ""] = f
    removed = 0
    for ident, f in items.items():
        name = _s(f, 4) or ""
        if name.upper().startswith(RX.upper()):
            op = _build_operation(handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident,
                item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None))
            try:
                client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
                removed += 1
            except Exception:
                pass
            time.sleep(0.15)
    logger.info("cleanup: removed %d RV- items", removed)


def main() -> int:
    if settings.anylist_target_list_name.strip() != "TestList":
        logger.error("Refusing to run: target list is %r, not TestList.", settings.anylist_target_list_name)
        return 1
    if settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: needs ANYLIST_ENABLED=true and ANYLIST_FAKE_MODE=false.")
        return 1

    ac.reset_client()
    ac.check_auth()

    t0 = time.time()
    run_cycles(N_CYCLES)
    elapsed = time.time() - t0

    logger.info("=== DONE in %.0fs: %d discrepancies across %d cycles ===", elapsed, len(DISCREPANCIES), N_CYCLES)
    out = Path(__file__).resolve().parent / "anylist_replace_fix_revalidation_results.json"
    out.write_text(json.dumps({"discrepancies": DISCREPANCIES, "elapsed_s": elapsed, "n_cycles": N_CYCLES}, indent=2, default=str))

    cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
