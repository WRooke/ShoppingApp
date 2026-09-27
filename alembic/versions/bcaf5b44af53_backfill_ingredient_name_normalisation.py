"""backfill ingredient name normalisation across reference tables

Revision ID: bcaf5b44af53
Revises: c920cac31b6a
Create Date: 2026-09-27

F1.5 of the ingredient-name-matching plan. `app/services/text_normalize.py`'s
`normalise_ingredient_name()` (plural-stripping + hyphen-folding) is now the grouping/matching
key used everywhere an ingredient name is compared — but existing rows in the 5 reference
tables below were written under the old, narrower lowercase+whitespace-only normalisation, so
some no longer match what a freshly-consolidated shopping-list line looks like (e.g. the
confirmed real "chicken thigh"/"chicken thighs" duplicate in `product_units`).

**CLAUDE.md non-negotiable rule 3 (data loss on prod is never acceptable, added 2026-09-27):
this migration never deletes a row, in any table, under any circumstance.** For every
collision (2+ existing rows that would now normalise to the same value under a column with a
uniqueness constraint), exactly ONE row is renamed to the new normalised value; every other row
in that collision group is left **completely untouched** — same id, same literal old value,
same every other column. It simply stops being matched by the new normalisation going forward,
exactly as unreachable as an already-orphaned row is today (e.g. the yoghurt `product_units`
rows F0's migration already found) — never deleted, never silently merged away. Every
left-behind row is printed in this migration's own output as a plain report for the maintainer
to reconcile by hand via the existing Settings CRUD, at their own pace — not auto-applied here.

`staples.name` is deliberately NOT included — the `staples` feature was retired at the
application layer (see docs/decision-history.md > "Staples — usefulness assessment"); the table
has no live matching path left, so renaming it has no functional benefit.

The normalisation logic below is a FROZEN SNAPSHOT of `app/services/text_normalize.py` as of
this migration — do not refactor this to import the live module (a migration must stay correct
independent of future changes to the app's own code). It DOES import `inflect` directly — that's
a stable, version-pinned third-party dependency (see requirements.txt), not app code that could
drift out from under this migration, the same standing as this file's own `sqlalchemy`/`alembic`
imports.
"""
from __future__ import annotations

import re
from typing import Sequence, Union

import inflect
from alembic import op
import sqlalchemy as sa


revision: str = "bcaf5b44af53"
down_revision: Union[str, Sequence[str], None] = "c920cac31b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- frozen snapshot of app/services/text_normalize.py (2026-09-27, post-`inflect`-adoption
# revision — see that module's own docstring for the full empirical reasoning behind this exact
# hand-rolled/`inflect` split, including the two real `inflect` bugs it works around: a blind
# "-us" ending mishandled by both the original hand-rolled rule AND `inflect`'s own fallback, and
# `inflect`'s much more aggressive "-ss"/short-word fallback that this hand-rolled ladder's
# existing `not endswith("ss")` + `len > 3` guards already avoid exposing it to). ------------

_HYPHEN_FAMILY = re.compile(r"[-‐‑‒–—]")
_US_WHITELIST = {"asparagus", "couscous", "hummus", "citrus"}
_INFLECT = inflect.engine()


def _base_norm(name: str) -> str:
    folded = _HYPHEN_FAMILY.sub(" ", name.strip().lower())
    return " ".join(folded.split())


def _singularise_word(word: str) -> str:
    if word in _US_WHITELIST:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ves"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    if not word.endswith("s"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    return word


def _singularise(s: str) -> str:
    head, sep, tail = s.rpartition(" ")
    return f"{head}{sep}{_singularise_word(tail)}"


def _normalise(name: str) -> str:
    return _singularise(_base_norm(name))


# --- generic collision-safe rename helper ------------------------------------------------


def _rename_one_per_group(
    conn,
    table_name: str,
    id_col: str,
    name_col: str,
    rows: list[dict],
    *,
    group_key,
    new_value,
    prefer,
) -> None:
    """Group `rows` (each a dict of the full row) by an opaque `group_key(row)` (which may be a
    composite of more than just `name_col`, e.g. product_units' (name, purchase_label) pair —
    the actual UNIQUE constraint). `new_value(row)` computes the normalised value to write into
    `name_col` for whichever row is kept — deliberately a SEPARATE function from `group_key`,
    since the grouping key and the column value are not always the same string (a bug caught
    while writing this migration: an earlier draft wrote the composite grouping key itself into
    `name_col`). For a group of 1, rename straight to the normalised value. For a group of 2+,
    rename only the row `prefer` picks as the "kept" one; every other row is left completely
    untouched (never renamed, never deleted) and printed as a left-behind report line."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)

    table = sa.table(table_name, sa.column(id_col, sa.Integer), sa.column(name_col, sa.Text))

    for key, group in groups.items():
        target = new_value(group[0])
        if len(group) == 1:
            row = group[0]
            if row[name_col] != target:
                conn.execute(
                    table.update()
                    .where(table.c[id_col] == row[id_col])
                    .values(**{name_col: target})
                )
            continue

        # A row that already exactly equals the target MUST be the one kept, regardless of
        # `prefer`'s tie-break — real bug caught testing this migration: if `prefer` picked a
        # DIFFERENT row while another group member already held the target value verbatim,
        # renaming the preferred row onto that same value hit the table's own UNIQUE
        # constraint (e.g. "ginger beer" already present, "ginger beers" separately renamed
        # onto it). No ambiguity to resolve in that case — the already-correct row is kept.
        already_correct = [r for r in group if r[name_col] == target]
        kept = already_correct[0] if already_correct else prefer(group)
        if kept[name_col] != target:
            conn.execute(
                table.update()
                .where(table.c[id_col] == kept[id_col])
                .values(**{name_col: target})
            )
        for row in group:
            if row[id_col] == kept[id_col]:
                continue
            print(
                f"[ingredient-name-backfill] LEFT BEHIND: {table_name}.{id_col}={row[id_col]} "
                f"{name_col}={row[name_col]!r} (would normalise to {target!r}, but "
                f"{table_name}.{id_col}={kept[id_col]} already took that value) — "
                f"review manually via Settings."
            )


def _prefer_not_preseeded_then_lowest_id(group: list[dict]) -> dict:
    not_preseeded = [r for r in group if not r.get("is_preseeded")]
    pool = not_preseeded or group
    return min(pool, key=lambda r: r["id"])


def _prefer_last_used_then_lowest_id(group: list[dict]) -> dict:
    with_use = [r for r in group if r.get("last_used_at") is not None]
    if with_use:
        return max(with_use, key=lambda r: r["last_used_at"])
    return min(group, key=lambda r: r["id"])


def _prefer_non_null_then_lowest_id(group: list[dict], col: str) -> dict:
    with_value = [r for r in group if r.get(col) is not None]
    pool = with_value or group
    return min(pool, key=lambda r: r["id"])


# --- per-table upgrades ---------------------------------------------------------------


def _upgrade_product_units(conn) -> None:
    rows = [dict(r._mapping) for r in conn.execute(sa.text("SELECT * FROM product_units"))]
    # Collision key is the PAIR (normalised name, purchase_label) — the actual UNIQUE
    # constraint — not the name alone; the value written back is just the normalised name.
    _rename_one_per_group(
        conn, "product_units", "id", "ingredient_name", rows,
        group_key=lambda r: _normalise(r["ingredient_name"]) + "\x00" + r["purchase_label"],
        new_value=lambda r: _normalise(r["ingredient_name"]),
        prefer=_prefer_not_preseeded_then_lowest_id,
    )


def _upgrade_coarse_ingredients(conn) -> None:
    rows = [dict(r._mapping) for r in conn.execute(sa.text("SELECT * FROM coarse_ingredients"))]
    # Note (differs from product_units/usual_items): a left-behind row here may carry a
    # genuinely different recipes_per_pack/purchase_label config, a household judgement call
    # never auto-resolved — flagged in the generic report below like any other left-behind row.
    _rename_one_per_group(
        conn, "coarse_ingredients", "id", "name", rows,
        group_key=lambda r: _normalise(r["name"]),
        new_value=lambda r: _normalise(r["name"]),
        prefer=lambda group: min(group, key=lambda r: r["id"]),
    )


def _upgrade_usual_items(conn) -> None:
    rows = [dict(r._mapping) for r in conn.execute(sa.text("SELECT * FROM usual_items"))]
    _rename_one_per_group(
        conn, "usual_items", "id", "name", rows,
        group_key=lambda r: _normalise(r["name"]),
        new_value=lambda r: _normalise(r["name"]),
        prefer=lambda group: _prefer_non_null_then_lowest_id(group, "last_added_at"),
    )


def _upgrade_ingredient_aliases(conn) -> None:
    rows = [dict(r._mapping) for r in conn.execute(sa.text("SELECT * FROM ingredient_aliases"))]
    table = sa.table(
        "ingredient_aliases",
        sa.column("id", sa.Integer),
        sa.column("alias_name", sa.Text),
        sa.column("canonical_name", sa.Text),
    )
    by_id = {r["id"]: r for r in rows}

    # --- alias_name: UNIQUE, same rename-one-keep-others pattern as product_units ---
    alias_groups: dict[str, list[dict]] = {}
    for row in rows:
        alias_groups.setdefault(_normalise(row["alias_name"]), []).append(row)
    final_alias_name: dict[int, str] = {}
    for new_value, group in alias_groups.items():
        if len(group) == 1:
            final_alias_name[group[0]["id"]] = new_value
            continue
        # A row already exactly at the target MUST be the one kept — same fix as the generic
        # helper's "already_correct" guard (a real bug caught testing this migration: picking
        # a different row via a tie-break while another already held the target value verbatim
        # hits the table's own UNIQUE constraint).
        already_correct = [r for r in group if r["alias_name"] == new_value]
        kept = already_correct[0] if already_correct else min(group, key=lambda r: r["id"])
        final_alias_name[kept["id"]] = new_value
        for row in group:
            if row["id"] != kept["id"]:
                final_alias_name[row["id"]] = row["alias_name"]  # left untouched
                print(
                    f"[ingredient-name-backfill] LEFT BEHIND: ingredient_aliases.id={row['id']} "
                    f"alias_name={row['alias_name']!r} (would normalise to {new_value!r}, but "
                    f"ingredient_aliases.id={kept['id']} already took that value) — review "
                    f"manually via Settings."
                )

    # --- canonical_name: NOT unique, so every distinct value can be renamed freely; the
    # only thing to guard is a row ending up with alias_name == canonical_name. ---
    canon_groups: dict[str, list[str]] = {}  # normalised -> [distinct raw values]
    for row in rows:
        raw = row["canonical_name"]
        norm = _normalise(raw)
        canon_groups.setdefault(norm, [])
        if raw not in canon_groups[norm]:
            canon_groups[norm].append(raw)
    raw_to_norm_canonical = {raw: norm for norm, raws in canon_groups.items() for raw in raws}

    for row in rows:
        rid = row["id"]
        new_alias = final_alias_name[rid]
        new_canonical = raw_to_norm_canonical[row["canonical_name"]]
        if new_alias == new_canonical:
            # Self-alias guard — revert BOTH sides for THIS row, leaving it completely
            # untouched (a real bug caught testing this migration: reverting only
            # canonical_name still left the alias_name rename applied, so the row ended up
            # self-aliased anyway via the other column).
            print(
                f"[ingredient-name-backfill] LEFT BEHIND: ingredient_aliases.id={rid} "
                f"alias_name={row['alias_name']!r} canonical_name={row['canonical_name']!r} "
                f"kept fully as-is (normalising would make alias_name == canonical_name) — "
                f"review manually via Settings."
            )
            new_alias = row["alias_name"]
            new_canonical = row["canonical_name"]
        if new_alias != row["alias_name"]:
            conn.execute(table.update().where(table.c.id == rid).values(alias_name=new_alias))
        if new_canonical != row["canonical_name"]:
            conn.execute(
                table.update().where(table.c.id == rid).values(canonical_name=new_canonical)
            )


def _upgrade_remembered_substitutions(conn) -> None:
    rows = [dict(r._mapping) for r in conn.execute(sa.text("SELECT * FROM remembered_substitutions"))]
    table = sa.table(
        "remembered_substitutions",
        sa.column("id", sa.Integer),
        sa.column("original_name", sa.Text),
        sa.column("substitute_name", sa.Text),
    )
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = _normalise(row["original_name"]) + "\x00" + _normalise(row["substitute_name"])
        groups.setdefault(key, []).append(row)

    for key, group in groups.items():
        new_original, new_substitute = key.split("\x00")
        if new_original == new_substitute:
            for row in group:
                print(
                    f"[ingredient-name-backfill] LEFT BEHIND: remembered_substitutions."
                    f"id={row['id']} original_name={row['original_name']!r} "
                    f"substitute_name={row['substitute_name']!r} kept as-is (normalising would "
                    f"make original_name == substitute_name) — review manually via Settings."
                )
            continue
        if len(group) == 1:
            row = group[0]
            if row["original_name"] != new_original or row["substitute_name"] != new_substitute:
                conn.execute(
                    table.update()
                    .where(table.c.id == row["id"])
                    .values(original_name=new_original, substitute_name=new_substitute)
                )
            continue
        # A row already exactly at the target pair MUST be the one kept — same fix as the
        # generic helper's "already_correct" guard (see product_units/usual_items).
        already_correct = [
            r for r in group
            if r["original_name"] == new_original and r["substitute_name"] == new_substitute
        ]
        kept = already_correct[0] if already_correct else _prefer_last_used_then_lowest_id(group)
        if kept["original_name"] != new_original or kept["substitute_name"] != new_substitute:
            conn.execute(
                table.update()
                .where(table.c.id == kept["id"])
                .values(original_name=new_original, substitute_name=new_substitute)
            )
        for row in group:
            if row["id"] == kept["id"]:
                continue
            print(
                f"[ingredient-name-backfill] LEFT BEHIND: remembered_substitutions.id={row['id']} "
                f"original_name={row['original_name']!r} substitute_name={row['substitute_name']!r} "
                f"(would normalise to {new_original!r} -> {new_substitute!r}, but "
                f"remembered_substitutions.id={kept['id']} already took that pair) — review "
                f"manually via Settings."
            )


def upgrade() -> None:
    conn = op.get_bind()
    _upgrade_product_units(conn)
    _upgrade_coarse_ingredients(conn)
    _upgrade_usual_items(conn)
    _upgrade_ingredient_aliases(conn)
    _upgrade_remembered_substitutions(conn)


def downgrade() -> None:
    # Documented no-op — nothing was ever deleted by upgrade(), so there is no data to
    # recover; renaming back to the exact prior string isn't tracked, same precedent as this
    # plan's other data migrations (see F0's c920cac31b6a).
    pass
