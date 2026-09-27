"""ingredient_aliases source column

Revision ID: 092f6bb91c9c
Revises: bcaf5b44af53
Create Date: 2026-09-27

F2.1 of the ingredient-name-matching plan (Fix 2 — aliases feed the extraction prompt). Adds
``source`` (``"system"`` | ``"user"``) so the prompt builder (F2.3) can frame a household
preference distinctly from a universal-English fact, and so a household can never create a
``source='system'`` row via the API (the ``IngredientAliasCreate`` schema has no ``source``
field at all — this is a DB-default-only distinction).

NOT NULL, existing rows backfilled to ``'user'`` — every existing row (the oil/lemon/lime/
yoghurt/heavy-cream/broth groups seeded so far, all genuinely household-facing choices, not
universal facts) correctly becomes ``source='user'`` with no data loss and no manual backfill
needed (CLAUDE.md non-negotiable rule 3). F2.2's own migration (chained after this one) is what
actually inserts the first ``source='system'`` rows.

Same server_default-then-drop dance as migrations ``1bc1ac8991f4``/``3474369f4c79`` — add the
column with a ``server_default`` (needed for SQLite to backfill existing rows on a NOT NULL
ADD COLUMN), then drop the server_default in a second step, so the final schema matches
``Base.metadata.create_all()`` (Python-side ``default="user"`` only, no DB-level default) —
see ``tests/test_migrations.py::test_migration_chain_matches_create_all``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '092f6bb91c9c'
down_revision: Union[str, Sequence[str], None] = 'bcaf5b44af53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ingredient_aliases", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.Text(), nullable=False, server_default="user")
        )
    with op.batch_alter_table("ingredient_aliases", schema=None) as batch_op:
        batch_op.alter_column("source", existing_type=sa.Text(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("ingredient_aliases", schema=None) as batch_op:
        batch_op.drop_column("source")
