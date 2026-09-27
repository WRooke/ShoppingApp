"""seed legacy system ingredient alias groups

Revision ID: 62a354151f0d
Revises: 092f6bb91c9c
Create Date: 2026-09-27

F2.2 of the ingredient-name-matching plan (Fix 2). The extraction prompt's own
canonicalisation bullet has always hardcoded 3 pairs as literal prose: the plain-salt group,
"minced beef" -> "beef mince", "green onion"/"scallion" -> "spring onion". F2.3 removes those
hardcoded pairs from the static prompt and replaces them with a *dynamic* hint section built
from `source='system'` `ingredient_aliases` rows — this migration is what actually seeds those
7 rows, exactly once, so the prompt's real-world coverage doesn't regress the moment F2.3
ships.

**Not** added to `INGREDIENT_ALIAS_SEEDS`/`seed_reference_data()` (which runs on every
startup) -- these rows must behave like any other `ingredient_aliases` row a household could
delete via Settings: deleting one must NOT see it silently resurrected on the next restart.
A one-time migration is the only mechanism here that gives that guarantee.

**CLAUDE.md non-negotiable rule 3**: this migration is a deliberate, documented EXCEPTION to
"row count never decreases" in the sense that it *adds* rows (the plan's Testing &
Verification section names this as the legitimate exception, alongside F2.2 there) -- but it
still never destroys or silently overrides existing data. `alias_name` is UNIQUE: if a
household already has its own alias for one of these 7 exact strings (e.g. they grouped
"scallion" under something else via Settings before this migration ever ran), a blind bulk
insert would abort the whole migration with an IntegrityError. Each of the 7 pairs is
inserted individually inside its own SAVEPOINT instead: a conflict skips just that one pair,
leaves the household's existing row completely untouched, and prints a report line -- same
"skip and report, never crash or overwrite" discipline as `bcaf5b44af53`'s rename collisions,
now applied to a fresh INSERT rather than an UPDATE.

The normalisation logic below is a FROZEN SNAPSHOT of `app/services/text_normalize.py`, same
convention (and same "do not refactor to import the live module" rule) as `bcaf5b44af53`'s own
copy. None of these 7 literal strings actually need plural-stripping, but running every write
path through the same normaliser is the correct, consistent thing to do regardless.
"""
from __future__ import annotations

import re
from typing import Sequence, Union

import inflect
from alembic import op
from sqlalchemy.exc import IntegrityError
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62a354151f0d'
down_revision: Union[str, Sequence[str], None] = '092f6bb91c9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- frozen snapshot of app/services/text_normalize.py (2026-09-27) — see bcaf5b44af53's own
# identical copy for the full empirical reasoning; kept in sync by hand, never imported live. ---

_HYPHEN_FAMILY = re.compile(r"[-‐‑‒–—]")
_US_WHITELIST = {"asparagus", "couscous", "hummus", "citrus"}
_INFLECT = inflect.engine()


def _base_norm(name: str) -> str:
    folded = _HYPHEN_FAMILY.sub(" ", name.strip().lower())
    return " ".join(folded.split())


def _singularise_word(word: str) -> str:
    if word in _US_WHITELIST:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ves"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    if not word.endswith("s"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    return word


def _singularise(s: str) -> str:
    head, sep, tail = s.rpartition(" ")
    return f"{head}{sep}{_singularise_word(tail)}"


def _normalise(name: str) -> str:
    return _singularise(_base_norm(name))


# The 7 legacy pairs, previously hardcoded prose in EXTRACTION_SYSTEM_PROMPT (see F2.3).
_SYSTEM_PAIRS = [
    ("table salt", "salt"),
    ("cooking salt", "salt"),
    ("kosher salt", "salt"),
    ("sea salt", "salt"),
    ("minced beef", "beef mince"),
    ("green onion", "spring onion"),
    ("scallion", "spring onion"),
]


def upgrade() -> None:
    conn = op.get_bind()
    ingredient_aliases = sa.table(
        "ingredient_aliases",
        sa.column("alias_name", sa.Text()),
        sa.column("canonical_name", sa.Text()),
        sa.column("source", sa.Text()),
    )
    skipped: list[tuple[str, str]] = []
    for alias_name, canonical_name in _SYSTEM_PAIRS:
        alias_name = _normalise(alias_name)
        canonical_name = _normalise(canonical_name)
        savepoint = conn.begin_nested()
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO ingredient_aliases "
                    "(alias_name, canonical_name, source, created_at, updated_at) "
                    "VALUES (:alias_name, :canonical_name, 'system', "
                    "datetime('now'), datetime('now'))"
                ),
                {"alias_name": alias_name, "canonical_name": canonical_name},
            )
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            existing = conn.execute(
                sa.text(
                    "SELECT id, alias_name, canonical_name, source FROM ingredient_aliases "
                    "WHERE alias_name = :alias_name"
                ),
                {"alias_name": alias_name},
            ).fetchone()
            skipped.append((alias_name, canonical_name))
            print(
                f"[62a354151f0d] Skipped seeding system alias {alias_name!r} -> "
                f"{canonical_name!r}: a row for {alias_name!r} already exists "
                f"({dict(existing._mapping) if existing else 'details unavailable'}). "
                "Left completely untouched -- reconcile by hand via Settings if this system "
                "pair should still apply."
            )
    if skipped:
        print(
            f"[62a354151f0d] {len(skipped)} of {len(_SYSTEM_PAIRS)} system alias pair(s) "
            "skipped due to a pre-existing alias_name collision -- see report lines above."
        )


def downgrade() -> None:
    ingredient_aliases = sa.table(
        "ingredient_aliases",
        sa.column("alias_name", sa.Text()),
        sa.column("source", sa.Text()),
    )
    normalised_names = [_normalise(alias_name) for alias_name, _ in _SYSTEM_PAIRS]
    op.execute(
        ingredient_aliases.delete().where(
            ingredient_aliases.c.alias_name.in_(normalised_names),
            ingredient_aliases.c.source == "system",
        )
    )
