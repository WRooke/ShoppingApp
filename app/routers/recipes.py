"""Recipe library API — recipe CRUD (soft delete) and nested ingredient CRUD.

HTTP only: parse the request, call app/services/recipes.py, wrap the result in
the {"ok": ...} envelope (see CLAUDE.md > API Conventions). Business logic and
query construction live in the service layer — see CLAUDE.md > Code
Architecture & Maintainability. RecipeNotFoundError / IngredientNotFoundError
are translated to a 404 envelope centrally in app/main.py, not here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recipes import (
    RecipeCreate,
    RecipeIngredientCreate,
    RecipeIngredientRead,
    RecipeIngredientUpdate,
    RecipeListItem,
    RecipeRead,
    RecipeUpdate,
)
from app.services import recipes as recipes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recipes", tags=["recipes"])


# --- recipes -------------------------------------------------------------


@router.post("", status_code=201)
def create_recipe(data: RecipeCreate, db: Session = Depends(get_db)) -> dict:
    recipe = recipes_service.create_recipe(db, data)
    return {"ok": True, "data": RecipeRead.model_validate(recipe).model_dump(mode="json")}


@router.get("")
def list_recipes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, description="Case-insensitive substring match on name"),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    items, total = recipes_service.list_recipes(
        db, limit=limit, offset=offset, search=search, include_archived=include_archived
    )
    return {
        "ok": True,
        "data": {
            "items": [RecipeListItem.model_validate(r).model_dump(mode="json") for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, db: Session = Depends(get_db)) -> dict:
    recipe = recipes_service.get_recipe(db, recipe_id)
    return {"ok": True, "data": RecipeRead.model_validate(recipe).model_dump(mode="json")}


@router.patch("/{recipe_id}")
def update_recipe(recipe_id: int, data: RecipeUpdate, db: Session = Depends(get_db)) -> dict:
    recipe = recipes_service.update_recipe(db, recipe_id, data)
    return {"ok": True, "data": RecipeRead.model_validate(recipe).model_dump(mode="json")}


@router.delete("/{recipe_id}")
def archive_recipe(recipe_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft delete — sets archived_at. See CLAUDE.md > Data Model > recipes."""
    recipes_service.archive_recipe(db, recipe_id)
    return {"ok": True, "data": {"id": recipe_id, "archived": True}}


# --- nested recipe_ingredients --------------------------------------------


@router.post("/{recipe_id}/ingredients", status_code=201)
def add_ingredient(
    recipe_id: int, data: RecipeIngredientCreate, db: Session = Depends(get_db)
) -> dict:
    ingredient = recipes_service.add_ingredient(db, recipe_id, data)
    return {
        "ok": True,
        "data": RecipeIngredientRead.model_validate(ingredient).model_dump(mode="json"),
    }


@router.patch("/{recipe_id}/ingredients/{ingredient_id}")
def update_ingredient(
    recipe_id: int,
    ingredient_id: int,
    data: RecipeIngredientUpdate,
    db: Session = Depends(get_db),
) -> dict:
    ingredient = recipes_service.update_ingredient(db, recipe_id, ingredient_id, data)
    return {
        "ok": True,
        "data": RecipeIngredientRead.model_validate(ingredient).model_dump(mode="json"),
    }


@router.delete("/{recipe_id}/ingredients/{ingredient_id}")
def delete_ingredient(recipe_id: int, ingredient_id: int, db: Session = Depends(get_db)) -> dict:
    recipes_service.delete_ingredient(db, recipe_id, ingredient_id)
    return {"ok": True, "data": {"id": ingredient_id, "deleted": True}}
