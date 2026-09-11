"""``product_units``, ``staples``, ``remembered_substitutions``, ``ingredient_aliases``,
``unit_synonyms`` and ``coarse_ingredients`` — the editable reference catalogue managed from
the Settings page. (``remembered_substitutions`` was ``ingredient_substitutions`` with an
auto-applying ``is_default`` until Phase 3.9 M4.)"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text, UniqueConstraint

from app.database import Base, utcnow


class ProductUnit(Base):
    __tablename__ = "product_units"
    # Phase 4 (Chunk 4.1): an ingredient can be sold in more than one pack size, so the
    # uniqueness moved from ``ingredient_name`` alone to (ingredient_name, purchase_label).
    # See CLAUDE.md > Data Model > product_units and > Scaling Logic > Purchase unit resolution.
    __table_args__ = (
        UniqueConstraint(
            "ingredient_name", "purchase_label", name="uq_product_unit_ingredient_label"
        ),
    )

    id = Column(Integer, primary_key=True)
    ingredient_name = Column(Text, nullable=False)  # matches recipe_ingredients.name
    purchase_label = Column(Text, nullable=False)  # e.g. "dozen", "500g pack"
    purchase_qty = Column(Float, nullable=False)
    purchase_unit = Column(Text, nullable=True)  # e.g. "g", "L", "each"
    notes = Column(Text, nullable=True)
    is_preseeded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Staple(Base):
    __tablename__ = "staples"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class UsualItem(Base):
    """"The usuals" (Phase 5 Chunk 5.4) — recurring non-recipe household items bought on a
    day-based schedule, independent of meal planning. Distinct from ``Staple`` (recipe
    ingredients assumed on-hand). Surfaced on the checklist as its own group only when *due*:
    ``last_added_at IS NULL`` or ``last_added_at + cadence_days`` has passed. Cadence is in
    days, not sessions — an ad-hoc single-recipe session is an unreliable clock. Managed in
    Settings, seeded empty. See CLAUDE.md > Checklist Screen Logic > "The usuals" and >
    Data Model > usual_items.
    """

    __tablename__ = "usual_items"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    notes = Column(Text, nullable=True)
    cadence_days = Column(Integer, nullable=False)  # "buy roughly every N days"
    last_added_at = Column(DateTime, nullable=True)  # stamped when actually pushed to AnyList
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class RememberedSubstitution(Base):
    """A quick-pick library entry (Phase 3.9 M4 — was ``IngredientSubstitution`` with an
    ``is_default`` that auto-applied; that's gone). It NEVER applies a swap on its own — it
    only pre-fills / top-ranks the suggestion in a per-recipe confirm UI. Every row exists
    because the user ticked "save this swap" at capture review, the recipe editor, or after a
    planning swap. See CLAUDE.md > AI Provider Migration > Ingredient Substitution Flagging
    and > Data Model > remembered_substitutions.
    """

    __tablename__ = "remembered_substitutions"
    __table_args__ = (
        UniqueConstraint("original_name", "substitute_name", name="uq_substitution_pair"),
    )

    id = Column(Integer, primary_key=True)
    original_name = Column(Text, nullable=False)  # normalised lowercase, matches recipe_ingredients.name
    substitute_name = Column(Text, nullable=False)  # normalised lowercase (freetext; 1:many stored verbatim)
    note = Column(Text, nullable=True)  # pre-fills recipe_ingredients.substitution_note
    last_used_at = Column(DateTime, nullable=True)  # quick-pick ordering, most-recent first
    # Quantity/unit equivalence (Phase 3.9 M8 — see CLAUDE.md > AI Provider Migration >
    # Ingredient Substitution Flagging, and > Data Model > remembered_substitutions).
    # "original_qty original_unit ~= substitute_qty substitute_unit", e.g. 2 "cob" ~= 2 "can".
    # A ratio the quick-pick uses to PRE-FILL recipe_ingredients' resolved_quantity /
    # resolved_unit for whatever amount that recipe calls for; the user still confirms. All
    # four NULL = a name-only quick-pick (unchanged from M4). Never auto-applied. original_qty
    # must be > 0 when set.
    original_qty = Column(Float, nullable=True)
    original_unit = Column(Text, nullable=True)
    substitute_qty = Column(Float, nullable=True)
    substitute_unit = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class IngredientAlias(Base):
    """"Same shopping item" grouping (2026-09-10, generalised from a hand-testing complaint
    about oil variants — "canola oil"/"vegetable oil"/"oil spray" reading as separate lines).

    Deliberately a DIFFERENT concept from ``RememberedSubstitution`` above, not a variant of
    it — see CLAUDE.md > Ingredient Aliases for the full distinction. In short: a substitution
    is "I don't want to buy X, buy Y instead" (a deliberate, per-recipe, confirmed swap,
    because the two are genuinely different products). An alias is "X and Y are the same
    thing to my household" (no swap, no confirmation, no recipe-level record — it's a pure
    relabelling applied uniformly wherever the ingredient name is used for grouping).

    ``alias_name`` -> ``canonical_name``, both normalised lowercase. Multiple aliases may
    point at the same canonical name (that's how a group forms); a canonical name is never
    itself required to appear as a real ingredient anywhere. Chains are flattened at write
    time (services/ingredient_aliases.py), not followed at read time — every row's
    ``canonical_name`` is always a final target, never another alias.

    Resolved dynamically at consolidation time (services/session_consolidation.py), NOT
    written into ``recipe_ingredients.name`` — this is what makes adding a new alias benefit
    every existing recipe immediately, and keeps a recipe's own data showing what it actually
    said. See CLAUDE.md > Ingredient Aliases and > Data Model > ingredient_aliases.

    2026-09-10 (lemon/lime juice -> whole fruit): an alias can optionally carry a quantity/
    unit equivalence pair too ("2 tbsp lemon juice ~= 1 lemon"), the same shape
    ``RememberedSubstitution`` already has for its M8 transform. Unlike that pair,
    ``canonical_unit`` may be blank — the canonical side is very often a bare discrete count
    ("1 lemon"), same as ``recipe_ingredients.unit`` being NULL for unitless produce. All four
    of qty/unit are still both-or-neither as a *pair* (``alias_qty``/``canonical_qty`` set
    together or not at all); see ``schemas/ingredient_aliases.py`` for the exact rule.
    """

    __tablename__ = "ingredient_aliases"

    id = Column(Integer, primary_key=True)
    alias_name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    canonical_name = Column(Text, nullable=False, index=True)  # normalised lowercase
    note = Column(Text, nullable=True)  # freetext, e.g. "roughly 3 tbsp juice per lemon"
    alias_qty = Column(Float, nullable=True)
    alias_unit = Column(Text, nullable=True)
    canonical_qty = Column(Float, nullable=True)
    canonical_unit = Column(Text, nullable=True)  # nullable -- the canonical side is often a bare count
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class UnitSynonym(Base):
    """Unit-spelling canonicalisation (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling
    > Layer A). The plainer sibling of ``IngredientAlias`` above — same "warn/merge, no admin"
    spirit, but for the *spelling* of a unit rather than the *identity* of an ingredient, and
    with no equivalence pair: a unit doesn't need a quantity conversion to its own synonym
    ("tablespoon" just *is* "tbsp", not "N tablespoon ~= M tbsp").

    Resolved dynamically at consolidation time (services/session_consolidation.py), same
    point and reasoning as ``IngredientAlias`` — a Settings-editable synonym added later
    should retroactively fix recipes saved before it existed, which rewriting
    ``recipe_ingredients.unit`` at save time couldn't do. A generic, tableless pluralisation-
    strip rule (``services/unit_synonyms.py > strip_plural()``) runs first and handles most
    discrete-unit plurals (clove/cloves, bunch/bunches) for free — this table only needs
    entries for genuine word-form differences the strip rule can't derive (gram(s) -> g,
    tablespoon(s)/tbs -> tbsp), which is why it's a small, one-time, universal seed rather
    than per-household admin.
    """

    __tablename__ = "unit_synonyms"

    id = Column(Integer, primary_key=True)
    alias_unit = Column(Text, nullable=False, unique=True)  # normalised lowercase, post-strip
    canonical_unit = Column(Text, nullable=False)  # normalised lowercase
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class CoarseIngredient(Base):
    """An ingredient that skips the normal sum -> normalise -> round consolidation pipeline
    entirely because precision is pointless for it (2026-09-12 — "10g + 1 tbsp of parsley is
    probably just a bunch, I'm not out shopping for parsley by the gram and tablespoon"). See
    CLAUDE.md > Ingredient Unit Handling > Layer D.

    Deliberately its own table rather than a flag on ``ProductUnit`` — a coarse ingredient's
    "pack" concept (a plain purchase label + a recipe-count divisor) is simpler than, and
    orthogonal to, ``ProductUnit``'s precise weight/volume pack-size resolution, which a
    coarse ingredient never runs. Checked against an ingredient's FINAL resolved name (after
    substitution + ``IngredientAlias`` resolution), the same point ``is_staple`` is checked.
    """

    __tablename__ = "coarse_ingredients"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    purchase_label = Column(Text, nullable=True)  # e.g. "bunch"; NULL = just "needed", no count
    recipes_per_pack = Column(Integer, nullable=False, default=3)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
