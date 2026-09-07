"""FastAPI application entry point.

Run directly (``python -m app.main``) or via uvicorn (``uvicorn app.main:app``).
start.bat uses the former.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import SessionLocal, init_db
from app.log_config import setup_logging
from app.seed_data import seed_reference_data
from app.routers import (
    anylist,
    checklist,
    diagnostics,
    health,
    recipes,
    sessions,
)
from app.routers import settings as settings_router
from app.services.capture_photo import InvalidImageError
from app.services.capture_url import RecipeFetchError
from app.services.ai_extraction import AiExtractionDisabledError, AiExtractionError
from app.services.recipes import (
    IngredientNotFoundError,
    PossibleDuplicateRecipeError,
    RecipeNotFoundError,
)
from app.services.sessions import (
    SessionNotFoundError,
    SessionSlotNotFoundError,
    SlotOrderMismatchError,
)
from app.services.settings import (
    DuplicateProductUnitNameError,
    DuplicateStapleNameError,
    ProductUnitNotFoundError,
    StapleNotFoundError,
)
from app.services.substitutions import (
    DuplicateSubstitutionError,
    InvalidSubstitutionError,
    SubstitutionNotFoundError,
)

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown. On startup: create tables (fresh-DB fast path — Alembic owns
    schema *changes*, see CLAUDE.md > Migrations), seed the idempotent reference data, and
    start the hourly capture-queue retry poller (Phase 3.9 M3). On shutdown: cancel the
    poller. A failure in init_db / seed is fatal (re-raised); the poller's own errors are
    caught per-iteration so one bad run doesn't kill it."""
    logger.info(
        "=== ShoppingApp starting (port %s, log level %s) ===", settings.port, settings.log_level
    )
    # Phase 5 — nudge toward keyring storage for the AnyList credentials (CLAUDE.md > Security
    # §2). Logged here, not in config.py, because logging isn't configured at config import.
    if settings.anylist_secret_source in ("env", "mixed"):
        logger.warning(
            "AnyList credentials loaded from .env (plaintext). Prefer Windows Credential "
            "Manager: `keyring set shoppingapp anylist_email` / `... anylist_password`. "
            "See CLAUDE.md > Security §2."
        )
    try:
        init_db()
    except Exception:
        logger.error("Database initialisation failed during startup", exc_info=True)
        raise

    # Reference data (staples + product_units starter lists) — idempotent, safe to
    # run on every startup. See CLAUDE.md > Build Phases > Phase 2, Chunk 2.1.
    db = SessionLocal()
    try:
        seed_reference_data(db)
    except Exception:
        logger.error("Reference data seed failed during startup", exc_info=True)
        raise
    finally:
        db.close()

    # Capture retry queue poller (Phase 3.9 M3) — wakes ~hourly and retries any capture
    # tasks parked on a Gemini 429. See app/services/capture_queue.py.
    poller = asyncio.create_task(_capture_queue_poll_loop())

    logger.info("Startup complete - diagnostics available at /#/diagnostics")
    yield
    poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller
    logger.info("=== ShoppingApp shutting down ===")


async def _capture_queue_poll_loop() -> None:
    from app.services import capture_queue

    while True:
        try:
            await asyncio.sleep(capture_queue.POLL_INTERVAL_SECONDS)
            db = SessionLocal()
            try:
                await asyncio.to_thread(capture_queue.run_once, db)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("capture_queue poll loop iteration failed", exc_info=True)


app = FastAPI(title="ShoppingApp", version="0.1.0", lifespan=lifespan)

# Local network access from phones on the home WiFi — but scoped to known origins only
# (see CLAUDE.md > Security §4). ALLOWED_ORIGINS in .env controls this; defaults to
# localhost/127.0.0.1 for dev. Without this scoping, any origin's JS (e.g. a malicious ad
# in an ordinary browser tab on the same WiFi) could read/write this API cross-origin, since
# there is no login to fall back on.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- error handling: every response uses the CLAUDE.md envelope -----------


def _error_body(code: str, message: str, detail=None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "detail": detail}}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        logger.error("HTTP %s on %s %s", exc.status_code, request.method, request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(f"HTTP_{exc.status_code}", str(exc.detail)),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "VALIDATION_ERROR",
            "The request was not in the expected format.",
            jsonable_encoder(exc.errors()),
        ),
    )


@app.exception_handler(RecipeNotFoundError)
async def recipe_not_found_handler(request: Request, exc: RecipeNotFoundError):
    logger.info("Recipe not found: id=%s (%s %s)", exc.recipe_id, request.method, request.url.path)
    return JSONResponse(
        status_code=404,
        content=_error_body("RECIPE_NOT_FOUND", f"Recipe {exc.recipe_id} not found.", None),
    )


@app.exception_handler(IngredientNotFoundError)
async def ingredient_not_found_handler(request: Request, exc: IngredientNotFoundError):
    logger.info(
        "Ingredient not found: recipe_id=%s ingredient_id=%s (%s %s)",
        exc.recipe_id,
        exc.ingredient_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body(
            "INGREDIENT_NOT_FOUND",
            f"Ingredient {exc.ingredient_id} not found on recipe {exc.recipe_id}.",
            None,
        ),
    )


@app.exception_handler(StapleNotFoundError)
async def staple_not_found_handler(request: Request, exc: StapleNotFoundError):
    logger.info("Staple not found: id=%s (%s %s)", exc.staple_id, request.method, request.url.path)
    return JSONResponse(
        status_code=404,
        content=_error_body("STAPLE_NOT_FOUND", f"Staple {exc.staple_id} not found.", None),
    )


@app.exception_handler(DuplicateStapleNameError)
async def duplicate_staple_name_handler(request: Request, exc: DuplicateStapleNameError):
    logger.info("Duplicate staple name: %r (%s %s)", exc.name, request.method, request.url.path)
    return JSONResponse(
        status_code=409,
        content=_error_body(
            "DUPLICATE_STAPLE_NAME", f'"{exc.name}" is already on the staples list.', None
        ),
    )


@app.exception_handler(ProductUnitNotFoundError)
async def product_unit_not_found_handler(request: Request, exc: ProductUnitNotFoundError):
    logger.info(
        "Product unit not found: id=%s (%s %s)",
        exc.product_unit_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body(
            "PRODUCT_UNIT_NOT_FOUND", f"Product unit {exc.product_unit_id} not found.", None
        ),
    )


@app.exception_handler(DuplicateProductUnitNameError)
async def duplicate_product_unit_name_handler(
    request: Request, exc: DuplicateProductUnitNameError
):
    logger.info(
        "Duplicate product unit ingredient_name: %r (%s %s)",
        exc.ingredient_name,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=409,
        content=_error_body(
            "DUPLICATE_PRODUCT_UNIT_NAME",
            f'A purchase unit for "{exc.ingredient_name}" already exists.',
            None,
        ),
    )


@app.exception_handler(PossibleDuplicateRecipeError)
async def possible_duplicate_recipe_handler(request: Request, exc: PossibleDuplicateRecipeError):
    # Warn-with-override, not a hard block — the frontend shows the matches and offers
    # "Save anyway" (re-submits with allow_duplicate=true). See CLAUDE.md > Duplicate
    # Recipe Prevention. Not an error-level event.
    logger.info(
        "Possible duplicate recipe on %s %s: %d match(es)",
        request.method,
        request.url.path,
        len(exc.matches),
    )
    return JSONResponse(
        status_code=409,
        content=_error_body(
            "POSSIBLE_DUPLICATE_RECIPE",
            "This looks like a recipe you already have.",
            [
                {
                    "id": m.id,
                    "name": m.name,
                    "source_summary": m.source_summary,
                    "matched_signal": m.matched_signal,
                    "archived": m.archived,
                }
                for m in exc.matches
            ],
        ),
    )


@app.exception_handler(SubstitutionNotFoundError)
async def substitution_not_found_handler(request: Request, exc: SubstitutionNotFoundError):
    logger.info(
        "Substitution not found: id=%s (%s %s)",
        exc.substitution_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body(
            "SUBSTITUTION_NOT_FOUND", f"Substitution {exc.substitution_id} not found.", None
        ),
    )


@app.exception_handler(DuplicateSubstitutionError)
async def duplicate_substitution_handler(request: Request, exc: DuplicateSubstitutionError):
    logger.info(
        "Duplicate substitution: %r -> %r (%s %s)",
        exc.original_name,
        exc.substitute_name,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=409,
        content=_error_body(
            "DUPLICATE_SUBSTITUTION",
            f'A rule for "{exc.original_name}" → "{exc.substitute_name}" already exists.',
            None,
        ),
    )


@app.exception_handler(InvalidSubstitutionError)
async def invalid_substitution_handler(request: Request, exc: InvalidSubstitutionError):
    logger.info("Invalid substitution: %s (%s %s)", exc.reason, request.method, request.url.path)
    return JSONResponse(
        status_code=422,
        content=_error_body("INVALID_SUBSTITUTION", exc.reason, None),
    )


@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(request: Request, exc: SessionNotFoundError):
    logger.info(
        "Planning session not found: id=%s (%s %s)",
        exc.session_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body(
            "SESSION_NOT_FOUND", f"Planning session {exc.session_id} not found.", None
        ),
    )


@app.exception_handler(SessionSlotNotFoundError)
async def session_slot_not_found_handler(request: Request, exc: SessionSlotNotFoundError):
    logger.info(
        "Session slot not found: session_id=%s slot_id=%s (%s %s)",
        exc.session_id,
        exc.slot_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=404,
        content=_error_body(
            "SESSION_SLOT_NOT_FOUND",
            f"Slot {exc.slot_id} not found on session {exc.session_id}.",
            None,
        ),
    )


@app.exception_handler(SlotOrderMismatchError)
async def slot_order_mismatch_handler(request: Request, exc: SlotOrderMismatchError):
    logger.info(
        "Slot reorder id-list mismatch: session_id=%s (%s %s)",
        exc.session_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "SLOT_ORDER_MISMATCH",
            "The reorder request must list exactly this session's current slot ids.",
            None,
        ),
    )


@app.exception_handler(AiExtractionDisabledError)
async def ai_extraction_disabled_handler(request: Request, exc: AiExtractionDisabledError):
    # Not logged as an error — this is the highest-priority §0c gate working as designed,
    # not a failure. See CLAUDE.md > Security > §0c.
    logger.warning(
        "AI extraction call refused (disabled): %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=503,
        content=_error_body(
            "AI_EXTRACTION_DISABLED",
            "Recipe capture is currently switched off. Ask the maintainer to enable it.",
            None,
        ),
    )


@app.exception_handler(AiExtractionError)
async def ai_extraction_error_handler(request: Request, exc: AiExtractionError):
    # Already logged at ERROR with exc_info=True inside ai_extraction.py at the point of
    # failure (CLAUDE.md > Diagnostics & Logging) — this is just the envelope translation.
    logger.warning("AI extraction failed: %s %s (%s)", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content=_error_body(
            "EXTRACTION_FAILED",
            "Couldn't extract ingredients from that. Try again, or add the recipe manually.",
            str(exc),
        ),
    )


@app.exception_handler(RecipeFetchError)
async def recipe_fetch_error_handler(request: Request, exc: RecipeFetchError):
    logger.warning("Recipe URL fetch failed: %s (%s)", exc.url, exc.reason)
    return JSONResponse(
        status_code=502,
        content=_error_body(
            "RECIPE_FETCH_FAILED",
            f"Couldn't fetch that page — {exc.reason}. Check the URL and try again.",
            None,
        ),
    )


@app.exception_handler(InvalidImageError)
async def invalid_image_error_handler(request: Request, exc: InvalidImageError):
    logger.info("Recipe photo upload rejected: %s", exc.reason)
    return JSONResponse(
        status_code=422,
        content=_error_body("INVALID_IMAGE", exc.reason, None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s", request.method, request.url.path, exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content=_error_body(
            "INTERNAL_ERROR",
            "Something went wrong on the server. Check the diagnostics log for details.",
            str(exc),
        ),
    )


# --- routers ------------------------------------------------------------

app.include_router(health.router)
app.include_router(diagnostics.router)
app.include_router(recipes.router)
app.include_router(sessions.router)
app.include_router(checklist.router)
app.include_router(anylist.router)
app.include_router(settings_router.router)


# --- static frontend --------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # A bare Response (not JSONResponse) for a real empty body. JSONResponse would
    # serialise content=None to the 4-byte body b"null" while Starlette declares
    # Content-Length: 0 for a 204, a mismatch h11 rejects as LocalProtocolError —
    # found via Phase 2 Chunk 2.3 browser testing: every page load requests this
    # and was spamming ERROR-level noise into the exact diagnostics panel meant
    # to surface real problems (see CLAUDE.md > Diagnostics & Logging).
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn

    # log_config=None: uvicorn's default logging setup detaches uvicorn.access from the
    # root logger (its own handler, propagate=False), which silently drops every request
    # access log from logs/app.log and the diagnostics ring buffer even though the console
    # still shows them. Passing None leaves our own setup_logging() config untouched instead.
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=settings.port, reload=False, log_config=None
    )
