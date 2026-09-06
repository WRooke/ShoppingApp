"""Recipe library API — recipe CRUD (soft delete), nested ingredient CRUD, and recipe
capture (URL/photo extraction + confirm-save).

HTTP only: parse the request, call app/services/*.py, wrap the result in
the {"ok": ...} envelope (see CLAUDE.md > API Conventions). Business logic and
query construction live in the service layer — see CLAUDE.md > Code
Architecture & Maintainability. Every exception raised below is translated to a
structured envelope centrally in app/main.py, not here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.capture import CaptureConfirmRequest, CaptureResult, CaptureUrlRequest
from app.schemas.recipes import (
    CheckDuplicateResponse,
    DuplicateMatch,
    RecipeCreate,
    RecipeIngredientCreate,
    RecipeIngredientRead,
    RecipeIngredientUpdate,
    RecipeListItem,
    RecipeRead,
    RecipeUpdate,
)
from app.services import capture_photo, capture_queue, capture_url
from app.services import recipes as recipes_service
from app.services.ai_extraction import AiQuotaExhaustedError, ExtractionResult

# Returned (inside the {"ok": true} envelope) when a capture is parked on the retry queue
# because every Gemini model is over quota (Phase 3.9 M3).
_QUEUED = {
    "queued": True,
    "message": (
        "Every AI model is over its quota right now — this capture has been queued and "
        "will be retried automatically."
    ),
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recipes", tags=["recipes"])


def _capture_result(
    result: ExtractionResult,
    *,
    source_type: str,
    source_url: str | None = None,
    source_image_path: str | None = None,
) -> dict:
    """Shapes a ai_extraction.ExtractionResult into the CaptureResult envelope payload — the
    two extraction endpoints below share this, the confirm endpoint doesn't need it (it
    already gets the reviewed shape straight from the frontend)."""
    return CaptureResult(
        source_type=source_type,
        source_url=source_url,
        source_image_path=source_image_path,
        cuisine=result.cuisine,
        protein=result.protein,
        ingredients=[
            {
                "name": ing.name,
                "quantity": ing.quantity,
                "unit": ing.unit,
                "preparation": ing.preparation,
                "original_text": ing.original_text,
                "suggested_section": ing.suggested_section,
            }
            for ing in result.ingredients
        ],
        substitution_flags=[
            {
                "original": f.original,
                "suggested_substitute": f.suggested_substitute,
                "note": f.note,
            }
            for f in result.substitution_flags
        ],
    ).model_dump(mode="json")


# --- recipes -------------------------------------------------------------


@router.post("", status_code=201)
def create_recipe(data: RecipeCreate, db: Session = Depends(get_db)) -> dict:
    recipe = recipes_service.create_recipe(db, data, allow_duplicate=data.allow_duplicate)
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


# Declared before GET /{recipe_id} on purpose — otherwise "check-duplicate" is parsed as a
# recipe id and 422s. Lets the review + manual-entry screens warn live on name-field blur
# rather than only on a submit-and-bounce (CLAUDE.md > Duplicate Recipe Prevention).
@router.get("/check-duplicate")
def check_duplicate(
    name: str = Query(..., min_length=1),
    source_url: str | None = Query(None),
    source_book: str | None = Query(None),
    source_page: str | None = Query(None),
    exclude_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    matches = recipes_service.find_possible_duplicates(
        db,
        name=name,
        source_url=source_url,
        source_book=source_book,
        source_page=source_page,
        exclude_id=exclude_id,
    )
    return {
        "ok": True,
        "data": CheckDuplicateResponse(
            matches=[DuplicateMatch.model_validate(m) for m in matches]
        ).model_dump(mode="json"),
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


@router.post("/{recipe_id}/restore")
def restore_recipe(recipe_id: int, db: Session = Depends(get_db)) -> dict:
    """Clears archived_at — the "Restore existing" action on the duplicate-recipe warning
    panel (CLAUDE.md > Duplicate Recipe Prevention)."""
    recipe = recipes_service.unarchive_recipe(db, recipe_id)
    return {"ok": True, "data": RecipeRead.model_validate(recipe).model_dump(mode="json")}


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


# --- capture (Phase 3 — see CLAUDE.md > Recipe Capture — AI Extraction) --------------------
#
# The two extraction endpoints below return a CaptureResult for the frontend to review —
# nothing is saved yet. /capture/confirm is the separate save step (Chunk 3.4). All three
# route through ai_extraction.extract_ingredients() (URL/photo) or
# recipes_service.create_recipe_from_capture() (confirm), which enforce the
# enable-switch/fake-mode gates and prompt-injection hardening — see CLAUDE.md > Security
# §0a/§0c. Their exceptions (AiExtractionDisabledError, AiExtractionError, RecipeFetchError,
# InvalidImageError) are translated to the envelope centrally in app/main.py, not here.


@router.post("/capture/url")
def capture_from_url(data: CaptureUrlRequest, db: Session = Depends(get_db)) -> dict:
    # Duplicate short-circuit: an exact source_url match returns a 409 BEFORE the Gemini extraction
    # call, so a re-capture of a page already in the library costs nothing (CLAUDE.md >
    # Duplicate Recipe Prevention > URL capture short-circuit). "Capture again anyway"
    # re-submits with allow_duplicate=true.
    if not data.allow_duplicate:
        existing = recipes_service.find_recipe_by_source_url(db, data.url)
        if existing is not None:
            raise recipes_service.PossibleDuplicateRecipeError(
                [
                    recipes_service.DuplicateMatch(
                        id=existing.id,
                        name=existing.name,
                        source_summary=existing.source_url,
                        matched_signal="source_url",
                        archived=existing.archived_at is not None,
                    )
                ]
            )
    try:
        result = capture_url.fetch_and_extract(db, data.url)
    except AiQuotaExhaustedError:
        capture_queue.enqueue(
            db, task="extract_url", payload={"url": data.url, "source_type": "url"}
        )
        return {"ok": True, "data": _QUEUED}
    return {
        "ok": True,
        "data": _capture_result(result, source_type="url", source_url=data.url),
    }


@router.post("/capture/photo")
def capture_from_photo(image: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    content = image.file.read()
    content_type = image.content_type or ""
    filename = capture_photo.store_image(content, content_type)  # raises InvalidImageError
    try:
        result = capture_photo.extract_stored(
            db, filename=filename, content=content, content_type=content_type
        )
    except AiQuotaExhaustedError:
        capture_queue.enqueue(
            db,
            task="extract_photo",
            payload={
                "image_path": filename,
                "content_type": content_type,
                "source_type": "photo",
            },
        )
        return {"ok": True, "data": _QUEUED}
    return {
        "ok": True,
        "data": _capture_result(result, source_type="photo", source_image_path=filename),
    }


@router.post("/capture/confirm", status_code=201)
def confirm_capture(data: CaptureConfirmRequest, db: Session = Depends(get_db)) -> dict:
    recipe = recipes_service.create_recipe_from_capture(
        db, data, allow_duplicate=data.allow_duplicate
    )
    return {"ok": True, "data": RecipeRead.model_validate(recipe).model_dump(mode="json")}
