"""The recipe-capture retry queue (Phase 3.9 M3).

A capture AI call that hits 429 on *both* Gemini models
(``ai_extraction.AiQuotaExhaustedError``) is parked here instead of failing the user's
request. A lifespan background poller (``app.main``) calls ``run_once`` about once an hour;
a task that succeeds on retry runs through the normal pipeline and its row is deleted.

M3 wires the ``extract_url`` / ``extract_photo`` tasks end-to-end (a successful retry
auto-saves the recipe to the library — the user names/edits it afterwards). The
``flag_substitutions`` / ``suggest_sections`` enrichment tasks are enqueued against a saved
recipe by M4/M6; ``run_once`` leaves them alone until then.

Plain Python / SQLAlchemy — no ``fastapi`` import.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import utcnow
from app.models.queue import CaptureQueueItem
from app.models.recipes import Recipe
from app.schemas.capture import CaptureConfirmRequest
from app.services import ai_extraction, capture_url, product_sections
from app.services import recipes as recipes_service

logger = logging.getLogger(__name__)

# How often the lifespan poller (app.main) calls run_once(). ~hourly — CLAUDE.md > AI
# Provider Migration deliberately does NOT tie retries to an assumed quota reset time.
POLL_INTERVAL_SECONDS = 3600


def enqueue(
    db: Session, *, task: str, payload: dict, recipe_id: int | None = None
) -> CaptureQueueItem:
    item = CaptureQueueItem(
        task=task, payload_json=json.dumps(payload), recipe_id=recipe_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("capture_queue: enqueued task=%s id=%s recipe_id=%s", task, item.id, recipe_id)
    return item


def due_items(db: Session) -> list[CaptureQueueItem]:
    """Everything in the queue — the poller runs hourly, so 'due' is just 'present'."""
    return db.query(CaptureQueueItem).order_by(CaptureQueueItem.queued_at.asc()).all()


def record_attempt(db: Session, item: CaptureQueueItem, *, error: str | None = None) -> None:
    item.attempt_count += 1
    item.last_attempt_at = utcnow()
    item.last_error = error
    db.commit()


def remove(db: Session, item: CaptureQueueItem) -> None:
    db.delete(item)
    db.commit()


def _result_to_confirm(result: ai_extraction.ExtractionResult, payload: dict) -> CaptureConfirmRequest:
    """Auto-save shape for a queued capture that finally succeeded. Placeholder name — the
    user renames/reviews it in the library afterwards."""
    return CaptureConfirmRequest(
        name=payload.get("fallback_name") or "Untitled captured recipe",
        source_type=payload["source_type"],
        source_url=payload.get("url"),
        source_image_path=payload.get("image_path"),
        base_servings=4,
        cuisine=result.cuisine,
        protein=result.protein,
        ingredients=[
            {
                "name": ing.name,
                "quantity": ing.quantity,
                "unit": ing.unit,
                "preparation": ing.preparation,
                "suggested_section": ing.suggested_section,
            }
            for ing in result.ingredients
        ],
        allow_duplicate=True,
    )


def _clear_pending(db: Session, recipe_id: int, task: str) -> None:
    """Remove `task` from a recipe's ai_tasks_pending list (M6). No-op if the recipe is
    gone or the task wasn't listed."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        return
    remaining = [t for t in recipe.ai_pending_tasks if t != task]
    recipe.ai_tasks_pending = json.dumps(remaining) if remaining else None
    db.commit()


def _process_extract(db: Session, item: CaptureQueueItem) -> None:
    payload = json.loads(item.payload_json)
    if item.task == "extract_url":
        result = capture_url.fetch_and_extract(db, payload["url"])
    else:  # extract_photo
        image_path = Path(settings.images_path) / payload["image_path"]
        content = image_path.read_bytes()
        result = ai_extraction.capture_recipe(
            db,
            call_type="recipe_photo",
            context_id=payload["image_path"],
            image_base64=base64.standard_b64encode(content).decode("utf-8"),
            image_media_type=payload.get("content_type", "image/jpeg"),
        )
    recipe = recipes_service.create_recipe_from_capture(
        db, _result_to_confirm(result, payload), allow_duplicate=True
    )
    # M6 — an auto-saved queued capture with enrichment still owed: record it on the recipe
    # (badge) and queue the retry.
    if "suggest_sections" in result.pending_tasks:
        recipe.ai_tasks_pending = json.dumps(["suggest_sections"])
        db.commit()
        enqueue(
            db,
            task="suggest_sections",
            payload={"recipe_id": recipe.id},
            recipe_id=recipe.id,
        )
    logger.info(
        "capture_queue: task=%s id=%s succeeded on retry -> recipe %s (pending=%s)",
        item.task,
        item.id,
        recipe.id,
        result.pending_tasks,
    )
    remove(db, item)


def _process_suggest_sections(db: Session, item: CaptureQueueItem) -> None:
    """M6 — retry the section-suggestion call for a saved recipe, then tag product_sections
    and clear the pending flag."""
    recipe = db.get(Recipe, item.recipe_id) if item.recipe_id else None
    if recipe is None:
        remove(db, item)  # recipe was deleted — drop the orphan task
        return
    names = [ing.name for ing in recipe.ingredients]
    sections = ai_extraction.suggest_sections(
        db, context_id=str(recipe.id), ingredient_names=names
    )
    if sections:
        product_sections.tag_suggested_sections(db, sections)
    _clear_pending(db, recipe.id, "suggest_sections")
    logger.info(
        "capture_queue: suggest_sections retry for recipe %s -> %d section(s)",
        recipe.id,
        len(sections),
    )
    remove(db, item)


def run_once(db: Session) -> dict:
    """Process every queued item once. Returns a small summary for logging/diagnostics."""
    summary = {"processed": 0, "succeeded": 0, "still_queued": 0, "skipped": 0}
    for item in due_items(db):
        summary["processed"] += 1
        try:
            if item.task == "suggest_sections":
                _process_suggest_sections(db, item)
            elif item.task == "flag_substitutions":
                # not retried post-capture — interactive-only; drop it if it somehow got here
                remove(db, item)
                summary["skipped"] += 1
                continue
            else:
                _process_extract(db, item)
            summary["succeeded"] += 1
        except ai_extraction.AiQuotaExhaustedError:
            record_attempt(db, item, error="still over quota")
            summary["still_queued"] += 1
        except Exception as exc:  # noqa: BLE001 — keep the item, try again next hour
            logger.error("capture_queue: task id=%s failed on retry", item.id, exc_info=True)
            record_attempt(db, item, error=str(exc))
            summary["still_queued"] += 1
    if summary["processed"]:
        logger.info("capture_queue.run_once: %s", summary)
    return summary
