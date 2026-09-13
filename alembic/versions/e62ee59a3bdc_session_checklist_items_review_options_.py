"""session_checklist_items review_options_json (2026-09-13 code review)

Revision ID: e62ee59a3bdc
Revises: e7f2c9a4d6b8
Create Date: 2026-09-13 14:26:23.807878

Adds the nullable JSON column that replaces frontend regex-parsing of `note` to build the
"use 100 g" quick-resolve buttons on a `needs_review` checklist line — see
services/consolidation.py > ReviewOption and CLAUDE.md > Scaling Logic > Rounding & unit rules.
Nullable with no default, so it applies to a populated table without touching existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e62ee59a3bdc'
down_revision: Union[str, Sequence[str], None] = 'e7f2c9a4d6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('session_checklist_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_options_json', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('session_checklist_items', schema=None) as batch_op:
        batch_op.drop_column('review_options_json')
