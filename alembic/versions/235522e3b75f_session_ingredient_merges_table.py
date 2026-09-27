"""session_ingredient_merges table

Revision ID: 235522e3b75f
Revises: f9e79977f8b0
Create Date: 2026-09-27

Fix 3, F3.1 (CLAUDE.md > Deferred Decisions > checklist-time merge) — a session-scoped,
ephemeral "fold these two checklist items into one, for this session only" rule, the
counterpart to a durable `ingredient_aliases` row. New whole table, so
`Base.metadata.create_all()` on a fresh DB already covers it; this migration brings an
existing populated DB up to the same schema. `ondelete="CASCADE"` on `session_id` matches
`session_recipes`/`session_checklist_items` — a merge that wasn't "remembered" disappears
automatically when its session is deleted, no manual cleanup needed.
tests/test_migrations.py keeps `upgrade head` == `create_all()`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "235522e3b75f"
down_revision: Union[str, Sequence[str], None] = "f9e79977f8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_ingredient_merges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("planning_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_name", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("alias_qty", sa.Float(), nullable=True),
        sa.Column("alias_unit", sa.Text(), nullable=True),
        sa.Column("canonical_qty", sa.Float(), nullable=True),
        sa.Column("canonical_unit", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "member_name"),
    )
    with op.batch_alter_table("session_ingredient_merges", schema=None) as batch_op:
        batch_op.create_index(
            "ix_session_ingredient_merges_session_id", ["session_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("session_ingredient_merges")
