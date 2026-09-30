"""session_ingredient_merges generalised beyond "merge" (chunk 7.5)

Revision ID: c7c1ecd37ec8
Revises: 235522e3b75f
Create Date: 2026-09-30

Checklist ingredient panel (Review→Checklist merge, chunk 7.5) — rather than a sibling table
per new session-scoped "this list only" edit type, this generalises the existing Fix 3
`session_ingredient_merges` table with a `kind` discriminator ('merge' | 'substitute' |
'pack_size' | 'coarse') plus the extra nullable columns `pack_size`/`coarse` need
(`purchase_label`/`purchase_qty`/`purchase_unit`/`recipes_per_pack` — disjoint from
`canonical_name`/the alias-pair columns `merge`/`substitute` use, not overloaded onto them).
See app/models/planning.py::SessionIngredientMerge's docstring for the full per-kind field
shape, and docs/checklist-and-shopping.md's "Review→Checklist merge — resolution" note.

Existing rows are all `kind='merge'` (the only kind that existed before this migration) —
backfilled via the column's own `server_default`, not a data migration step. `canonical_name`
moves from NOT NULL to nullable (only merge/substitute use it; pack_size/coarse don't),
enforced per-kind at the schema layer instead. The unique constraint widens from
(session_id, member_name) to (session_id, member_name, kind), since a single ingredient can
now hold at most one row PER kind, not one row total. render_as_batch handles the SQLite
table rebuild this constraint change needs.

Non-destructive per CLAUDE.md rule 3: adds nullable columns, backfills every existing row's
new `kind` via its own default (no explicit UPDATE needed), and only widens (never narrows)
what the unique constraint allows. tests/test_migrations.py keeps `upgrade head` ==
`create_all()`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7c1ecd37ec8"
down_revision: Union[str, Sequence[str], None] = "235522e3b75f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The original table's UniqueConstraint("session_id", "member_name") was created with no
# explicit name (`sa.UniqueConstraint(...)`, no `name=` kwarg) — reflected back as name=None
# on the real prod DB (confirmed: sa.inspect(engine).get_unique_constraints() against a
# pre-migration DB). Batch mode's own drop_constraint needs a real name to target; a
# `naming_convention` assigns reflection a deterministic one when the real name is None, so it
# can be dropped by that generated name below. Looked up dynamically (not hardcoded) so this
# also works unchanged against a DB where the constraint already carries a real name for some
# other reason (e.g. a prior downgrade of this same migration, tested locally) — this migration
# runs once against the real, never-downgraded prod DB, but staying name-agnostic costs nothing
# and avoids a brittle guess.
_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_N_name)s"}


def _existing_unique_constraint_name(table_name: str) -> str:
    bind = op.get_bind()
    constraints = sa.inspect(bind).get_unique_constraints(table_name)
    existing = next((c for c in constraints if c["column_names"] == ["session_id", "member_name"]), None)
    if existing is None:
        raise RuntimeError(f"expected a (session_id, member_name) unique constraint on {table_name}")
    if existing["name"]:
        return existing["name"]
    # Unnamed — the naming_convention below will assign this exact generated name on reflection.
    return _NAMING_CONVENTION["uq"] % {"table_name": table_name, "column_0_N_name": "session_id_member_name"}


def upgrade() -> None:
    constraint_name = _existing_unique_constraint_name("session_ingredient_merges")
    with op.batch_alter_table(
        "session_ingredient_merges",
        schema=None,
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.Text(), nullable=False, server_default="merge")
        )
        batch_op.alter_column("canonical_name", existing_type=sa.Text(), nullable=True)
        batch_op.add_column(sa.Column("purchase_label", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("purchase_qty", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("purchase_unit", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("recipes_per_pack", sa.Integer(), nullable=True))
        batch_op.drop_constraint(constraint_name, type_="unique")
        batch_op.create_unique_constraint(
            "uq_session_ingredient_merges_session_member_kind",
            ["session_id", "member_name", "kind"],
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "session_ingredient_merges", schema=None, recreate="always"
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_session_ingredient_merges_session_member_kind", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_session_ingredient_merges_session_member", ["session_id", "member_name"]
        )
        batch_op.drop_column("recipes_per_pack")
        batch_op.drop_column("purchase_unit")
        batch_op.drop_column("purchase_qty")
        batch_op.drop_column("purchase_label")
        batch_op.alter_column("canonical_name", existing_type=sa.Text(), nullable=False)
        batch_op.drop_column("kind")
