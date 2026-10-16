"""The Gemini call mechanics shared by every task: the Flash -> Flash-Lite fallback chain,
the check that real calls are enabled (docs/security.md > API enable switch), and the small response-cleaning helpers each call in ``calls.py`` uses
to sanitise what comes back.

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see docs/deferred-decisions.md > Deferred Decisions). Imports ``genai`` and
``settings`` at module level rather than inside functions specifically so
``app.services.ai_extraction.genai`` / ``...settings`` stay valid patch targets for tests
(``unittest.mock.patch`` resolves a dotted path by importing the module and walking
attributes — as long as ``__init__.py`` re-exports this module's ``genai``/``settings``
names, patching ``.Client`` or a settings flag there patches the exact same shared module
object every call site actually uses, package split or not).
"""

from __future__ import annotations

import logging
import time

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

# 2026-09-27 live-test finding: "gemini-flash-latest" defaults to thinking mode ON with no
# thinking_config set, and a "thinking" response's reasoning tokens are drawn from the SAME
# max_output_tokens budget as the visible completion. A 7-ingredient recipe (well under any
# reasonable size limit) hit finish_reason=MAX_TOKENS after only 316 *visible* output tokens
# -- the model had spent the rest of the 8192 cap on invisible chain-of-thought before ever
# writing the JSON body. The pre-existing MAX_TOKENS handling below then reported this as "the
# recipe was too large," which was never the real cause. None of this package's 5 call types
# benefit from chain-of-thought -- they're all deterministic, schema-constrained JSON
# extractions already run at temperature=0 -- so thinking is disabled outright rather than
# tuned to a smaller nonzero budget.
_THINKING_CONFIG = genai_types.ThinkingConfig(thinking_budget=0)


def _strip_code_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _clean_suggested_section(value: object) -> str | None:
    """Security > Prompt injection hardening — only ever a value from the fixed section vocabulary, or None."""
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


_RAW_LOG_CHARS = 200


def describe_raw(raw: str | None) -> str:
    """A bounded, safe stand-in for a model reply in a log line: its length plus the first
    ``_RAW_LOG_CHARS`` characters. The full reply derives from scraped pages / photographed
    cookbooks (untrusted, possibly personal) and can be 8k tokens, so it is never logged whole
    (docs/security.md > Prompt injection hardening, Personal Data Policy)."""
    raw = raw or ""
    head = raw[:_RAW_LOG_CHARS].replace("\n", " ")
    return f"{len(raw)} chars: {head!r}{'...' if len(raw) > _RAW_LOG_CHARS else ''}"


def _record_call(db: Session, **kwargs) -> None:
    """`ai_call_log.log_ai_call`, but a bookkeeping failure (a locked/full DB) is logged and
    swallowed so it can't replace the Gemini error actually being handled."""
    try:
        ai_call_log.log_ai_call(db, **kwargs)
    except Exception:  # noqa: BLE001
        logger.error(
            "AI %s: could not write the ai_call_log row (outcome=%s)",
            kwargs.get("call_type"), kwargs.get("outcome"), exc_info=True,
        )
        db.rollback()


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
    usage right after a success (Security > API usage observability, with the model that actually answered), returns the raw
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
            thinking_config=_THINKING_CONFIG,
        )
        started = time.monotonic()
        logger.info(
            "AI %s: calling %s (context=%s, %d part(s), attempt %d/%d)",
            call_type, model, context_id, len(parts), i + 1, len(_MODEL_CHAIN),
        )
        try:
            response = client.models.generate_content(model=model, contents=parts, config=config)
        except genai_errors.ClientError as exc:
            if _is_quota_error(exc):
                is_last = i == len(_MODEL_CHAIN) - 1
                _record_call(
                    db, call_type=call_type, model=model, outcome="quota", context_id=context_id
                )
                logger.warning(
                    "AI %s: %s quota-exhausted (429) after %.1fs, context=%s%s",
                    call_type,
                    model,
                    time.monotonic() - started,
                    context_id,
                    " — chain exhausted, will queue" if is_last else " — trying fallback",
                )
                if is_last:
                    raise AiQuotaExhaustedError(
                        "All Gemini models are over quota — the capture has been queued."
                    ) from exc
                continue
            _record_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error(
                "AI %s failed: %s client error %s after %.1fs, context=%s: %s",
                call_type, model, exc.code, time.monotonic() - started, context_id,
                str(exc)[:300], exc_info=True,
            )
            raise AiExtractionError(f"Gemini API returned an error ({exc.code}).") from exc
        except genai_errors.APIError as exc:
            _record_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error(
                "AI %s failed: %s API error (%s) after %.1fs, context=%s: %s",
                call_type, model, type(exc).__name__, time.monotonic() - started, context_id,
                str(exc)[:300], exc_info=True,
            )
            raise AiExtractionError("Gemini API returned an error.") from exc
        except Exception as exc:  # network / DNS / transport
            _record_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail=str(exc), context_id=context_id,
            )
            logger.error(
                "AI %s: %s call failed (%s) after %.1fs, context=%s: %s",
                call_type, model, type(exc).__name__, time.monotonic() - started, context_id,
                str(exc)[:300], exc_info=True,
            )
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
            _record_call(
                db, call_type=call_type, model=model, outcome="error",
                error_detail="response truncated at MAX_TOKENS", context_id=context_id,
                input_tokens=input_tokens, output_tokens=output_tokens,
            )
            logger.error(
                "AI %s: %s response truncated at MAX_TOKENS (%d output tokens), context=%s",
                call_type, model, output_tokens, context_id,
            )
            raise AiExtractionError(
                "The recipe was too large for one extraction pass and the response got cut "
                "off. Try splitting it into two recipes, or capture again with a shorter "
                "excerpt of the page."
            )

        text = response.text or ""
        if not text.strip():
            # A safety block / empty candidate used to fall through as "" and surface as the
            # misleading "could not be parsed". Say what actually happened.
            reason = (
                f"empty response (finish_reason={finish_reason or 'unknown'}, "
                f"candidates={len(candidates)})"
            )
            _record_call(
                db, call_type=call_type, model=model, outcome="error", error_detail=reason,
                context_id=context_id, input_tokens=input_tokens, output_tokens=output_tokens,
            )
            logger.error(
                "AI %s: %s returned no content after %.1fs, context=%s: %s",
                call_type, model, time.monotonic() - started, context_id, reason,
            )
            raise AiExtractionError("Gemini returned no content for that (it may have been blocked).")

        _record_call(
            db,
            call_type=call_type,
            model=model,
            outcome="success",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_id=context_id,
        )
        logger.info(
            "AI %s: %s answered in %.1fs (%s in / %s out tokens), context=%s",
            call_type, model, time.monotonic() - started, input_tokens, output_tokens, context_id,
        )
        if model != MODEL_ID:
            logger.info("AI %s: answered by fallback model %s", call_type, model)
        return text

    raise AiQuotaExhaustedError("All Gemini models are over quota.")  # unreachable
