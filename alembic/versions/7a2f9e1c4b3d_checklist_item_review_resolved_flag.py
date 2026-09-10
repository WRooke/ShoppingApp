"""session_checklist_items.review_resolved_by_user

Revision ID: 7a2f9e1c4b3d
Revises: d68cf188aaa4
Create Date: 2026-09-10

2026-09-10 hand-testing ("doesn't remember amounts under review") — consolidate_session()
unconditionally overwrote total_quantity/total_unit/needs_review/note on every recompute, so
a needs_review conflict (e.g. "100 g + 200 ml") the user had manually resolved via
POST /checklist/{id}/items/{id}/resolve got silently re-flagged and reset the next time the
session was re-consolidated (adding a recipe, changing servings, re-opening the review
screen). See CLAUDE.md > Scaling Logic > re-running consolidation and > Checklist Screen
Logic.

review_resolved_by_user marks "this row's current total_quantity/total_unit is a manual
choice the recompute must not clobber while the same ingredient still conflicts". Set True by
services/checklist.py > resolve_item(); consulted (and cleared once the conflict is gone) by
services/session_consolidation.py > consolidate_session(). Same server_default-then-drop dance
as migrations 1bc1ac8991f4 / 3474369f4c79, so it matches Base.metadata.create_all() (Python-
side defaults only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a2f9e1c4b3d"
down_revision: Union[str, Sequence[str], None] = "d68cf188aaa4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "review_resolved_by_user",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.alter_column(
            "review_resolved_by_user", existing_type=sa.Boolean(), server_default=None
        )


def downgrade() -> None:
    with op.batch_alter_table("session_checklist_items", schema=None) as batch_op:
        batch_op.drop_column("review_resolved_by_user")
