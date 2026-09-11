"""Settings API — CRUD for the `staples` and `product_units` reference
catalogue (see CLAUDE.md > Data Model > product_units / staples). This is
what makes the seeded data from Chunk 2.1 actually editable, per the Phase 2
deliverable (CLAUDE.md > Build Phases > Phase 2).

HTTP only: parse the request, call app/services/settings.py, wrap the result
in the {"ok": ...} envelope (see CLAUDE.md > API Conventions). Business logic
and query construction live in the service layer — see CLAUDE.md > Code
Architecture & Maintainability. The Not-Found / Duplicate-Name exceptions are
translated to structured errors centrally in app/main.py, not here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.coarse_ingredients import (
    CoarseIngredientCreate,
    CoarseIngredientRead,
    CoarseIngredientUpdate,
)
from app.schemas.ingredient_aliases import (
    IngredientAliasCreate,
    IngredientAliasRead,
    IngredientAliasUpdate,
)
from app.schemas.settings import (
    ProductUnitCreate,
    ProductUnitRead,
    ProductUnitUpdate,
    StapleCreate,
    StapleRead,
    StapleUpdate,
)
from app.schemas.unit_synonyms import (
    UnitSynonymCreate,
    UnitSynonymRead,
    UnitSynonymUpdate,
)
from app.schemas.usuals import UsualItemCreate, UsualItemUpdate
from app.schemas.substitutions import (
    RememberedSubstitutionCreate,
    RememberedSubstitutionRead,
    RememberedSubstitutionUpdate,
)
from app.services import coarse_ingredients as coarse_ingredients_service
from app.services import ingredient_aliases as ingredient_aliases_service
from app.services import settings as settings_service
from app.services import substitutions as substitutions_service
from app.services import unit_synonyms as unit_synonyms_service
from app.services import usuals as usuals_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# --- section vocabulary (read-only constant, see CLAUDE.md > Section Vocabulary Starter
# List) — used by the capture review UI's suggested_section dropdown (Chunk 3.4) --------


@router.get("/section-vocabulary")
def section_vocabulary() -> dict:
    return {"ok": True, "data": {"sections": settings_service.get_section_vocabulary()}}


# --- staples ---------------------------------------------------------------


@router.post("/staples", status_code=201)
def create_staple(data: StapleCreate, db: Session = Depends(get_db)) -> dict:
    staple = settings_service.create_staple(db, data)
    return {"ok": True, "data": StapleRead.model_validate(staple).model_dump(mode="json")}


@router.get("/staples")
def list_staples(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = settings_service.list_staples(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [StapleRead.model_validate(s).model_dump(mode="json") for s in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/staples/{staple_id}")
def update_staple(staple_id: int, data: StapleUpdate, db: Session = Depends(get_db)) -> dict:
    staple = settings_service.update_staple(db, staple_id, data)
    return {"ok": True, "data": StapleRead.model_validate(staple).model_dump(mode="json")}


@router.delete("/staples/{staple_id}")
def delete_staple(staple_id: int, db: Session = Depends(get_db)) -> dict:
    settings_service.delete_staple(db, staple_id)
    return {"ok": True, "data": {"id": staple_id, "deleted": True}}


# --- product_units -----------------------------------------------------


@router.post("/product-units", status_code=201)
def create_product_unit(data: ProductUnitCreate, db: Session = Depends(get_db)) -> dict:
    product_unit = settings_service.create_product_unit(db, data)
    return {
        "ok": True,
        "data": ProductUnitRead.model_validate(product_unit).model_dump(mode="json"),
    }


@router.get("/product-units")
def list_product_units(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = settings_service.list_product_units(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [ProductUnitRead.model_validate(p).model_dump(mode="json") for p in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/product-units/{product_unit_id}")
def update_product_unit(
    product_unit_id: int, data: ProductUnitUpdate, db: Session = Depends(get_db)
) -> dict:
    product_unit = settings_service.update_product_unit(db, product_unit_id, data)
    return {
        "ok": True,
        "data": ProductUnitRead.model_validate(product_unit).model_dump(mode="json"),
    }


@router.delete("/product-units/{product_unit_id}")
def delete_product_unit(product_unit_id: int, db: Session = Depends(get_db)) -> dict:
    settings_service.delete_product_unit(db, product_unit_id)
    return {"ok": True, "data": {"id": product_unit_id, "deleted": True}}


# --- remembered substitutions: the quick-pick library (Phase 3.9 M4) -------------------
#
# A row is *created* when the user ticks "save this swap" at capture review, in the recipe
# editor, or after a planning swap. This section views / edits the note / deletes them. It
# never applies a swap and has no "default". Exceptions translate centrally in app/main.py.


def _sub_read(row) -> dict:
    return RememberedSubstitutionRead.model_validate(row).model_dump(mode="json")


@router.post("/substitutions", status_code=201)
def create_substitution(
    data: RememberedSubstitutionCreate, db: Session = Depends(get_db)
) -> dict:
    return {"ok": True, "data": _sub_read(substitutions_service.create_substitution(db, data))}


@router.get("/substitutions")
def list_substitutions(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = substitutions_service.list_substitutions(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [_sub_read(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/substitutions/{substitution_id}")
def update_substitution(
    substitution_id: int,
    data: RememberedSubstitutionUpdate,
    db: Session = Depends(get_db),
) -> dict:
    row = substitutions_service.update_substitution(db, substitution_id, data)
    return {"ok": True, "data": _sub_read(row)}


@router.delete("/substitutions/{substitution_id}")
def delete_substitution(substitution_id: int, db: Session = Depends(get_db)) -> dict:
    substitutions_service.delete_substitution(db, substitution_id)
    return {"ok": True, "data": {"id": substitution_id, "deleted": True}}


# --- "the usuals" (Phase 5 Chunk 5.4) --------------------------------------


@router.post("/usuals", status_code=201)
def create_usual(data: UsualItemCreate, db: Session = Depends(get_db)) -> dict:
    item = usuals_service.create_usual(db, data)
    return {"ok": True, "data": usuals_service.to_read(item)}


@router.get("/usuals")
def list_usuals(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = usuals_service.list_usuals(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [usuals_service.to_read(i) for i in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/usuals/{usual_id}")
def update_usual(usual_id: int, data: UsualItemUpdate, db: Session = Depends(get_db)) -> dict:
    item = usuals_service.update_usual(db, usual_id, data)
    return {"ok": True, "data": usuals_service.to_read(item)}


@router.delete("/usuals/{usual_id}")
def delete_usual(usual_id: int, db: Session = Depends(get_db)) -> dict:
    usuals_service.delete_usual(db, usual_id)
    return {"ok": True, "data": {"id": usual_id, "deleted": True}}


# --- ingredient aliases: "same shopping item" grouping (2026-09-10) --------------------
#
# Distinct from remembered substitutions above — see CLAUDE.md > Ingredient Aliases. Never
# applies a swap or needs confirmation; it's a pure relabelling resolved fresh at every
# consolidate (app/services/session_consolidation.py), not stored on any recipe.


def _alias_read(row) -> dict:
    return IngredientAliasRead.model_validate(row).model_dump(mode="json")


@router.post("/ingredient-aliases", status_code=201)
def create_ingredient_alias(data: IngredientAliasCreate, db: Session = Depends(get_db)) -> dict:
    row = ingredient_aliases_service.create_alias(db, data)
    return {"ok": True, "data": _alias_read(row)}


@router.get("/ingredient-aliases")
def list_ingredient_aliases(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = ingredient_aliases_service.list_aliases(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [_alias_read(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/ingredient-aliases/{alias_id}")
def update_ingredient_alias(
    alias_id: int, data: IngredientAliasUpdate, db: Session = Depends(get_db)
) -> dict:
    row = ingredient_aliases_service.update_alias(db, alias_id, data)
    return {"ok": True, "data": _alias_read(row)}


@router.delete("/ingredient-aliases/{alias_id}")
def delete_ingredient_alias(alias_id: int, db: Session = Depends(get_db)) -> dict:
    ingredient_aliases_service.delete_alias(db, alias_id)
    return {"ok": True, "data": {"id": alias_id, "deleted": True}}


# --- unit synonyms: spelling canonicalisation (2026-09-12) -----------------------------
#
# Distinct from ingredient aliases above — see CLAUDE.md > Ingredient Unit Handling > Layer
# A. No equivalence pair (a unit needs no quantity conversion to its own synonym).


def _unit_synonym_read(row) -> dict:
    return UnitSynonymRead.model_validate(row).model_dump(mode="json")


@router.post("/unit-synonyms", status_code=201)
def create_unit_synonym(data: UnitSynonymCreate, db: Session = Depends(get_db)) -> dict:
    row = unit_synonyms_service.create_synonym(db, data)
    return {"ok": True, "data": _unit_synonym_read(row)}


@router.get("/unit-synonyms")
def list_unit_synonyms(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = unit_synonyms_service.list_synonyms(db, limit=limit, offset=offset)
    return {
        "ok": True,
        "data": {
            "items": [_unit_synonym_read(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/unit-synonyms/{synonym_id}")
def update_unit_synonym(
    synonym_id: int, data: UnitSynonymUpdate, db: Session = Depends(get_db)
) -> dict:
    row = unit_synonyms_service.update_synonym(db, synonym_id, data)
    return {"ok": True, "data": _unit_synonym_read(row)}


@router.delete("/unit-synonyms/{synonym_id}")
def delete_unit_synonym(synonym_id: int, db: Session = Depends(get_db)) -> dict:
    unit_synonyms_service.delete_synonym(db, synonym_id)
    return {"ok": True, "data": {"id": synonym_id, "deleted": True}}


# --- coarse ingredients: skip quantity math entirely (2026-09-12) ----------------------
#
# See CLAUDE.md > Ingredient Unit Handling > Layer D.


def _coarse_read(row) -> dict:
    return CoarseIngredientRead.model_validate(row).model_dump(mode="json")


@router.post("/coarse-ingredients", status_code=201)
def create_coarse_ingredient(
    data: CoarseIngredientCreate, db: Session = Depends(get_db)
) -> dict:
    row = coarse_ingredients_service.create_coarse_ingredient(db, data)
    return {"ok": True, "data": _coarse_read(row)}


@router.get("/coarse-ingredients")
def list_coarse_ingredients(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    items, total = coarse_ingredients_service.list_coarse_ingredients(
        db, limit=limit, offset=offset
    )
    return {
        "ok": True,
        "data": {
            "items": [_coarse_read(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.patch("/coarse-ingredients/{coarse_id}")
def update_coarse_ingredient(
    coarse_id: int, data: CoarseIngredientUpdate, db: Session = Depends(get_db)
) -> dict:
    row = coarse_ingredients_service.update_coarse_ingredient(db, coarse_id, data)
    return {"ok": True, "data": _coarse_read(row)}


@router.delete("/coarse-ingredients/{coarse_id}")
def delete_coarse_ingredient(coarse_id: int, db: Session = Depends(get_db)) -> dict:
    coarse_ingredients_service.delete_coarse_ingredient(db, coarse_id)
    return {"ok": True, "data": {"id": coarse_id, "deleted": True}}
