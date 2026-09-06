"""phase 4 groundwork: session_recipes slot_type + nullable recipe_id, product_units composite unique, ingredient_substitutions

Revision ID: 1bc1ac8991f4
Revises: 9b903c88b3aa
Create Date: 2026-09-06 16:58:50.468499

Phase 4 Chunk 4.1 — schema groundwork only, no behaviour wired to it yet. Three changes,
each from an already-decided Data Model note in CLAUDE.md:

  * ``session_recipes`` — ``recipe_id`` becomes nullable and a ``slot_type`` flag is added
    ('recipe' | 'leftovers'), so a session slot can be a non-recipe "leftovers" marker that
    contributes nothing to consolidation. See CLAUDE.md > Data Model > session_recipes.
  * ``product_units`` — uniqueness moves from ``ingredient_name`` alone to
    (ingredient_name, purchase_label): one ingredient can have several pack-size rows. See
    CLAUDE.md > Data Model > product_units and > Scaling Logic > Purchase unit resolution.
  * ``ingredient_substitutions`` — new table (schema already in CLAUDE.md > Data Model).

``slot_type`` is added with a temporary ``server_default='recipe'`` purely to backfill
existing rows during the SQLite batch table-copy, then the default is dropped so the column
matches ``Base.metadata.create_all()`` (project convention: Python-side defaults only, see
app/models). tests/test_migrations.py guards that parity.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1bc1ac8991f4'
down_revision: Union[str, Sequence[str], None] = '9b903c88b3aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lets batch-mode reflection give the existing inline ``UNIQUE(ingredient_name)`` (created
# unnamed by create_all()) a deterministic name so drop_constraint can target it.
NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    """Upgrade schema."""
    # --- session_recipes: nullable recipe_id + slot_type ------------------------------
    with op.batch_alter_table("session_recipes", schema=None) as batch_op:
        batch_op.alter_column("recipe_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(
            sa.Column(
                "slot_type", sa.Text(), nullable=False, server_default="recipe"
            )
        )
    # Drop the backfill-only server default so the column matches create_all().
    with op.batch_alter_table("session_recipes", schema=None) as batch_op:
        batch_op.alter_column("slot_type", existing_type=sa.Text(), server_default=None)

    # --- product_units: single-column unique -> composite unique ---------------------
    with op.batch_alter_table(
        "product_units", schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_product_units_ingredient_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_product_unit_ingredient_label", ["ingredient_name", "purchase_label"]
        )

    # --- ingredient_substitutions: new table ---------------------------------------
    op.create_table(
        "ingredient_substitutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("substitute_name", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "original_name", "substitute_name", name="uq_substitution_pair"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ingredient_substitutions")

    with op.batch_alter_table(
        "product_units", schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_product_unit_ingredient_label", type_="unique")
        batch_op.create_unique_constraint(
            "uq_product_units_ingredient_name", ["ingredient_name"]
        )

    with op.batch_alter_table("session_recipes", schema=None) as batch_op:
        batch_op.drop_column("slot_type")
        batch_op.alter_column("recipe_id", existing_type=sa.Integer(), nullable=False)
