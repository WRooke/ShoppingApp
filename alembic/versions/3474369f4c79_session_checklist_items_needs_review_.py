"""session_checklist_items.needs_review + note (Chunk 4.6)

Revision ID: 3474369f4c79
Revises: 1bc1ac8991f4
Create Date: 2026-09-06

Phase 4 Chunk 4.6 surfaced the need for two display-only columns on the consolidated
checklist (see CLAUDE.md > Scaling Logic > Rounding & unit rules):
  * needs_review — mass + volume for one ingredient can't be merged (no density data);
    the line is flagged, total_quantity/unit stay NULL, the parts go in `note`.
  * note — also carries a "to taste" marker and an overage note ("450 g spare").

Same server_default-then-drop dance as migration 1bc1ac8991f4's slot_type, so
needs_review matches Base.metadata.create_all() (Python-side defaults only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3474369f4c79"
down_revision: Union[str, Sequence[str], None] = "1bc1ac8991f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "needs_review", sa.Boolean(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.alter_column("needs_review", existing_type=sa.Boolean(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.drop_column("note")
        batch_op.drop_column("needs_review")
