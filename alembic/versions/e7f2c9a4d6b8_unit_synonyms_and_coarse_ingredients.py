"""unit_synonyms and coarse_ingredients

Revision ID: e7f2c9a4d6b8
Revises: d5e7a9c3f1b6
Create Date: 2026-09-12

2026-09-12 — see CLAUDE.md > Ingredient Unit Handling. Two brand-new, independent tables:

* ``unit_synonyms`` (Layer A) — unit-spelling canonicalisation, e.g. "grams" -> "g". The
  plainer sibling of ``ingredient_aliases`` (no equivalence pair needed).
* ``coarse_ingredients`` (Layer D) — ingredients (fresh herbs) that skip quantity/unit math
  entirely and resolve straight to a purchase-label count.

Both plain ``create_table`` — no existing rows, no server_default dance needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f2c9a4d6b8"
down_revision: Union[str, Sequence[str], None] = "d5e7a9c3f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unit_synonyms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alias_unit", sa.Text(), nullable=False),
        sa.Column("canonical_unit", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_unit"),
    )
    op.create_table(
        "coarse_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("purchase_label", sa.Text(), nullable=True),
        sa.Column("recipes_per_pack", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("coarse_ingredients")
    op.drop_table("unit_synonyms")
