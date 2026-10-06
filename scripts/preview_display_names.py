"""Preview (and sanity-check) how ingredient display names come out on REAL data, read-only.

    .venv\\Scripts\\python -m scripts.preview_display_names [path\\to\\mealplanner.db]

For every ingredient key found in ``recipe_ingredients`` it prints the household's written forms and
what ``checklist_display.display_name`` + ``title_case_name`` would show at a few representative
amounts, then checks the central safety property for EVERY key and amount:

  1. the display string normalises back to the same key (so nothing about matching can change), and
  2. the title-cased AnyList name still matches its own checklist row under ``checklist._names_match``
     (so a re-push finds the item it pushed).

Opens the database read-only (``mode=ro``) — it can never modify it — and prints ingredient names only
(no personal data). Exit status 1 if either property fails anywhere. See
docs/ingredient-handling.md > Display names.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import checklist, checklist_display as cd, text_normalize

AMOUNTS = [(None, None), (1, None), (3, None), (500, "g"), (2, "tbsp"), (12, "clove")]


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("data/mealplanner_prod.db")
    if not path.exists():
        print(f"no database at {path}")
        return 2
    engine = create_engine(f"sqlite:///file:{path.resolve().as_posix()}?mode=ro&uri=true", future=True)
    db = sessionmaker(bind=engine, future=True)()
    try:
        index = cd.WordingIndex.build(db)
        keys = sorted(index.forms)
        bad = 0
        changed = 0
        print(f"{len(keys)} ingredient keys in {path.name}\n")
        print(f"{'key':34} {'written as':40} " + " | ".join(f"{(q or '-')!s:>3}{(u or ''):>5}" for q, u in AMOUNTS))
        for key in keys:
            forms = ", ".join(f"{f}×{n}" for f, n in index.forms[key].most_common(3))
            shown = []
            for q, u in AMOUNTS:
                d = cd.display_name(db, key, q, u, index)
                push = text_normalize.title_case_name(d)
                if text_normalize.normalise_ingredient_name(d) != key:
                    bad += 1
                    print(f"!! display {d!r} does not normalise back to {key!r}")
                if not checklist._names_match(key, push):
                    bad += 1
                    print(f"!! pushed name {push!r} would not match its own row {key!r}")
                shown.append(d)
            if len(set(shown)) > 1 or shown[0] != key:
                changed += 1
            print(f"{key[:34]:34} {forms[:40]:40} " + " | ".join(s[:14] for s in shown))
        print(f"\n{changed}/{len(keys)} keys display differently from the bare key at some amount; "
              f"{bad} safety violation(s).")
        return 1 if bad else 0
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
