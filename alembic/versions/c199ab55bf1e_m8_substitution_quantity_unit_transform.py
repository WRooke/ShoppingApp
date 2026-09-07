"""m8 substitution quantity/unit transform

Revision ID: c199ab55bf1e
Revises: 15b1aab757ac
Create Date: 2026-09-07 21:00:40.068406

Phase 3.9 M8 — a substitution can change the *amount and unit*, not just the name
("2 whole corn cobs" -> "2 cans of corn"). See CLAUDE.md > AI Provider Migration >
Ingredient Substitution Flagging, and > Data Model > recipe_ingredients /
remembered_substitutions.

  * recipe_ingredients gains resolved_quantity / resolved_unit — the swap's ABSOLUTE amount
    for this recipe. Only meaningful with resolved_ingredient set; both NULL = name-only.
  * remembered_substitutions gains the four equivalence-pair columns
    (original_qty / original_unit / substitute_qty / substitute_unit) the quick-pick uses to
    pre-fill the recipe-level absolute. All NULL = a name-only quick-pick (unchanged from M4).

All six columns are nullable with no server default — Python-side defaults only, so
`alembic upgrade head` stays byte-for-byte equivalent to `Base.metadata.create_all()`
(tests/test_migrations.py guards this). render_as_batch handles the SQLite table rebuild.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c199ab55bf1e"
down_revision: Union[str, Sequence[str], None] = "15b1aab757ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_ingredients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resolved_quantity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("resolved_unit", sa.Text(), nullable=True))

    with op.batch_alter_table("remembered_substitutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("original_qty", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("original_unit", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("substitute_qty", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("substitute_unit", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("remembered_substitutions", schema=None) as batch_op:
        batch_op.drop_column("substitute_unit")
        batch_op.drop_column("substitute_qty")
        batch_op.drop_column("original_unit")
        batch_op.drop_column("original_qty")

    with op.batch_alter_table("recipe_ingredients", schema=None) as batch_op:
        batch_op.drop_column("resolved_unit")
        batch_op.drop_column("resolved_quantity")
