"""capture_queue table (Phase 3.9 M3)

Revision ID: 285e886712e0
Revises: 3474369f4c79
Create Date: 2026-09-06

New whole table — capture AI tasks deferred on a 429 from both Gemini models, retried
hourly. See CLAUDE.md > Data Model > capture_queue.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "285e886712e0"
down_revision: Union[str, Sequence[str], None] = "3474369f4c79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capture_queue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("capture_queue", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_capture_queue_recipe_id"), ["recipe_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("capture_queue", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_capture_queue_recipe_id"))
    op.drop_table("capture_queue")
