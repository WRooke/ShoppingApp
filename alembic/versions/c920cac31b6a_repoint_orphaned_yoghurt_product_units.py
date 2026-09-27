"""repoint orphaned yoghurt product_units rows to greek yoghurt

Revision ID: c920cac31b6a
Revises: e62ee59a3bdc
Create Date: 2026-09-27

F0 of the ingredient-name-matching plan. The prod DB audit (2026-09-27) found `product_units`
rows seeded as bare `"yoghurt"` (two pack sizes) that match NONE of the three real yoghurt
ingredient names ever actually used (`"plain yoghurt"`, `"plain yogurt"`, `"greek yoghurt"`) --
`ProductUnit.ingredient_name` is matched by literal equality against the final resolved
ingredient name, so these rows have been permanently unreachable. Now that `"plain
yoghurt"`/`"plain yogurt"` alias to `"greek yoghurt"` (see app/seed_data.py's
INGREDIENT_ALIAS_SEEDS, same migration set), re-pointing these two rows makes pack-size
resolution work for yoghurt again.

**CLAUDE.md non-negotiable rule 3 (data loss on prod is never acceptable)**: this is a plain
`UPDATE` of the `ingredient_name` column on two EXISTING rows -- every other field (id,
purchase_label, purchase_qty, purchase_unit, is_preseeded, created_at) is left untouched. No row
is added or removed. If a row named "yoghurt" doesn't exist (e.g. a dev DB that never had it),
this is a no-op, not an error.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c920cac31b6a"
down_revision: Union[str, Sequence[str], None] = "e62ee59a3bdc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_NAME = "yoghurt"
_NEW_NAME = "greek yoghurt"


def upgrade() -> None:
    product_units = sa.table(
        "product_units",
        sa.column("ingredient_name", sa.Text()),
    )
    op.execute(
        product_units.update()
        .where(product_units.c.ingredient_name == _OLD_NAME)
        .values(ingredient_name=_NEW_NAME)
    )


def downgrade() -> None:
    # Documented no-op, same precedent as this plan's other data migrations: renaming back is
    # not attempted because a genuine "greek yoghurt" row could have been added independently
    # (e.g. via Settings) after this migration ran, and blindly renaming every such row back to
    # "yoghurt" would misfire against it. Nothing was ever deleted by upgrade(), so there is no
    # data to recover here either way.
    pass
