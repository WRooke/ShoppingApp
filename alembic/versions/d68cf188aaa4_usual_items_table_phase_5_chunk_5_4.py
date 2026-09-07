"""usual_items table (phase 5 chunk 5.4)

Revision ID: d68cf188aaa4
Revises: c199ab55bf1e
Create Date: 2026-09-07

Phase 5 Chunk 5.4 — "the usuals": recurring non-recipe household items on a day-based
cadence. See CLAUDE.md > Data Model > usual_items and > Checklist Screen Logic > "The usuals".
New whole table, so `Base.metadata.create_all()` on a fresh DB already covers it; this
migration is what brings an existing populated DB up to the same schema.
tests/test_migrations.py keeps `upgrade head` == `create_all()`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d68cf188aaa4"
down_revision: Union[str, Sequence[str], None] = "c199ab55bf1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usual_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cadence_days", sa.Integer(), nullable=False),
        sa.Column("last_added_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_usual_items_name"),
    )


def downgrade() -> None:
    op.drop_table("usual_items")
