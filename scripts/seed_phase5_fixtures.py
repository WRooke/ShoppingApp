"""Seed a disposable DB with the fixtures the Phase 5 hand test plan needs.

Creates ``data/phase5-test.db`` (or ``--database <path>``) with:
  * the full schema (``Base.metadata.create_all`` — the fresh-DB fast path)
  * the app's own idempotent reference data (staples incl. "olive oil";
    ~30 product_units incl. "beef mince" 500g pack; section vocabulary)
  * three manual recipes tailored to the test plan's Setup section:
      - "P5 — Milk & Passata"   : milk 1 L (matches the fake AnyList list) + passata 400 g
      - "P5 — Beef & Oil"       : beef mince 500 g (seeded pack) + olive oil 2 tbsp (a staple)
      - "P5 — Cream Conflict"   : cream 100 g + cream 200 ml in ONE recipe -> a Chunk 4.6
                                  irreconcilable-units (`needs_review`) line at consolidation

Idempotent: re-running skips recipes that already exist by name. ``--reset`` deletes the
DB file first for a clean slate. Does NOT create sessions, usuals, or push anything — those
are test-plan steps.

    .venv\\Scripts\\python -m scripts.seed_phase5_fixtures            # data/phase5-test.db
    .venv\\Scripts\\python -m scripts.seed_phase5_fixtures --reset

Then start the server against it (fake modes on, nothing touches the real dev DB or AnyList):

    DATABASE_PATH=data/phase5-test.db AI_EXTRACTION_FAKE_MODE=true ANYLIST_FAKE_MODE=true \\
      .venv/Scripts/python -m app.main
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

RECIPES: list[dict] = [
    {
        "name": "P5 — Milk & Passata",
        "ingredients": [
            {"name": "milk", "quantity": 1, "unit": "L"},
            {"name": "passata", "quantity": 400, "unit": "g"},
        ],
    },
    {
        "name": "P5 — Beef & Oil",
        "ingredients": [
            {"name": "beef mince", "quantity": 500, "unit": "g"},
            {"name": "olive oil", "quantity": 2, "unit": "tbsp"},
        ],
    },
    {
        "name": "P5 — Cream Conflict",
        "ingredients": [
            {"name": "cream", "quantity": 100, "unit": "g"},
            {"name": "cream", "quantity": 200, "unit": "ml"},
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default="data/phase5-test.db",
        help="SQLite path, relative to the project root (default: data/phase5-test.db)",
    )
    parser.add_argument("--reset", action="store_true", help="delete the DB file first")
    args = parser.parse_args()

    db_path = (BASE_DIR / args.database).resolve()
    if args.reset and db_path.exists():
        db_path.unlink()
        print(f"reset: removed {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Point the app at this DB *before* importing anything that reads settings.
    os.environ["DATABASE_PATH"] = str(db_path)

    from app.database import SessionLocal, init_db  # noqa: E402
    from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate  # noqa: E402
    from app.seed_data import seed_reference_data  # noqa: E402
    from app.services import recipes as recipes_service  # noqa: E402

    init_db()
    print(f"schema ready at {db_path}")

    db = SessionLocal()
    try:
        ref = seed_reference_data(db)
        print(f"reference data: {ref}")

        existing = {r.name for r in recipes_service.list_recipes(db, limit=1000)[0]}
        created = []
        for spec in RECIPES:
            if spec["name"] in existing:
                print(f"skip (exists): {spec['name']}")
                continue
            recipe = recipes_service.create_recipe(
                db,
                RecipeCreate(
                    name=spec["name"],
                    source_type="manual",
                    base_servings=4,
                    ingredients=[RecipeIngredientCreate(**i) for i in spec["ingredients"]],
                ),
                allow_duplicate=True,
            )
            created.append(f"#{recipe.id} {recipe.name}")
        print(f"recipes created: {created or 'none (all already present)'}")
    finally:
        db.close()

    rel = args.database.replace("\\", "/")
    print(
        "\nStart the server against it (fake modes on — real dev DB and AnyList untouched):\n"
        f"  DATABASE_PATH={rel} AI_EXTRACTION_FAKE_MODE=true ANYLIST_FAKE_MODE=true \\\n"
        "    .venv/Scripts/python -m app.main\n"
        "\nThe fake AnyList 'TestList' is auto-seeded with milk / eggs / butter on first call."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
