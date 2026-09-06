"""M4 substitution merge: recipe_ingredients resolved cols + remembered_substitutions

Revision ID: 173367a2aab2
Revises: 285e886712e0
Create Date: 2026-09-06

Phase 3.9 M4 — the substitution merge (CLAUDE.md > AI Provider Migration > The substitution
merge, and > Data Model > recipe_ingredients / remembered_substitutions):

  * recipe_ingredients gains resolved_ingredient / substitution_note (the per-recipe swap the
    user confirmed; NULL = use `name`).
  * ingredient_substitutions -> remembered_substitutions: is_default DROPPED (no silent
    auto-apply anywhere), note + last_used_at added. It becomes a quick-pick library only.

render_as_batch handles the SQLite table rebuilds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "173367a2aab2"
down_revision: Union[str, Sequence[str], None] = "285e886712e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_ingredients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resolved_ingredient", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("substitution_note", sa.Text(), nullable=True))

    op.rename_table("ingredient_substitutions", "remembered_substitutions")
    with op.batch_alter_table("remembered_substitutions", schema=None) as batch_op:
        batch_op.drop_column("is_default")
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("remembered_substitutions", schema=None) as batch_op:
        batch_op.drop_column("last_used_at")
        batch_op.drop_column("note")
        batch_op.add_column(
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
    with op.batch_alter_table("remembered_substitutions", schema=None) as batch_op:
        batch_op.alter_column("is_default", existing_type=sa.Boolean(), server_default=None)
    op.rename_table("remembered_substitutions", "ingredient_substitutions")

    with op.batch_alter_table("recipe_ingredients", schema=None) as batch_op:
        batch_op.drop_column("substitution_note")
        batch_op.drop_column("resolved_ingredient")
