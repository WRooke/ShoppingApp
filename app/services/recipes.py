"""Recipe library business logic — recipe CRUD (soft delete) and nested
recipe_ingredients CRUD. Plain Python / SQLAlchemy only, no `fastapi` import
here — see CLAUDE.md > Code Architecture & Maintainability. Routers
(app/routers/recipes.py) call these functions and translate the exceptions
below into the {"ok": false, "error": ...} envelope.
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.recipes import Recipe, RecipeIngredient
from app.schemas.capture import CaptureConfirmRequest
from app.schemas.recipes import (
    RecipeCreate,
    RecipeIngredientCreate,
    RecipeIngredientUpdate,
    RecipeUpdate,
)
from app.services import product_sections

logger = logging.getLogger(__name__)


class RecipeNotFoundError(Exception):
    def __init__(self, recipe_id: int) -> None:
        self.recipe_id = recipe_id
        super().__init__(f"Recipe {recipe_id} not found")


class IngredientNotFoundError(Exception):
    def __init__(self, recipe_id: int, ingredient_id: int) -> None:
        self.recipe_id = recipe_id
        self.ingredient_id = ingredient_id
        super().__init__(f"Ingredient {ingredient_id} not found on recipe {recipe_id}")


def _norm_resolved(value: str | None) -> str | None:
    """Normalise a resolved_ingredient the same way as an ingredient name (lowercase, trim);
    blank -> None (clears the substitution). Phase 3.9 M4."""
    if value is None:
        return None
    trimmed = " ".join(value.strip().lower().split())
    return trimmed or None


def _resolved_transform(
    resolved_ingredient: str | None,
    resolved_quantity: float | None,
    resolved_unit: str | None,
) -> tuple[float | None, str | None]:
    """The M8 (resolved_quantity, resolved_unit) pair, normalised and gated: they only mean
    anything alongside a name swap, so if `resolved_ingredient` normalises away to None the
    transform is dropped too (CLAUDE.md > AI Provider Migration > Ingredient Substitution
    Flagging > Quantity/unit transform). Unit lowercased/trimmed to match consolidation."""
    if not resolved_ingredient or resolved_quantity is None:
        return None, None
    unit = _norm_resolved(resolved_unit)
    return resolved_quantity, unit


def _normalise_ingredient_name(name: str) -> str:
    """Lowercase + strip whitespace — see CLAUDE.md > Ingredient Normalisation.
    Automatic synonym matching ("green onion" vs "spring onion") is explicitly
    NOT implemented here — deferred, user review is the normalisation for now."""
    return name.strip().lower()


def _clean_optional_text(value: str | None) -> str | None:
    """Trim; a blank/whitespace-only string means 'not set' (-> None). Used for the
    optional free-text source-provenance fields on create — see CLAUDE.md > Data Model >
    recipes source provenance. (update_recipe stores what it's given via its exclude_unset
    loop; only the create paths normalise here.)"""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


# --- duplicate recipe prevention ---------------------------------------------
#
# Implementation moved to services/recipe_duplicates.py at the Phase 3.9 M-review (CLAUDE.md
# > Code Architecture > File size). Re-exported here so `recipes_service.<name>` call sites
# and imports (app/main.py, app/routers/recipes.py, tests) keep resolving unchanged.
from app.services.recipe_duplicates import (  # noqa: E402,F401
    DuplicateMatch,
    PossibleDuplicateRecipeError,
    find_possible_duplicates,
    find_recipe_by_source_url,
    raise_if_duplicate as _raise_if_duplicate,
)


# --- recipes ---------------------------------------------------------------


def create_recipe(db: Session, data: RecipeCreate, *, allow_duplicate: bool = False) -> Recipe:
    """Create a recipe + its nested ingredients in one commit. Ingredient names are
    normalised lowercase; `resolved_ingredient` / `substitution_note` (the per-recipe swap,
    Phase 3.9 M4) pass through normalised. Unless `allow_duplicate`, raises
    PossibleDuplicateRecipeError first if this looks like a recipe already in the library
    (CLAUDE.md > Duplicate Recipe Prevention)."""
    if not allow_duplicate:
        _raise_if_duplicate(db, data)
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        source_book=_clean_optional_text(data.source_book),
        source_page=_clean_optional_text(data.source_page),
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    for i, ing in enumerate(data.ingredients):
        resolved = _norm_resolved(ing.resolved_ingredient)
        rq, ru = _resolved_transform(resolved, ing.resolved_quantity, ing.resolved_unit)
        recipe.ingredients.append(
            RecipeIngredient(
                name=_normalise_ingredient_name(ing.name),
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=ing.sort_order or i,
                resolved_ingredient=resolved,
                substitution_note=_clean_optional_text(ing.substitution_note),
                resolved_quantity=rq,
                resolved_unit=ru,
            )
        )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    logger.info(
        "Recipe created: id=%s name=%r ingredients=%d",
        recipe.id,
        recipe.name,
        len(recipe.ingredients),
    )
    return recipe


def create_recipe_from_capture(
    db: Session, data: CaptureConfirmRequest, *, allow_duplicate: bool = False
) -> Recipe:
    """Saves a reviewed recipe capture (Chunk 3.4 — see CLAUDE.md > Build Phases > Phase 3).
    Differs from create_recipe() only in also writing product_sections rows for any
    ingredient carrying a suggested_section — see services/product_sections.py."""
    if not allow_duplicate:
        _raise_if_duplicate(db, data)
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        source_book=_clean_optional_text(data.source_book),
        source_page=_clean_optional_text(data.source_page),
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    ingredient_sections: dict[str, str] = {}
    confirmed_swaps: list[tuple[str, str]] = []
    for i, ing in enumerate(data.ingredients):
        normalised_name = _normalise_ingredient_name(ing.name)
        resolved = _norm_resolved(ing.resolved_ingredient)
        rq, ru = _resolved_transform(resolved, ing.resolved_quantity, ing.resolved_unit)
        recipe.ingredients.append(
            RecipeIngredient(
                name=normalised_name,
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=i,
                resolved_ingredient=resolved,
                substitution_note=_clean_optional_text(ing.substitution_note),
                resolved_quantity=rq,
                resolved_unit=ru,
            )
        )
        if ing.suggested_section:
            ingredient_sections[normalised_name] = ing.suggested_section
        if resolved:
            confirmed_swaps.append((normalised_name, resolved))

    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    logger.info(
        "Recipe created from capture: id=%s name=%r source_type=%s ingredients=%d",
        recipe.id,
        recipe.name,
        recipe.source_type,
        len(recipe.ingredients),
    )

    product_sections.tag_suggested_sections(db, ingredient_sections)

    # Bump last_used_at on any remembered substitution the user re-confirmed here, so it
    # floats to the top of the quick-picks next time (Phase 3.9 M4). Silent no-op for swaps
    # that aren't in the library.
    from app.services import substitutions as substitutions_service

    for original, substitute in confirmed_swaps:
        substitutions_service.touch(db, original_name=original, substitute_name=substitute)

    return recipe


def get_recipe(db: Session, recipe_id: int) -> Recipe:
    """Fetch by id regardless of archived state — archived recipes are still
    viewable by direct link, only excluded from the default browse list
    (see list_recipes)."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise RecipeNotFoundError(recipe_id)
    return recipe


def list_recipes(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    include_archived: bool = False,
) -> tuple[list[Recipe], int]:
    """Returns (page of recipes, total matching count) for pagination
    (see CLAUDE.md > API Conventions). Default view filters archived_at IS
    NULL, per CLAUDE.md > Data Model > recipes soft-delete."""
    query = db.query(Recipe)
    if not include_archived:
        query = query.filter(Recipe.archived_at.is_(None))
    if search:
        query = query.filter(func.lower(Recipe.name).contains(search.strip().lower()))

    total = query.count()
    recipes = query.order_by(Recipe.name.asc()).offset(offset).limit(limit).all()
    return recipes, total


def update_recipe(db: Session, recipe_id: int, data: RecipeUpdate) -> Recipe:
    recipe = get_recipe(db, recipe_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    for field, value in changes.items():
        setattr(recipe, field, value)
    db.commit()
    db.refresh(recipe)
    logger.info("Recipe updated: id=%s fields=%s", recipe_id, list(changes.keys()))
    return recipe


def archive_recipe(db: Session, recipe_id: int) -> None:
    """Soft delete — sets archived_at rather than removing the row (see
    CLAUDE.md > Data Model > recipes > soft-delete)."""
    recipe = get_recipe(db, recipe_id)
    recipe.archived_at = utcnow()
    db.commit()
    logger.info("Recipe archived: id=%s", recipe_id)


def unarchive_recipe(db: Session, recipe_id: int) -> Recipe:
    """Clears archived_at — backs the "Restore existing" action on the duplicate-recipe
    warning panel (see CLAUDE.md > Duplicate Recipe Prevention). Idempotent on a live recipe."""
    recipe = get_recipe(db, recipe_id)
    recipe.archived_at = None
    db.commit()
    db.refresh(recipe)
    logger.info("Recipe unarchived: id=%s", recipe_id)
    return recipe


# --- recipe_ingredients ------------------------------------------------


def add_ingredient(db: Session, recipe_id: int, data: RecipeIngredientCreate) -> RecipeIngredient:
    """Append one ingredient to an existing recipe. Name normalised lowercase;
    `resolved_ingredient` / `substitution_note` pass through normalised (Phase 3.9 M4).
    Raises RecipeNotFoundError if the recipe is gone."""
    recipe = get_recipe(db, recipe_id)
    resolved = _norm_resolved(data.resolved_ingredient)
    rq, ru = _resolved_transform(resolved, data.resolved_quantity, data.resolved_unit)
    ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        name=_normalise_ingredient_name(data.name),
        quantity=data.quantity,
        unit=data.unit,
        preparation=data.preparation,
        sort_order=data.sort_order,
        resolved_ingredient=resolved,
        substitution_note=_clean_optional_text(data.substitution_note),
        resolved_quantity=rq,
        resolved_unit=ru,
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    logger.info(
        "Ingredient added: recipe_id=%s ingredient_id=%s name=%r",
        recipe_id,
        ingredient.id,
        ingredient.name,
    )
    return ingredient


def _get_ingredient(db: Session, recipe_id: int, ingredient_id: int) -> RecipeIngredient:
    ingredient = db.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe_id:
        raise IngredientNotFoundError(recipe_id, ingredient_id)
    return ingredient


def update_ingredient(
    db: Session, recipe_id: int, ingredient_id: int, data: RecipeIngredientUpdate
) -> RecipeIngredient:
    """Partial update — only fields actually sent are changed (`exclude_unset`). Name +
    `resolved_ingredient` are re-normalised; sending `resolved_ingredient: null` clears the
    substitution (reverts to `name`). Phase 3.9 M4."""
    ingredient = _get_ingredient(db, recipe_id, ingredient_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = _normalise_ingredient_name(changes["name"])
    if "resolved_ingredient" in changes:  # may be an explicit null to clear the swap
        changes["resolved_ingredient"] = _norm_resolved(changes["resolved_ingredient"])
    if "substitution_note" in changes:
        changes["substitution_note"] = _clean_optional_text(changes["substitution_note"])
    if "resolved_unit" in changes:
        changes["resolved_unit"] = _norm_resolved(changes["resolved_unit"])
    for field, value in changes.items():
        setattr(ingredient, field, value)
    # M8 invariant on the merged row: the quantity/unit transform only means anything
    # alongside a name swap, and is both-or-neither. Clearing resolved_ingredient (or leaving
    # a half-pair) drops the transform rather than erroring — reverting is always safe.
    if not ingredient.resolved_ingredient or ingredient.resolved_quantity is None:
        ingredient.resolved_quantity = None
        ingredient.resolved_unit = None
    db.commit()
    db.refresh(ingredient)
    logger.info(
        "Ingredient updated: recipe_id=%s ingredient_id=%s fields=%s",
        recipe_id,
        ingredient_id,
        list(changes.keys()),
    )
    return ingredient


def delete_ingredient(db: Session, recipe_id: int, ingredient_id: int) -> None:
    """Hard delete — recipe_ingredients has no soft-delete column in the data
    model (only recipes does), so removing an ingredient from a recipe is a
    real DELETE."""
    ingredient = _get_ingredient(db, recipe_id, ingredient_id)
    db.delete(ingredient)
    db.commit()
    logger.info("Ingredient deleted: recipe_id=%s ingredient_id=%s", recipe_id, ingredient_id)
