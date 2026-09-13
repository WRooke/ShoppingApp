"""FastAPI application entry point.

Run directly (``python -m app.main``) or via uvicorn (``uvicorn app.main:app``).
start.bat uses the former.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
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
from app.services.anylist_client import (
    AnyListAuthError,
    AnyListDisabledError,
    AnyListError,
)
from app.services.checklist import (
    ChecklistItemNotFoundError,
    ChecklistNotReadyError,
    SessionAlreadyPushedError,
)
from app.services.usuals import DuplicateUsualItemNameError, UsualItemNotFoundError
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
from app.services.ingredient_aliases import (
    DuplicateIngredientAliasError,
    IngredientAliasNotFoundError,
    InvalidIngredientAliasError,
)
from app.services.unit_synonyms import (
    DuplicateUnitSynonymError,
    InvalidUnitSynonymError,
    UnitSynonymNotFoundError,
)
from app.services.coarse_ingredients import (
    CoarseIngredientNotFoundError,
    DuplicateCoarseIngredientError,
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
#
# 2026-09-13 code review — this section used to be ~30 individually hand-written
# `@app.exception_handler` functions, each a near-verbatim copy of the same 10-line
# "log a line, build the envelope, return a JSONResponse" template with different field names
# substituted in (main.py had grown to 721 lines, well past the project's own ~300-400 line
# guideline — CLAUDE.md > Code Architecture > File size and scope discipline). Replaced with
# two small factories covering the two shapes almost all of them actually are (see each
# factory's own docstring for which), registered from the tables below; only the handlers
# with a genuinely different shape (a dynamic status code, a non-None `detail`, or
# conditional logging) stay as their own explicit functions. Every status code, error code,
# message and log line is unchanged from before this refactor — verified against the full
# test suite, which already asserts on the ones that matter.


def _error_body(code: str, message: str, detail=None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "detail": detail}}


def _domain_error_handler(
    status_code: int, code: str, message: Callable[[Exception], str], *, log_level: int = logging.INFO
) -> Callable:
    """Factory for the common shape: an internal domain exception (NotFound / Duplicate /
    Invalid / a disabled §0c-or-§2 gate) whose message is entirely safe to both log and return
    to the client — it's built from OUR OWN exception's own attributes, never wraps arbitrary
    external error text (contrast `_external_error_handler` below, which is exactly for that
    case). `detail` is always None for this shape. Logs one consistent
    `"<message> (<method> <path>)"` line at `log_level` — a deliberate small normalisation
    versus the handlers this replaces (a couple, e.g. UsualItemNotFoundError's, previously
    logged no request context at all; the "disabled" gates previously used a differently-
    worded but equivalent log line) — every simple error now logs at least as much as before.
    """

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        text = message(exc)
        logger.log(log_level, "%s (%s %s)", text, request.method, request.url.path)
        return JSONResponse(status_code=status_code, content=_error_body(code, text, None))

    return handler


def _external_error_handler(status_code: int, code: str, message: str, *, log_prefix: str) -> Callable:
    """Factory for a call into an external system (Gemini/AnyList) whose own exception text
    can carry detail we don't control — CLAUDE.md > Security §4: this is a LAN-only app with
    no login, so raw internal/external exception text must never cross the wire to an
    unauthenticated client. The client always gets a fixed, safe `message` with `None`
    detail; the raw exception is still logged in full server-side for diagnostics."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        logger.warning("%s: %s %s (%s)", log_prefix, request.method, request.url.path, exc)
        return JSONResponse(status_code=status_code, content=_error_body(code, message, None))

    return handler


# exception type -> (status_code, error_code, message-builder, [log_level])
_DOMAIN_ERROR_HANDLERS: dict[type[Exception], Callable] = {
    RecipeNotFoundError: _domain_error_handler(
        404, "RECIPE_NOT_FOUND", lambda e: f"Recipe {e.recipe_id} not found."
    ),
    IngredientNotFoundError: _domain_error_handler(
        404,
        "INGREDIENT_NOT_FOUND",
        lambda e: f"Ingredient {e.ingredient_id} not found on recipe {e.recipe_id}.",
    ),
    StapleNotFoundError: _domain_error_handler(
        404, "STAPLE_NOT_FOUND", lambda e: f"Staple {e.staple_id} not found."
    ),
    DuplicateStapleNameError: _domain_error_handler(
        409, "DUPLICATE_STAPLE_NAME", lambda e: f'"{e.name}" is already on the staples list.'
    ),
    UsualItemNotFoundError: _domain_error_handler(
        404, "USUAL_ITEM_NOT_FOUND", lambda e: f"Usual item {e.usual_id} not found."
    ),
    DuplicateUsualItemNameError: _domain_error_handler(
        409, "DUPLICATE_USUAL_ITEM_NAME", lambda e: f'"{e.name}" is already in the usuals list.'
    ),
    ProductUnitNotFoundError: _domain_error_handler(
        404, "PRODUCT_UNIT_NOT_FOUND", lambda e: f"Product unit {e.product_unit_id} not found."
    ),
    DuplicateProductUnitNameError: _domain_error_handler(
        409,
        "DUPLICATE_PRODUCT_UNIT_NAME",
        lambda e: f'A purchase unit for "{e.ingredient_name}" already exists.',
    ),
    SubstitutionNotFoundError: _domain_error_handler(
        404, "SUBSTITUTION_NOT_FOUND", lambda e: f"Substitution {e.substitution_id} not found."
    ),
    DuplicateSubstitutionError: _domain_error_handler(
        409,
        "DUPLICATE_SUBSTITUTION",
        lambda e: f'A rule for "{e.original_name}" → "{e.substitute_name}" already exists.',
    ),
    InvalidSubstitutionError: _domain_error_handler(
        422, "INVALID_SUBSTITUTION", lambda e: e.reason
    ),
    IngredientAliasNotFoundError: _domain_error_handler(
        404, "INGREDIENT_ALIAS_NOT_FOUND", lambda e: f"Ingredient alias {e.alias_id} not found."
    ),
    DuplicateIngredientAliasError: _domain_error_handler(
        409,
        "DUPLICATE_INGREDIENT_ALIAS",
        lambda e: f'"{e.alias_name}" is already grouped under another name.',
    ),
    InvalidIngredientAliasError: _domain_error_handler(
        422, "INVALID_INGREDIENT_ALIAS", lambda e: e.reason
    ),
    UnitSynonymNotFoundError: _domain_error_handler(
        404, "UNIT_SYNONYM_NOT_FOUND", lambda e: f"Unit synonym {e.synonym_id} not found."
    ),
    DuplicateUnitSynonymError: _domain_error_handler(
        409,
        "DUPLICATE_UNIT_SYNONYM",
        lambda e: f'"{e.alias_unit}" is already mapped to another unit.',
    ),
    InvalidUnitSynonymError: _domain_error_handler(
        422, "INVALID_UNIT_SYNONYM", lambda e: e.reason
    ),
    CoarseIngredientNotFoundError: _domain_error_handler(
        404, "COARSE_INGREDIENT_NOT_FOUND", lambda e: f"Coarse ingredient {e.coarse_id} not found."
    ),
    DuplicateCoarseIngredientError: _domain_error_handler(
        409, "DUPLICATE_COARSE_INGREDIENT", lambda e: f'"{e.name}" is already a coarse ingredient.'
    ),
    SessionNotFoundError: _domain_error_handler(
        404, "SESSION_NOT_FOUND", lambda e: f"Planning session {e.session_id} not found."
    ),
    SessionSlotNotFoundError: _domain_error_handler(
        404,
        "SESSION_SLOT_NOT_FOUND",
        lambda e: f"Slot {e.slot_id} not found on session {e.session_id}.",
    ),
    SlotOrderMismatchError: _domain_error_handler(
        422,
        "SLOT_ORDER_MISMATCH",
        lambda e: "The reorder request must list exactly this session's current slot ids.",
    ),
    AiExtractionDisabledError: _domain_error_handler(
        503,
        "AI_EXTRACTION_DISABLED",
        lambda e: "Recipe capture is currently switched off. Ask the maintainer to enable it.",
        log_level=logging.WARNING,  # the highest-priority §0c gate working as designed, not a failure
    ),
    InvalidImageError: _domain_error_handler(422, "INVALID_IMAGE", lambda e: e.reason),
    ChecklistNotReadyError: _domain_error_handler(
        409,
        "CHECKLIST_NOT_CONSOLIDATED",
        lambda e: "This session has no shopping list yet — review and consolidate it first.",
    ),
    ChecklistItemNotFoundError: _domain_error_handler(
        404,
        "CHECKLIST_ITEM_NOT_FOUND",
        lambda e: f"Checklist item {e.item_id} not found on session {e.session_id}.",
    ),
    SessionAlreadyPushedError: _domain_error_handler(
        409,
        "SESSION_ALREADY_PUSHED",
        lambda e: (
            "This session was already pushed to AnyList. Push again only if you're sure "
            "(it will re-add items)."
        ),
    ),
    AnyListDisabledError: _domain_error_handler(
        503,
        "ANYLIST_DISABLED",
        lambda e: "AnyList sync is currently switched off. Ask the maintainer to enable it.",
        log_level=logging.WARNING,  # the §2 gate working as designed, not a failure
    ),
}

_EXTERNAL_ERROR_HANDLERS: dict[type[Exception], Callable] = {
    AiExtractionError: _external_error_handler(
        502,
        "EXTRACTION_FAILED",
        "Couldn't extract ingredients from that. Try again, or add the recipe manually.",
        log_prefix="AI extraction failed",
        # Already logged at ERROR with exc_info=True inside ai_extraction.py at the point of
        # failure too (CLAUDE.md > Diagnostics & Logging) — this WARNING is just the envelope
        # translation's own record of which request it surfaced on.
    ),
    AnyListAuthError: _external_error_handler(
        502,
        "ANYLIST_AUTH_FAILED",
        "Couldn't sign in to AnyList. Check the credentials (see Security §2).",
        log_prefix="AnyList auth failed",
    ),
    AnyListError: _external_error_handler(
        502,
        "ANYLIST_FAILED",
        "Couldn't reach AnyList — check your connection and try again.",
        log_prefix="AnyList call failed",
    ),
}

for _exc_type, _handler in {**_DOMAIN_ERROR_HANDLERS, **_EXTERNAL_ERROR_HANDLERS}.items():
    app.exception_handler(_exc_type)(_handler)


# --- the handlers below are genuinely bespoke: a dynamic status code, a non-None `detail`,
# or conditional logging that doesn't fit either factory shape above. ----------------------


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
            None,
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
