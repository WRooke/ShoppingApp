"""AnyList reliability investigation (2026-09-19) — Phase A of the "fix it" follow-up to the
2026-09-18 fault-finding spike (docs/build-status/anylist-fault-finding-spike.md).

Throwaway script. NOT wired into the app — do not import this from app/.

That spike's leading theory for symptom #1 ("Not set" quantity, "+" jumps from the true value)
was falsified by a live phone check: a field-18-only item displayed its quantity *correctly*.
What's left standing is probe 3's other finding — a minority of `set-list-item-quantity` calls
silently persist **nothing at all** (both protobuf fields empty afterward) — but that was only
directly observed twice, and a 35-call follow-up couldn't reproduce it on demand. This script
runs at the scale needed to actually characterize that failure rather than eyeball three data
points:

1. **A1 — realistic multi-cycle simulation.** A ~28-item synthetic grocery list (generic names,
   no household data) pushed through 10 simulated "weekly" cycles via the REAL app pipeline
   (recipe -> session -> consolidate -> load_checklist -> push_to_anylist), alternating dense
   (near-zero spacing) and spaced (multi-second spacing) cycles to test whether the "cumulative
   across a session" theory in docs/deferred-decisions.md holds up against request density
   specifically, not just wall-clock session length.
2. **A2 — full forensics on every call.** `_RealAnyList._data_post` is wrapped (not modified —
   this script instruments the live instance, the committed connector is untouched) to log
   status, headers, body length, and timing for EVERY call, not just non-200s, since a silent
   failure returns 200 and nothing about it has ever actually been inspected before.
3. **A3 — controlled re-test of the "details corrupts quantity forever" finding** (Chunk 5.7,
   2026-09-12): one group of items gets a single `set-list-item-details` call then many
   quantity-only updates; a control group gets only quantity updates, same volume. If failure
   rates are statistically similar, that finding was very likely a misdiagnosis of this same
   general flakiness (exactly as a differently-shaped 2026-09-10 finding in this project's
   history turned out to be) — which would unblock actually fixing the notes-on-update
   limitation instead of just documenting it.

Any item caught with BOTH quantity fields empty right after a write is deliberately left on
TestList (not cleaned up) and printed clearly at the end for a one-off phone check — otherwise
everything this script creates is removed again via the wire-level `remove-shopping-list-item`
handler, same as the prior spike's probe 10.

Always targets `settings.anylist_target_list_name` (TestList) — refuses to run otherwise. Reads
credentials the same way the app does (`app.config.settings`) — never hardcoded, never printed.

Usage:
    .venv\\Scripts\\python.exe -m spike.anylist_reliability_investigation
"""

from __future__ import annotations

import json
import logging
import sys
import time
import types
from pathlib import Path

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import AnyListError, PushItem
from app.services.anylist_wire import (
    _b,
    _build_operation,
    _build_operation_list,
    _decode_message,
    _item_to_wire,
    _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("anylist_reliability_investigation")

RX = "RX-"  # this run's item prefix (Reliability investigation), distinct from the prior FF-
CALL_LOG: list[dict] = []
DISCREPANCIES: list[dict] = []
LEFTOVER_FOR_PHONE_CHECK: list[str] = []

# --- realistic synthetic grocery list (generic, no household data) --------------------------
# (name, qty, unit, "core"|"occasional") -- core items appear every cycle (like real staples),
# occasional ones appear in roughly half the cycles (like a one-off recipe ingredient).
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


def instrument(client) -> None:
    """Wrap the live connector instance's _data_post so every call this run makes — through
    the public API or the raw helpers below — is logged with full forensics, without touching
    the committed app code."""
    orig = type(client)._data_post

    def wrapped(self, path, *, files=None):
        t0 = time.time()
        try:
            resp = orig(self, path, files=files)
            CALL_LOG.append({
                "ts": t0, "path": path, "status": resp.status_code,
                "dt_ms": round((time.time() - t0) * 1000),
                "body_len": len(resp.content),
                "headers": {k: v for k, v in resp.headers.items() if k.lower() != "authorization"},
            })
            return resp
        except Exception as exc:  # noqa: BLE001 — log, then re-raise unchanged
            CALL_LOG.append({
                "ts": t0, "path": path, "error": repr(exc),
                "dt_ms": round((time.time() - t0) * 1000),
            })
            raise

    client._data_post = types.MethodType(wrapped, client)


def raw_dump() -> tuple[str, dict[str, dict]]:
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


def is_blank(f: dict) -> bool:
    has21 = 21 in f
    v18 = _s(f, 18)
    return not has21 and v18 is None


def with_retry(fn, *, attempts: int = 3, label: str = ""):
    """Script-level resilience against a transient AnyList timeout so a long simulation
    doesn't die on one slow response — NOT the app-level fix (that's Phase B); this only keeps
    the investigation itself running."""
    for n in range(attempts):
        try:
            return fn()
        except AnyListError as exc:
            if n == attempts - 1:
                raise
            logger.warning("%s: attempt %d/%d failed (%s) — retrying", label, n + 1, attempts, exc)
            time.sleep(2.0)


# --- A1: realistic multi-cycle simulation ----------------------------------------------------


def run_cycles(n_cycles: int = 10) -> None:
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
        dense = cycle % 2 == 0
        spacing = 0.1 if dense else 2.0
        active = list(core) + [g for i, g in enumerate(occasional) if (i + cycle) % 2 == 0]
        # small week-to-week quantity drift, still deterministic-ish for reproducibility
        ings = [
            RecipeIngredientCreate(name=f"{RX.lower()}{name}", quantity=qty + (cycle % 3), unit=unit)
            for name, qty, unit, _ in active
        ]
        logger.info(
            "--- cycle %d/%d (%s spacing=%.1fs, %d items) ---",
            cycle + 1, n_cycles, "DENSE" if dense else "SPACED", spacing, len(ings),
        )

        r = with_retry(
            lambda: recipes_service.create_recipe(
                db, RecipeCreate(name=f"RX cycle {cycle}", source_type="manual", base_servings=1, ingredients=ings),
                allow_duplicate=True,
            ),
            label=f"cycle{cycle}-create_recipe",
        )
        s = sessions_service.create_session(db, PlanningSessionCreate())
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=1))
        sessions_service.consolidate_session(db, s.id)

        with_retry(lambda: checklist_service.load_checklist(db, s.id), label=f"cycle{cycle}-load")
        for c in s.checklist_items:
            checklist_service.update_item(db, s.id, c.id, have_it="no")
            time.sleep(spacing / 4)  # pacing applies to the AnyList calls below, not local DB writes

        result = with_retry(lambda: checklist_service.push_to_anylist(db, s.id), label=f"cycle{cycle}-push")
        logger.info(
            "cycle %d: added=%d updated=%d confirmed=%s discrepancies=%s",
            cycle + 1, len(result["added"]), len(result["updated"]), result["confirmed"], result["discrepancies"],
        )
        if result["discrepancies"]:
            DISCREPANCIES.append({"phase": "A1", "cycle": cycle + 1, "detail": result["discrepancies"]})
            _check_for_blank_items([f"{RX.lower()}{name}".title() for name, *_ in active])

        time.sleep(spacing)

    db.close()
    engine.dispose()


def _check_for_blank_items(candidate_titled_names: list[str]) -> None:
    """After a discrepancy, look for any candidate item that's actually blank in both fields
    and, if found, leave it alone (don't clean it up) for a phone check."""
    try:
        _, items = raw_dump()
    except Exception:
        return
    for f in items.values():
        name = _s(f, 4) or ""
        if name in candidate_titled_names and is_blank(f):
            LEFTOVER_FOR_PHONE_CHECK.append(name)
            logger.warning(">>> CAUGHT a live blank-quantity item: %r — leaving it on TestList", name)


# --- A3: controlled re-test of the "details breaks quantity forever" finding -----------------


def run_details_experiment(group_size: int = 6, updates_per_item: int = 15) -> dict:
    client = ac._get_client()

    def seed(prefix: str) -> list[tuple[str, str]]:
        out = []
        for i in range(group_size):
            name = f"{RX}exp-{prefix}-{i}"
            with_retry(
                lambda name=name: ac.add_or_increment_items([PushItem(name=name, quantity="1")]),
                label=f"seed-{name}",
            )
            out.append(name)
        return out

    detail_names = seed("detail")
    control_names = seed("control")

    _, items = raw_dump()
    ids = {name: ident for ident, f in items.items() for name in (_s(f, 4),) if name in detail_names + control_names}

    # touch the detail group once with set-list-item-details, then leave both groups alone
    list_id, _ = raw_dump()
    for name in detail_names:
        op = _build_operation(
            handler_id="set-list-item-details", list_id=list_id, list_item_id=ids[name], updated_value="experiment note",
        )
        with_retry(
            lambda op=op: client._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            ),
            label=f"details-touch-{name}",
        )
        time.sleep(0.3)

    def run_updates(names: list[str], label: str) -> int:
        failures = 0
        for round_n in range(updates_per_item):
            for name in names:
                val = str(round_n + 2)
                res = with_retry(
                    lambda name=name, val=val: ac.add_or_increment_items(
                        [PushItem(name=name, quantity=val, existing_id=ids[name])]
                    ),
                    label=f"{label}-{name}-round{round_n}",
                )
                if not res.confirmed:
                    failures += 1
                    DISCREPANCIES.append({"phase": "A3", "group": label, "item": name, "round": round_n, "detail": res.discrepancies})
                    _check_for_blank_items([name])
                time.sleep(0.2)
        return failures

    detail_failures = run_updates(detail_names, "detail-group")
    control_failures = run_updates(control_names, "control-group")

    total_detail = group_size * updates_per_item
    total_control = group_size * updates_per_item
    verdict = {
        "detail_group_failures": detail_failures, "detail_group_total": total_detail,
        "control_group_failures": control_failures, "control_group_total": total_control,
        "detail_failure_rate": detail_failures / total_detail,
        "control_failure_rate": control_failures / total_control,
    }
    logger.info("A3 verdict: %s", verdict)
    return verdict


# --- cleanup ----------------------------------------------------------------------------------


def cleanup(skip_names: set[str]) -> None:
    list_id, items = raw_dump()
    client = ac._get_client()
    removed, kept = [], []
    for ident, f in items.items():
        name = _s(f, 4) or ""
        if not name.upper().startswith(RX.upper()):
            continue
        if name in skip_names:
            kept.append(name)
            continue
        item_wire = _item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None)
        op = _build_operation(handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident, item_wire=item_wire)
        try:
            client._data_post(
                "/data/shopping-lists/update",
                files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
            )
            removed.append(name)
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.warning("cleanup failed for %r: %r", name, exc)
        time.sleep(0.2)
    logger.info("cleanup: removed=%d kept_for_phone_check=%s", len(removed), kept)


def main() -> int:
    if settings.anylist_target_list_name.strip() != "TestList":
        logger.error("Refusing to run: target list is %r, not TestList.", settings.anylist_target_list_name)
        return 1
    if settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: needs ANYLIST_ENABLED=true and ANYLIST_FAKE_MODE=false.")
        return 1

    ac.reset_client()
    ac.check_auth()
    instrument(ac._get_client())

    t0 = time.time()
    logger.info("=== Phase A1: realistic multi-cycle simulation ===")
    run_cycles(n_cycles=10)

    logger.info("=== Phase A3: details-corruption controlled re-test ===")
    verdict = run_details_experiment()

    elapsed = time.time() - t0
    total_calls = len(CALL_LOG)
    failed_calls = sum(1 for c in CALL_LOG if c.get("status") != 200)
    logger.info(
        "=== DONE in %.0fs: %d HTTP calls, %d non-200/errored, %d discrepancies, %d caught blank ===",
        elapsed, total_calls, failed_calls, len(DISCREPANCIES), len(LEFTOVER_FOR_PHONE_CHECK),
    )

    out_dir = Path(__file__).resolve().parent
    (out_dir / "anylist_reliability_calllog.json").write_text(json.dumps(CALL_LOG, default=str, indent=2))
    (out_dir / "anylist_reliability_discrepancies.json").write_text(json.dumps(DISCREPANCIES, default=str, indent=2))
    (out_dir / "anylist_reliability_verdict.json").write_text(json.dumps({
        "total_calls": total_calls, "failed_calls": failed_calls,
        "discrepancy_count": len(DISCREPANCIES), "caught_blank": LEFTOVER_FOR_PHONE_CHECK,
        "a3_verdict": verdict, "elapsed_s": elapsed,
    }, default=str, indent=2))

    cleanup(skip_names=set(LEFTOVER_FOR_PHONE_CHECK))

    if LEFTOVER_FOR_PHONE_CHECK:
        logger.warning("PHONE CHECK NEEDED for: %s (left on TestList)", LEFTOVER_FOR_PHONE_CHECK)
    else:
        logger.info("Nothing caught live this run — no phone check needed, TestList is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
