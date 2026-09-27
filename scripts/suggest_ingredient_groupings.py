"""Fix 5, F5.2 — one-off AI-assisted audit for ingredient-name groupings a household hasn't
aliased yet (CLAUDE.md > Deferred Decisions > AI-assisted ingredient-grouping discovery).

Read-only against whatever DB you point it at (only ever runs a SELECT via
``recipes_service.distinct_ingredient_names()`` — never writes a row). ``--db-path`` is
required, deliberately with no default, so running this is always a conscious choice of which
file to read — point it at a **restored copy** of the real database, never the live file
directly, same discipline as every other real-data check in the ingredient-name-matching plan.

Makes exactly ONE real Gemini call per run (§0c: needs ``AI_EXTRACTION_ENABLED=true`` +
``GEMINI_API_KEY`` set first, and — per this app's standing rule — the maintainer's explicit
go-ahead in conversation before it's actually run, even with the switch already on).

This script never writes anything. A suggestion the maintainer wants to keep becomes a normal,
separate, human-reviewed addition to ``app/seed_data.py > INGREDIENT_ALIAS_SEEDS`` — the same
one-time-migration-or-idempotent-seed decision every other alias in this app already goes
through, not something this script automates.

    .venv\\Scripts\\python -m scripts.suggest_ingredient_groupings --db-path <path to a DB copy>
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to a SQLite DB to read from — a restored COPY, never the live prod file.",
    )
    parser.add_argument(
        "--include-aliased",
        action="store_true",
        help="Also ask about names that already have an alias (default: excluded — already solved).",
    )
    args = parser.parse_args()

    # Point the app at this DB *before* importing anything that reads settings (same convention
    # as scripts/seed_phase5_fixtures.py).
    os.environ["DATABASE_PATH"] = args.db_path

    from app.database import SessionLocal  # noqa: E402
    from app.services import ai_extraction  # noqa: E402
    from app.services import recipes as recipes_service  # noqa: E402

    if not ai_extraction.settings.ai_extraction_enabled:
        print(
            "AI_EXTRACTION_ENABLED is not 'true' -- this script needs it on, and the "
            "maintainer's explicit go-ahead in conversation for this specific run (CLAUDE.md "
            "> Security > section 0c). Not making any call."
        )
        return 1

    db = SessionLocal()
    try:
        names = recipes_service.distinct_ingredient_names(
            db, exclude_aliased=not args.include_aliased
        )
        print(f"Read {len(names)} distinct ingredient name(s) from {args.db_path!r}")
        if not names:
            print("Nothing to ask about.")
            return 0

        print("Making one real Gemini call...")
        groups = ai_extraction.suggest_ingredient_groupings(db, names=names)

        if not groups:
            print(
                "\nNo groupings suggested -- a legitimate result if the remaining ungrouped "
                "list genuinely has no more findable pairs, not necessarily a failure."
            )
            return 0

        print(f"\n{len(groups)} suggested group(s) -- review each, nothing is written automatically:\n")
        for g in groups:
            print(f"  {g.names} -> {g.suggested_canonical!r}")
            if g.reason:
                print(f"    reason: {g.reason}")
        print(
            "\nTo accept a group, add it to app/seed_data.py's INGREDIENT_ALIAS_SEEDS by hand "
            "(source='user', same convention as every other seeded alias) -- this script never "
            "writes anything itself."
        )
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
