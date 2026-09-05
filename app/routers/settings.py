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
from app.schemas.settings import (
    ProductUnitCreate,
    ProductUnitRead,
    ProductUnitUpdate,
    StapleCreate,
    StapleRead,
    StapleUpdate,
)
from app.services import settings as settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


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
