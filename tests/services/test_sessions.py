"""Unit tests for app/services/sessions.py — direct DB session, no HTTP.
Router behaviour is covered by tests/routers/test_sessions.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import (
    LeftoversSlotCreate,
    PlanningSessionCreate,
    PlanningSessionUpdate,
    SessionOverride,
    SessionRecipeCreate,
    SessionSlotUpdate,
)
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service
from app.services.scaling import DEFAULT_TARGET_SERVINGS


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


def _recipe(db, name="Test Dish", base_servings=4):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=name,
            source_type="manual",
            base_servings=base_servings,
            ingredients=[RecipeIngredientCreate(name="thing", quantity=1, unit="g")],
        ),
        allow_duplicate=True,
    )


# --- session CRUD ---------------------------------------------------------


def test_create_session_defaults_active_and_trims_label(db):
    s = sessions_service.create_session(db, PlanningSessionCreate(label="  Week of 14 Jul  "))
    assert s.id is not None
    assert s.status == "active"
    assert s.label == "Week of 14 Jul"


def test_get_session_raises_when_missing(db):
    with pytest.raises(sessions_service.SessionNotFoundError):
        sessions_service.get_session(db, 999)


def test_list_sessions_newest_first_and_status_filter(db):
    a = sessions_service.create_session(db, PlanningSessionCreate(label="A"))
    b = sessions_service.create_session(db, PlanningSessionCreate(label="B"))
    sessions_service.archive_session(db, a.id)

    all_rows, total = sessions_service.list_sessions(db)
    assert total == 2
    assert [s.id for s in all_rows] == [b.id, a.id]  # newest first

    archived, total_archived = sessions_service.list_sessions(db, status="archived")
    assert [s.id for s in archived] == [a.id] and total_archived == 1


def test_list_sessions_pagination(db):
    for i in range(5):
        sessions_service.create_session(db, PlanningSessionCreate(label=f"S{i}"))
    page1, total = sessions_service.list_sessions(db, limit=2, offset=0)
    page2, _ = sessions_service.list_sessions(db, limit=2, offset=2)
    assert total == 5 and len(page1) == 2 and len(page2) == 2
    assert {s.id for s in page1}.isdisjoint({s.id for s in page2})


def test_update_session_label_and_status(db):
    s = sessions_service.create_session(db, PlanningSessionCreate(label="X"))
    updated = sessions_service.update_session(
        db, s.id, PlanningSessionUpdate(label="Y", status="pushed")
    )
    assert updated.label == "Y" and updated.status == "pushed"


def test_archive_session_sets_status(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    assert sessions_service.archive_session(db, s.id).status == "archived"


# --- recipe slots -------------------------------------------------------


def test_add_session_recipe_defaults_servings_and_appends_sort_order(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2 = _recipe(db, "One"), _recipe(db, "Two")

    slot1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    slot2 = sessions_service.add_session_recipe(
        db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=6, day_of_week=3)
    )

    assert slot1.slot_type == "recipe"
    assert slot1.scaled_servings == DEFAULT_TARGET_SERVINGS  # default applied
    assert slot1.sort_order == 0 and slot2.sort_order == 1
    assert slot2.scaled_servings == 6 and slot2.day_of_week == 3


def test_add_session_recipe_unknown_recipe_raises(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    with pytest.raises(recipes_service.RecipeNotFoundError):
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=12345))


def test_add_session_recipe_unknown_session_raises(db):
    r = _recipe(db)
    with pytest.raises(sessions_service.SessionNotFoundError):
        sessions_service.add_session_recipe(db, 999, SessionRecipeCreate(recipe_id=r.id))


# --- leftovers slots --------------------------------------------------


def test_add_leftovers_slot_has_no_recipe_and_zero_servings(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    slot = sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate(day_of_week=5))
    assert slot.slot_type == "leftovers"
    assert slot.recipe_id is None
    assert slot.scaled_servings == 0
    assert slot.day_of_week == 5


def test_update_slot_scaled_servings_inert_on_leftovers(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    slot = sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate())
    updated = sessions_service.update_slot(
        db, s.id, slot.id, SessionSlotUpdate(scaled_servings=8, day_of_week=2)
    )
    assert updated.scaled_servings == 0  # ignored
    assert updated.day_of_week == 2  # applied


def test_update_slot_on_recipe_changes_servings(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id))
    updated = sessions_service.update_slot(
        db, s.id, slot.id, SessionSlotUpdate(scaled_servings=2)
    )
    assert updated.scaled_servings == 2


def test_remove_slot(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id))
    sessions_service.remove_slot(db, s.id, slot.id)
    assert sessions_service.get_session(db, s.id).recipes == []


def test_get_slot_wrong_session_raises(db):
    s1 = sessions_service.create_session(db, PlanningSessionCreate())
    s2 = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s1.id, SessionRecipeCreate(recipe_id=r.id))
    with pytest.raises(sessions_service.SessionSlotNotFoundError):
        sessions_service.update_slot(db, s2.id, slot.id, SessionSlotUpdate(scaled_servings=2))


# --- reorder ---------------------------------------------------------


def test_reorder_slots_sets_sort_order_by_position(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2, r3 = _recipe(db, "A"), _recipe(db, "B"), _recipe(db, "C")
    s1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    s2 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id))
    s3 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r3.id))

    result = sessions_service.reorder_slots(db, s.id, [s3.id, s1.id, s2.id])

    assert [x.id for x in result] == [s3.id, s1.id, s2.id]
    assert [x.sort_order for x in result] == [0, 1, 2]


def test_reorder_slots_rejects_partial_or_foreign_id_list(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2 = _recipe(db, "A"), _recipe(db, "B")
    s1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id))

    with pytest.raises(sessions_service.SlotOrderMismatchError):
        sessions_service.reorder_slots(db, s.id, [s1.id])  # missing one


# --- consolidate_session (Chunk 4.6) ---------------------------------


def _recipe_with(db, name, ings, base_servings=4):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=name,
            source_type="manual",
            base_servings=base_servings,
            ingredients=[RecipeIngredientCreate(**i) for i in ings],
        ),
        allow_duplicate=True,
    )


def test_consolidate_scales_and_sums_across_recipes(db):
    from app.models.catalog import ProductUnit

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "Bol", [{"name": "beef mince", "quantity": 500, "unit": "g"}], base_servings=4)
    r2 = _recipe_with(db, "Chilli", [{"name": "beef mince", "quantity": 250, "unit": "g"}], base_servings=4)
    # r1 target 4 (x1) -> 500g; r2 target 6 (x1.5) -> 375g; total 875 -> ceil 25 -> 875
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=6))

    db.add(ProductUnit(ingredient_name="beef mince", purchase_label="500g pack", purchase_qty=500, purchase_unit="g"))
    db.commit()

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    it = items[0]
    assert it.ingredient_name == "beef mince"
    assert it.total_quantity == 875 and it.total_unit == "g"
    assert it.display_qty == "2 × 500g pack"  # ceil(875/500)=2
    assert it.purchase_qty == 1000


def test_consolidate_folds_ingredient_aliases_into_the_canonical_name(db):
    # 2026-09-10 hand-testing ("oil vs oil spray vs vegetable oil vs canola oil is stupid,
    # needs to be consolidated") -- see CLAUDE.md > Ingredient Aliases. Two recipes using
    # different but aliased names must consolidate onto one line under the canonical name,
    # and the recipes' own stored ingredient names must be untouched (dynamic resolution,
    # not a rewrite).
    from app.services import ingredient_aliases as ia_service
    from app.schemas.ingredient_aliases import IngredientAliasCreate

    ia_service.create_alias(
        db, IngredientAliasCreate(alias_name="canola oil", canonical_name="vegetable oil")
    )
    ia_service.create_alias(
        db, IngredientAliasCreate(alias_name="oil spray", canonical_name="vegetable oil")
    )

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "Stir Fry", [{"name": "canola oil", "quantity": 1, "unit": "tbsp"}])
    r2 = _recipe_with(db, "Pan Fry", [{"name": "oil spray", "quantity": 1, "unit": "tbsp"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1  # merged onto one line, not two
    assert items[0].ingredient_name == "vegetable oil"
    assert items[0].total_quantity == 2 and items[0].total_unit == "tbsp"  # 1 tbsp + 1 tbsp

    # the recipes' own data is untouched -- dynamic resolution, not a rewrite
    r1_fresh = recipes_service.get_recipe(db, r1.id)
    assert r1_fresh.ingredients[0].name == "canola oil"


def test_consolidate_applies_the_alias_equivalence_pair_transform(db):
    # 2026-09-10 ("lemon juice should be put on the list as a lemon"). An alias with a
    # quantity/unit pair renames AND converts the amount, then shows what it was converted
    # from as a note -- an approximation, unlike the plain-rename oil case above, so it's
    # surfaced rather than silent (maintainer's call).
    from app.services import ingredient_aliases as ia_service
    from app.schemas.ingredient_aliases import IngredientAliasCreate

    ia_service.create_alias(
        db,
        IngredientAliasCreate(
            alias_name="lemon juice", canonical_name="lemon",
            alias_qty=2, alias_unit="tbsp", canonical_qty=1, canonical_unit=None,
        ),
    )

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Lemon Chicken", [{"name": "lemon juice", "quantity": 2, "unit": "tbsp"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=8))
    # base_servings=4 -> target 8 -> factor 2 -> 4 tbsp lemon juice -> 4/2*1 = 2 lemons

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    item = items[0]
    assert item.ingredient_name == "lemon"
    assert item.total_quantity == 2 and item.total_unit is None
    assert item.note == "from 4 tbsp lemon juice"

    # the recipe's own ingredient is untouched
    r_fresh = recipes_service.get_recipe(db, r.id)
    assert r_fresh.ingredients[0].name == "lemon juice"
    assert r_fresh.ingredients[0].quantity == 2  # unscaled, as stored


def test_consolidate_alias_pair_falls_back_to_name_only_on_unit_mismatch(db):
    # Same alias as above, but a recipe uses "ml" instead of the configured "tbsp" -- the
    # transform is skipped (can't trust the ratio across units), falling back to a plain
    # rename that keeps the recipe's own unit.
    from app.services import ingredient_aliases as ia_service
    from app.schemas.ingredient_aliases import IngredientAliasCreate

    ia_service.create_alias(
        db,
        IngredientAliasCreate(
            alias_name="lemon juice", canonical_name="lemon",
            alias_qty=2, alias_unit="tbsp", canonical_qty=1, canonical_unit=None,
        ),
    )
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Lemon Chicken", [{"name": "lemon juice", "quantity": 30, "unit": "ml"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    item = items[0]
    assert item.ingredient_name == "lemon"  # still renamed
    assert item.total_quantity == 30 and item.total_unit == "ml"  # NOT converted
    assert item.note is None  # no conversion note when the transform didn't apply


def test_consolidate_resolves_unit_spelling_before_summing(db):
    # 2026-09-12, Ingredient Unit Handling Layer A -- "gram" is a free-text unit today
    # (consolidation._dimension() only recognises "g"/"kg" as mass), so without synonym
    # resolution this would land in a DIFFERENT bucket than "g" and get flagged needs_review
    # even though they're plainly the same thing. With the seeded gram->g synonym (via a
    # fresh row here, not relying on seed_data), the two recipes merge cleanly.
    from app.services import unit_synonyms as us_service
    from app.schemas.unit_synonyms import UnitSynonymCreate

    us_service.create_synonym(db, UnitSynonymCreate(alias_unit="gram", canonical_unit="g"))

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "Cake", [{"name": "flour", "quantity": 200, "unit": "gram"}])
    r2 = _recipe_with(db, "Bread", [{"name": "flour", "quantity": 300, "unit": "g"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1  # merged onto one line, not flagged needs_review
    assert items[0].total_quantity == 500 and items[0].total_unit == "g"


def test_consolidate_unit_synonym_lets_a_plural_typo_reconcile_too(db):
    # Plain plurals need no synonym row at all -- services/unit_synonyms.py's strip_plural()
    # handles "clove"/"cloves" generically before any table lookup.
    r1 = _recipe_with(db, "Aioli", [{"name": "garlic", "quantity": 2, "unit": "clove"}])
    r2 = _recipe_with(db, "Soup", [{"name": "garlic", "quantity": 3, "unit": "cloves"}])
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    assert items[0].total_quantity == 5 and items[0].total_unit == "clove"


def test_consolidate_coarse_ingredient_ignores_quantity_and_counts_recipe_slots(db):
    # 2026-09-12, Ingredient Unit Handling Layer D -- parsley in "10g" and "1 tbsp" would
    # normally be flagged needs_review (mass + volume). Marked coarse, it skips quantity math
    # entirely: 2 contributing recipe slots, recipes_per_pack=3 -> ceil(2/3) = 1 pack.
    from app.services import coarse_ingredients as ci_service
    from app.schemas.coarse_ingredients import CoarseIngredientCreate

    ci_service.create_coarse_ingredient(
        db, CoarseIngredientCreate(name="parsley", purchase_label="bunch", recipes_per_pack=3)
    )
    r1 = _recipe_with(db, "Chimichurri", [{"name": "parsley", "quantity": 10, "unit": "g"}])
    r2 = _recipe_with(db, "Tabbouleh", [{"name": "parsley", "quantity": 1, "unit": "tbsp"}])
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    item = items[0]
    assert item.ingredient_name == "parsley"
    assert item.needs_review is False  # would have been True without the coarse flag
    assert item.total_quantity is None and item.total_unit is None
    assert item.display_qty == "1 × bunch"
    assert item.purchase_label == "bunch"


def test_consolidate_coarse_ingredient_scales_pack_count_with_recipe_count(db):
    # 4 contributing recipes, recipes_per_pack=3 -> ceil(4/3) = 2 packs.
    from app.services import coarse_ingredients as ci_service
    from app.schemas.coarse_ingredients import CoarseIngredientCreate

    ci_service.create_coarse_ingredient(
        db, CoarseIngredientCreate(name="basil", purchase_label="bunch", recipes_per_pack=3)
    )
    s = sessions_service.create_session(db, PlanningSessionCreate())
    for i in range(4):
        r = _recipe_with(db, f"Basil Dish {i}", [{"name": "basil", "quantity": 5, "unit": "g"}])
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].display_qty == "2 × bunch"


def test_consolidate_coarse_ingredient_without_purchase_label_shows_no_count(db):
    from app.services import coarse_ingredients as ci_service
    from app.schemas.coarse_ingredients import CoarseIngredientCreate

    ci_service.create_coarse_ingredient(db, CoarseIngredientCreate(name="chives"))
    r = _recipe_with(db, "Garnish", [{"name": "chives", "quantity": 1, "unit": "tbsp"}])
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].display_qty is None and items[0].purchase_label is None


def test_consolidate_coarse_ingredient_still_populates_recipe_breakdown(db):
    # The breakdown is independent of how the total is computed -- each contributing recipe's
    # own raw quantity/unit still shows, even though the total ignores it.
    from app.services import coarse_ingredients as ci_service
    from app.schemas.coarse_ingredients import CoarseIngredientCreate

    ci_service.create_coarse_ingredient(db, CoarseIngredientCreate(name="parsley", purchase_label="bunch"))
    r1 = _recipe_with(db, "Chimichurri", [{"name": "parsley", "quantity": 10, "unit": "g"}])
    r2 = _recipe_with(db, "Tabbouleh", [{"name": "parsley", "quantity": 1, "unit": "tbsp"}])
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))

    _rows, breakdown = sessions_service.consolidate_session_with_breakdown(db, s.id)
    contributions = breakdown["parsley"]
    assert len(contributions) == 2
    by_label = {c.recipe_label: (c.quantity, c.unit) for c in contributions}
    assert by_label["Chimichurri"] == (10, "g")
    assert by_label["Tabbouleh"] == (1, "tbsp")


def test_consolidate_with_breakdown_disambiguates_duplicate_recipe_slots_by_day(db):
    # 2026-09-11, "which recipe is this ingredient from" -- the same recipe slotted into a
    # session twice (e.g. meal-prepped for two different nights) shows as two separate
    # breakdown rows, disambiguated by day when set (CLAUDE.md).
    r = _recipe_with(db, "Bolognese", [{"name": "beef mince", "quantity": 500, "unit": "g"}])
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(
        db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4, day_of_week=1)
    )
    sessions_service.add_session_recipe(
        db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=6, day_of_week=4)
    )

    _rows, breakdown = sessions_service.consolidate_session_with_breakdown(db, s.id)
    contributions = breakdown["beef mince"]
    assert len(contributions) == 2  # not merged, even though it's the same recipe
    by_label = {c.recipe_label: c for c in contributions}
    assert by_label["Bolognese (Mon)"].quantity == 500
    assert by_label["Bolognese (Thu)"].quantity == 750  # scaled x1.5 for 6 servings


def test_consolidate_leftovers_slot_contributes_nothing(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Soup", [{"name": "carrot", "quantity": 3, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate(day_of_week=3))

    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["carrot"]
    assert items[0].total_quantity == 3


def test_consolidate_flags_is_staple(db):
    from app.services import settings as settings_service
    from app.schemas.settings import StapleCreate

    settings_service.create_staple(db, StapleCreate(name="olive oil"))
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Dressing", [{"name": "olive oil", "quantity": 30, "unit": "ml"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].is_staple is True


def test_consolidate_is_a_merge_preserving_have_it_and_add_to_list(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "A", [{"name": "onion", "quantity": 2, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)

    # user marks the onion line
    onion = next(ci for ci in sessions_service.get_session(db, s.id).checklist_items if ci.ingredient_name == "onion")
    onion.have_it = "yes"
    onion.add_to_list = True
    db.commit()

    # add a second recipe and re-consolidate
    r2 = _recipe_with(db, "B", [{"name": "onion", "quantity": 1, "unit": None}, {"name": "garlic", "quantity": 2, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)

    by_name = {i.ingredient_name: i for i in items}
    assert by_name["onion"].total_quantity == 3  # recomputed
    assert by_name["onion"].have_it == "yes"  # preserved
    assert by_name["onion"].add_to_list is True  # preserved
    assert by_name["garlic"].have_it == "unknown"  # new line, default


def test_consolidate_preserves_a_manually_resolved_review_line(db):
    # 2026-09-10 hand-testing ("doesn't remember amounts under review") — a mass+volume
    # conflict the user resolved via checklist.resolve_item() must survive a later
    # re-consolidate while the same ingredient still conflicts, instead of being silently
    # re-flagged and reset. See CLAUDE.md > Scaling Logic > re-running consolidation.
    from app.services import checklist as checklist_service

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "A", [{"name": "cream", "quantity": 100, "unit": "g"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    r2 = _recipe_with(db, "B", [{"name": "cream", "quantity": 200, "unit": "ml"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)

    cream = next(i for i in items if i.ingredient_name == "cream")
    assert cream.needs_review is True

    resolved = checklist_service.resolve_item(db, s.id, cream.id, total_quantity=300, total_unit="ml")
    assert resolved.needs_review is False and resolved.total_quantity == 300

    # add an unrelated third recipe and re-consolidate — cream still conflicts (same two
    # recipes still contribute g + ml), so the user's choice must stick.
    r3 = _recipe_with(db, "C", [{"name": "rice", "quantity": 200, "unit": "g"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r3.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)
    cream = next(i for i in items if i.ingredient_name == "cream")
    assert cream.needs_review is False
    assert cream.total_quantity == 300 and cream.total_unit == "ml"

    # once the conflict genuinely goes away, the stale manual pick is not reused —
    # a fresh single-dimension total takes over normally.
    sessions_service.remove_slot(
        db, s.id, next(sl.id for sl in sessions_service.get_session(db, s.id).recipes if sl.recipe_id == r1.id)
    )
    items = sessions_service.consolidate_session(db, s.id)
    cream = next(i for i in items if i.ingredient_name == "cream")
    assert cream.needs_review is False
    assert cream.total_quantity == 200 and cream.total_unit == "ml"  # recomputed from recipe B alone


def test_consolidate_removes_lines_no_longer_needed(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "A", [{"name": "onion", "quantity": 2, "unit": None}])
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)
    assert len(sessions_service.get_session(db, s.id).checklist_items) == 1

    sessions_service.remove_slot(db, s.id, slot.id)
    items = sessions_service.consolidate_session(db, s.id)
    assert items == []


def test_consolidate_session_uses_per_recipe_resolved_ingredient(db):
    # M4: the recipe carries a confirmed swap on the ingredient itself
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Salad",
        [{"name": "bulgarian feta", "quantity": 100, "unit": "g",
          "resolved_ingredient": "regular feta"}],
    )
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["regular feta"]


def test_consolidate_session_override_beats_resolved_ingredient(db):
    # a session-only override keys off the DISPLAYED (already-resolved) name and wins for
    # this run only — nothing is written back
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Salad",
        [{"name": "bulgarian feta", "quantity": 100, "unit": "g",
          "resolved_ingredient": "regular feta"}],
    )
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(
        db, s.id,
        overrides=[SessionOverride(original_name="regular feta", substitute_name="goat cheese")],
    )
    assert [i.ingredient_name for i in items] == ["goat cheese"]

    # the recipe's own data is untouched
    reloaded = recipes_service.get_recipe(db, r.id)
    assert reloaded.ingredients[0].resolved_ingredient == "regular feta"


def test_consolidate_to_taste_item_note(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Season", [{"name": "saffron", "quantity": 1, "unit": "pinch"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=8))
    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].total_quantity is None
    assert items[0].note == "to taste"


# --- M8: substitution quantity/unit transform -----------------------------


def test_consolidate_recipe_level_transform_changes_amount_and_unit(db):
    # "2 whole corn cobs" the recipe calls for -> buy "2 cans of corn"
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Chowder",
        [{"name": "corn cobs", "quantity": 2, "unit": "cob",
          "resolved_ingredient": "canned corn",
          "resolved_quantity": 2, "resolved_unit": "can"}],
    )
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["canned corn"]
    assert (items[0].total_quantity, items[0].total_unit) == (2, "can")


def test_consolidate_recipe_level_transform_scales_with_servings(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Chowder",
        [{"name": "corn cobs", "quantity": 2, "unit": "cob",
          "resolved_ingredient": "canned corn",
          "resolved_quantity": 2, "resolved_unit": "can"}],
        base_servings=4,
    )
    # x2 servings -> the swap's absolute (2 can) scales to 4 can
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=8))
    items = sessions_service.consolidate_session(db, s.id)
    assert (items[0].total_quantity, items[0].total_unit) == (4, "can")


def test_consolidate_recipe_level_transform_scales_down_and_ceils(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Chowder",
        [{"name": "corn cobs", "quantity": 1, "unit": "cob",
          "resolved_ingredient": "canned corn",
          "resolved_quantity": 1, "resolved_unit": "can"}],
        base_servings=4,
    )
    # x0.5 -> 0.5 can, but a free-text unit ceils to a whole -> 1 can (never short)
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=2))
    items = sessions_service.consolidate_session(db, s.id)
    assert (items[0].total_quantity, items[0].total_unit) == (1, "can")


def test_consolidate_transformed_line_merges_with_a_plain_line_of_the_same_name(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(
        db,
        "Chowder",
        [{"name": "corn cobs", "quantity": 2, "unit": "cob",
          "resolved_ingredient": "canned corn",
          "resolved_quantity": 2, "resolved_unit": "can"}],
    )
    r2 = _recipe_with(db, "Salsa", [{"name": "canned corn", "quantity": 1, "unit": "can"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["canned corn"]
    assert (items[0].total_quantity, items[0].total_unit) == (3, "can")


def test_consolidate_session_override_carries_an_equivalence_pair(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Chowder", [{"name": "corn", "quantity": 4, "unit": "cob"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    items = sessions_service.consolidate_session(
        db, s.id,
        overrides=[SessionOverride(
            original_name="corn", substitute_name="canned corn",
            original_qty=2, original_unit="cob", substitute_qty=1, substitute_unit="can",
        )],
    )
    # 4 cob / 2 * 1 = 2 can
    assert [i.ingredient_name for i in items] == ["canned corn"]
    assert (items[0].total_quantity, items[0].total_unit) == (2, "can")


def test_consolidate_session_override_pair_falls_back_to_name_only_on_unit_mismatch(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Chowder", [{"name": "corn", "quantity": 500, "unit": "g"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    items = sessions_service.consolidate_session(
        db, s.id,
        overrides=[SessionOverride(
            original_name="corn", substitute_name="canned corn",
            original_qty=2, original_unit="cob", substitute_qty=1, substitute_unit="can",
        )],
    )
    # override unit "cob" != line unit "g" -> rename only, quantity/unit unchanged
    assert [i.ingredient_name for i in items] == ["canned corn"]
    assert (items[0].total_quantity, items[0].total_unit) == (500, "g")


def test_consolidate_session_override_pair_skipped_for_to_taste_line(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Season", [{"name": "saffron", "quantity": 1, "unit": "pinch"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=8))
    items = sessions_service.consolidate_session(
        db, s.id,
        overrides=[SessionOverride(
            original_name="saffron", substitute_name="saffron threads",
            original_qty=1, original_unit="pinch", substitute_qty=2, substitute_unit="g",
        )],
    )
    # renamed, but still a "to taste" line — no number, no ratio applied
    assert [i.ingredient_name for i in items] == ["saffron threads"]
    assert items[0].total_quantity is None and items[0].note == "to taste"
