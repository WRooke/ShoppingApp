"""ingredient_aliases — "same shopping item" grouping

Revision ID: c4d8f0a1b2e3
Revises: 7a2f9e1c4b3d
Create Date: 2026-09-10

2026-09-10, generalised from hand-testing feedback about oil variants ("canola oil" /
"vegetable oil" / "oil spray" reading as separate shopping-list lines when the household
considers them the same thing). See CLAUDE.md > Ingredient Aliases for the full design and
why this is a different concept from ``remembered_substitutions``.

Brand-new table, so (unlike the batch add_column migrations elsewhere in this history) this
is a plain ``create_table`` — no existing rows to preserve, no server_default dance needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d8f0a1b2e3"
down_revision: Union[str, Sequence[str], None] = "7a2f9e1c4b3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingredient_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alias_name", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_name"),
    )
    op.create_index(
        "ix_ingredient_aliases_canonical_name",
        "ingredient_aliases",
        ["canonical_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingredient_aliases_canonical_name", table_name="ingredient_aliases")
    op.drop_table("ingredient_aliases")
