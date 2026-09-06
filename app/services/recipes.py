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


def _normalise_ingredient_name(name: str) -> str:
    """Lowercase + strip whitespace — see CLAUDE.md > Ingredient Normalisation.
    Automatic synonym matching ("green onion" vs "spring onion") is explicitly
    NOT implemented here — deferred, user review is the normalisation for now."""
    return name.strip().lower()


# --- recipes ---------------------------------------------------------------


def create_recipe(db: Session, data: RecipeCreate) -> Recipe:
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    for i, ing in enumerate(data.ingredients):
        recipe.ingredients.append(
            RecipeIngredient(
                name=_normalise_ingredient_name(ing.name),
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=ing.sort_order or i,
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


def create_recipe_from_capture(db: Session, data: CaptureConfirmRequest) -> Recipe:
    """Saves a reviewed recipe capture (Chunk 3.4 — see CLAUDE.md > Build Phases > Phase 3).
    Differs from create_recipe() only in also writing product_sections rows for any
    ingredient carrying a suggested_section — see services/product_sections.py."""
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    ingredient_sections: dict[str, str] = {}
    for i, ing in enumerate(data.ingredients):
        normalised_name = _normalise_ingredient_name(ing.name)
        recipe.ingredients.append(
            RecipeIngredient(
                name=normalised_name,
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=i,
            )
        )
        if ing.suggested_section:
            ingredient_sections[normalised_name] = ing.suggested_section

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


# --- recipe_ingredients ------------------------------------------------


def add_ingredient(db: Session, recipe_id: int, data: RecipeIngredientCreate) -> RecipeIngredient:
    recipe = get_recipe(db, recipe_id)
    ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        name=_normalise_ingredient_name(data.name),
        quantity=data.quantity,
        unit=data.unit,
        preparation=data.preparation,
        sort_order=data.sort_order,
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
    ingredient = _get_ingredient(db, recipe_id, ingredient_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = _normalise_ingredient_name(changes["name"])
    for field, value in changes.items():
        setattr(ingredient, field, value)
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
