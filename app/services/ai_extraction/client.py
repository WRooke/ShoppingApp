"""The Gemini call mechanics shared by every task: the Flash -> Flash-Lite fallback chain,
the §0c enable gate, and the small response-cleaning helpers each call in ``calls.py`` uses
to sanitise what comes back.

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). Imports ``genai`` and
``settings`` at module level rather than inside functions specifically so
``app.services.ai_extraction.genai`` / ``...settings`` stay valid patch targets for tests
(``unittest.mock.patch`` resolves a dotted path by importing the module and walking
attributes — as long as ``__init__.py`` re-exports this module's ``genai``/``settings``
names, patching ``.Client`` or a settings flag there patches the exact same shared module
object every call site actually uses, package split or not).
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.services import ai_call_log

from .prompts import _SECTION_VOCABULARY_SET
from .types import (
    FALLBACK_MODEL_ID,
    MODEL_ID,
    AiExtractionDisabledError,
    AiExtractionError,
    AiQuotaExhaustedError,
)

logger = logging.getLogger(__name__)

_MODEL_CHAIN = (MODEL_ID, FALLBACK_MODEL_ID)

# 2026-09-10 hand-testing: a real multi-part recipe (~20 ingredients across a main dish, a
# sauce, and a quick pickle) exceeded the original 4096-token cap mid-ingredient-array,
# producing a truncated, unparseable JSON body (a raw json.JSONDecodeError, logged and
# surfaced as a generic "could not be parsed" error — not a crash, but not an actionable
# message either). Raised to give genuinely large recipes real headroom; see also the
# finish_reason check in _call_gemini below, which now gives a specific, actionable error
# if a response is ever cut off again rather than a generic parse failure.
MAX_OUTPUT_TOKENS = 8192


def _strip_code_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _clean_suggested_section(value: object) -> str | None:
    """§0a — only ever a value from the fixed section vocabulary, or None."""
    if isinstance(value, str) and value in _SECTION_VOCABULARY_SET:
        return value
    return None


def _clean_title(value: object) -> str | None:
    """Capture-Fixes-Staged.md issue 1/2 — blank/whitespace-only titles collapse to None
    rather than saving an empty-looking name."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_servings(value: object) -> int | None:
    """Coerce to a positive int, or None. Guards against the model returning a range string
    ("4-6"), a float, or nonsense — recipes.base_servings is NOT NULL DEFAULT 4 (schema),
    so the review screen's pre-fill just falls back to its own default of 4 when this is
    None, same as before title/servings existed."""
    try:
        servings = int(value)
    except (TypeError, ValueError):
        return None
    return servings if servings >= 1 else None


def _require_enabled(task: str) -> None:
    if not settings.ai_extraction_enabled:
        logger.warning("AI %s refused: AI_EXTRACTION_ENABLED is not 'true'", task)
        raise AiExtractionDisabledError()


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.ClientError) and getattr(exc, "code", None) == 429


def _call_gemini(
    db: Session,
    *,
    call_type: str,
    context_id: str | None,
    system_prompt: str,
    response_schema: type[BaseModel],
    parts: list[genai_types.Part],
) -> str:
    """One Gemini structured-output call, with the Flash → Flash-Lite fallback chain. Logs
    usage right after a success (§0b, with the model that actually answered), returns the raw
    JSON text. A 429 from every model in the chain -> AiQuotaExhaustedError (caller queues).
    Any non-quota SDK/transport failure -> AiExtractionError immediately (no fallback — a
    weaker model won't fix a bad request or a network fault)."""
    client = genai.Client(api_key=settings.gemini_api_key)

    for i, model in enumerate(_MODEL_CHAIN):
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
        )
        try:
            response = client.models.generate_content(model=model, contents=parts, config=config)
        except genai_errors.ClientError as exc:
            if _is_quota_error(exc):
                is_last = i == len(_MODEL_CHAIN) - 1
                ai_call_log.log_ai_call(
                    db, call_type=call_type, model=model, outcome="quota", context_id=context_id
                )
                logger.warning(
                    "AI %s: %s quota-exhausted (429)%s",
                    call_type,
                    model,
                    " — chain exhausted, will queue" if is_last else " — trying fallback",
                )
                if is_last:
                    raise AiQuotaExhaustedError(
                        "All Gemini models are over quota — the capture has been queued."
                    ) from exc
                continue
            ai_call_log.log_ai_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error("AI %s failed: client error %s", call_type, exc.code, exc_info=True)
            raise AiExtractionError(f"Gemini API returned an error ({exc.code}).") from exc
        except genai_errors.APIError as exc:
            ai_call_log.log_ai_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error("AI %s failed: API error", call_type, exc_info=True)
            raise AiExtractionError("Gemini API returned an error.") from exc
        except Exception as exc:  # network / DNS / transport
            ai_call_log.log_ai_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error("AI %s: call failed", call_type, exc_info=True)
            raise AiExtractionError("Could not reach the Gemini API — check network/DNS.") from exc

        usage = response.usage_metadata
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)

        # A response cut off at MAX_OUTPUT_TOKENS mid-JSON used to surface only as a bare
        # json.JSONDecodeError from the caller's parse step — technically handled (logged,
        # turned into AiExtractionError, no crash) but with no actionable message. Detect it
        # here, defensively (SDK response shapes have moved before — see the model-ID note
        # above), so the caller gets a specific reason instead of a generic parse failure.
        candidates = getattr(response, "candidates", None) or []
        finish_reason = str(getattr(candidates[0], "finish_reason", "") or "") if candidates else ""
        if "MAX_TOKENS" in finish_reason.upper():
            ai_call_log.log_ai_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail="response truncated at MAX_TOKENS", context_id=context_id,
                input_tokens=input_tokens, output_tokens=output_tokens,
            )
            logger.error(
                "AI %s: %s response truncated at MAX_TOKENS (%d output tokens)",
                call_type, model, output_tokens,
            )
            raise AiExtractionError(
                "The recipe was too large for one extraction pass and the response got cut "
                "off. Try splitting it into two recipes, or capture again with a shorter "
                "excerpt of the page."
            )

        ai_call_log.log_ai_call(
            db,
            call_type=call_type,
            model=model,
            outcome="success",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_id=context_id,
        )
        if model != MODEL_ID:
            logger.info("AI %s: answered by fallback model %s", call_type, model)
        return response.text or ""

    raise AiQuotaExhaustedError("All Gemini models are over quota.")  # unreachable
