"""session_checklist_items.have_quantity / have_unit ("I have some", Chunk 6.7, user-feedback batch, batch 3)

Revision ID: a1b2c3d4e5f6
Revises: c7c1ecd37ec8
Create Date: 2026-10-16

Adds two NULLABLE columns holding how much of an ingredient the household already has, so the
checklist can buy only the difference. Purely additive per the never-lose-production-data rule (CLAUDE.md > Non-Negotiable Operating Rules): no existing row is
touched (both columns start NULL = "nothing recorded"), nothing is dropped or narrowed.
tests/test_migrations.py keeps `upgrade head` == `create_all()`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c7c1ecd37ec8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("session_checklist_items") as batch:
        batch.add_column(sa.Column("have_quantity", sa.Float(), nullable=True))
        batch.add_column(sa.Column("have_unit", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("session_checklist_items") as batch:
        batch.drop_column("have_unit")
        batch.drop_column("have_quantity")
