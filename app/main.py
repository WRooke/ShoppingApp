"""FastAPI application entry point.

Run directly (``python -m app.main``) or via uvicorn (``uvicorn app.main:app``).
start.bat uses the former.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import init_db
from app.log_config import setup_logging
from app.routers import (
    anylist,
    checklist,
    diagnostics,
    health,
    recipes,
    sessions,
)
from app.routers import settings as settings_router

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "=== ShoppingApp starting (port %s, log level %s) ===", settings.port, settings.log_level
    )
    try:
        init_db()
    except Exception:
        logger.error("Database initialisation failed during startup", exc_info=True)
        raise
    logger.info("Startup complete - diagnostics available at /#/diagnostics")
    yield
    logger.info("=== ShoppingApp shutting down ===")


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
    return JSONResponse(status_code=204, content=None)


if __name__ == "__main__":
    import uvicorn

    # log_config=None: uvicorn's default logging setup detaches uvicorn.access from the
    # root logger (its own handler, propagate=False), which silently drops every request
    # access log from logs/app.log and the diagnostics ring buffer even though the console
    # still shows them. Passing None leaves our own setup_logging() config untouched instead.
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=settings.port, reload=False, log_config=None
    )
