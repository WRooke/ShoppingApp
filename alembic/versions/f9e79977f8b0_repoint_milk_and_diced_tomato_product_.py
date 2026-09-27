"""repoint milk and diced tomato product_units to Fix 5 aliases

Revision ID: f9e79977f8b0
Revises: 62a354151f0d
Create Date: 2026-09-27

Fix 5, F5.2 follow-up. The maintainer reviewed a real `suggest_ingredient_groupings()` audit
and accepted "milk" -> "full cream milk" and "diced tomato"/"crushed tomato" -> "canned tomato"
as household preferences (now seeded in `INGREDIENT_ALIAS_SEEDS`). `product_units` had
pre-existing pack-size rows seeded under the OLD names ("milk" x2, "diced tomato" x1) — once
those aliases are live, a real "milk"/"diced tomato" ingredient line resolves to the new
canonical name before pack-size lookup ever runs, so these rows would become permanently
unreachable, exactly the same class of bug F0's `c920cac31b6a` already fixed once for
"yoghurt".

**CLAUDE.md non-negotiable rule 3**: plain `UPDATE`s of the `ingredient_name` column on
existing rows only -- every other column (id, purchase_label, purchase_qty, purchase_unit,
is_preseeded, created_at) is left untouched, and no row is added or removed. Collision-safe
per row (same discipline as `62a354151f0d`'s alias-insert collisions): `product_units` has a
UNIQUE(ingredient_name, purchase_label) constraint, so if a household already has their own
"full cream milk"/"<label>" or "canned tomato"/"<label>" row (e.g. added by hand via Settings
before this migration ever ran), a blind rename would collide. Each row is renamed inside its
own SAVEPOINT; a conflict leaves that one row completely untouched and prints a report line,
never crashes the migration and never silently drops or merges anything. If a "milk"/"diced
tomato" row doesn't exist at all (e.g. a fresh dev DB seeded after this fix already shipped),
that rename is simply a no-op, not an error.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.exc import IntegrityError
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9e79977f8b0'
down_revision: Union[str, Sequence[str], None] = '62a354151f0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = {
    "milk": "full cream milk",
    "diced tomato": "canned tomato",
}


def upgrade() -> None:
    conn = op.get_bind()
    product_units = sa.table(
        "product_units",
        sa.column("id", sa.Integer()),
        sa.column("ingredient_name", sa.Text()),
        sa.column("purchase_label", sa.Text()),
    )
    for old_name, new_name in _RENAMES.items():
        rows = conn.execute(
            sa.select(product_units.c.id, product_units.c.purchase_label).where(
                product_units.c.ingredient_name == old_name
            )
        ).fetchall()
        for row in rows:
            savepoint = conn.begin_nested()
            try:
                conn.execute(
                    product_units.update()
                    .where(product_units.c.id == row.id)
                    .values(ingredient_name=new_name)
                )
                savepoint.commit()
            except IntegrityError:
                savepoint.rollback()
                print(
                    f"[f9e79977f8b0] Skipped repointing product_units.id={row.id} "
                    f"({old_name!r}, purchase_label={row.purchase_label!r}) to {new_name!r}: "
                    f"a row for ({new_name!r}, {row.purchase_label!r}) already exists. Left "
                    "completely untouched -- reconcile by hand via Settings if needed."
                )


def downgrade() -> None:
    # Documented no-op, same precedent as this plan's other data migrations (e.g. c920cac31b6a)
    # -- renaming back is not attempted because a genuine row under the new name could have
    # been added independently (e.g. via Settings) after this migration ran, and nothing was
    # ever deleted by upgrade() to recover in the first place.
    pass
