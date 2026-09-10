"""ingredient_aliases equivalence pair + note

Revision ID: d5e7a9c3f1b6
Revises: c4d8f0a1b2e3
Create Date: 2026-09-10

2026-09-10, kicked off by "lemon juice should be put on the list as a lemon, same thing with
limes" (hand-testing). An alias can now optionally carry a quantity/unit equivalence pair
("2 tbsp lemon juice ~= 1 lemon") — the same shape ``remembered_substitutions`` already has
for its M8 transform, plus a freetext ``note`` matching that table too. See CLAUDE.md >
Ingredient Aliases and > Data Model > ingredient_aliases.

All five columns nullable, no server_default dance needed (unlike the NOT NULL boolean
columns in earlier migrations) -- existing rows (the oil-variant seed group) simply get NULL,
which is exactly "no equivalence pair", the correct default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e7a9c3f1b6"
down_revision: Union[str, Sequence[str], None] = "c4d8f0a1b2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ingredient_aliases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("alias_qty", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("alias_unit", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("canonical_qty", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("canonical_unit", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ingredient_aliases", schema=None) as batch_op:
        batch_op.drop_column("canonical_unit")
        batch_op.drop_column("canonical_qty")
        batch_op.drop_column("alias_unit")
        batch_op.drop_column("alias_qty")
        batch_op.drop_column("note")
