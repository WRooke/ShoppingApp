"""recipes.ai_tasks_pending (Phase 3.9 M6)

Revision ID: 15b1aab757ac
Revises: b6e557ca6088
Create Date: 2026-09-06

One nullable TEXT column on ``recipes`` — a JSON array of still-outstanding AI capture
sub-tasks (currently only ``["suggest_sections"]``), NULL / "[]" meaning nothing pending.
Drives the "Pending AI processing" badge. See CLAUDE.md > Data Model > recipes and
> AI Provider Migration (M6).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "15b1aab757ac"
down_revision: Union[str, Sequence[str], None] = "b6e557ca6088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_tasks_pending", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        batch_op.drop_column("ai_tasks_pending")
