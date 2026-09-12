"""The four Gemini task calls, plus the capture_recipe() orchestrator that runs the first
three of them for a single recipe capture.

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). This is the module the
rest of the app actually calls into — ``__init__.py`` re-exports every name here unchanged,
so nothing outside this package needed to change for the split.

**Three separate Gemini calls per capture** (M2), each with its own system prompt,
``response_schema`` and fake fixture:
  1. ``extract_recipe()``      — ingredients + cuisine/protein (NO section suggestion)
  2. ``flag_substitutions()``  — per-recipe substitution candidates (enrichment; M4 wires
                                 the confirm/decline UI)
  3. ``suggest_sections()``    — per-ingredient store section (allow-list validated)
``capture_recipe()`` runs all three and merges the result. Calls 2 and 3 are enrichment —
if they fail the recipe is still usable (M3 turns a quota failure into a queued retry).

A fourth call, unrelated to capture, lives here too for the same "one small stable
interface" reason (CLAUDE.md > Ingredient Unit Handling > Admin reduction, 2026-09-12):
  4. ``classify_units()``      — is a never-before-seen unit spelling a same-magnitude
                                 variant of a standard unit (g/kg/ml/l/tsp/tbsp/cup)?
                                 Called from ``services/unit_synonyms.py > learn_new_units()``
                                 after an ingredient save, not from ``capture_recipe()``. Its
                                 input is the household's own typed data, not scraped/
                                 photographed content, so — uniquely among the four — it does
                                 NOT wrap its input in the §0a untrusted-content delimiter;
                                 the output is still allow-list validated regardless.
"""

from __future__ import annotations

import base64
import json
import logging

from google.genai import types as genai_types
from sqlalchemy.orm import Session

from app.config import settings

from .client import (
    _call_gemini,
    _clean_servings,
    _clean_suggested_section,
    _clean_title,
    _require_enabled,
    _strip_code_fence,
)
from .fixtures import (
    _FAKE_SECTION_MAP,
    _FAKE_SUBSTITUTION_FLAGS,
    _FAKE_UNIT_CLASSIFICATIONS,
    _pick_fake_fixture,
)
from .prompts import (
    _MAX_SUBSTITUTION_NOTE_CHARS,
    _STANDARD_UNITS,
    EXTRACTION_SYSTEM_PROMPT,
    MAX_INPUT_TEXT_CHARS,
    SECTIONS_SYSTEM_PROMPT,
    SUBSTITUTIONS_SYSTEM_PROMPT,
    UNIT_CLASSIFICATION_SYSTEM_PROMPT,
    _wrap_untrusted,
)
from .schemas import _GExtraction, _GFlags, _GSections, _GUnitClassifications
from .types import (
    AiExtractionError,
    ExtractedIngredient,
    ExtractionResult,
    SubstitutionFlag,
)

logger = logging.getLogger(__name__)


# --- call 1: recipe extraction -----------------------------------------------------


def extract_recipe(
    db: Session,
    *,
    call_type: str,
    context_id: str | None = None,
    text: str | None = None,
    image_base64: str | None = None,
    image_media_type: str | None = None,
) -> ExtractionResult:
    """Ingredients + cuisine/protein from recipe text and/or an image. No section suggestion
    (that's suggest_sections()). Fake mode returns a canned fixture."""
    if not text and not image_base64:
        raise ValueError("extract_recipe requires text and/or image_base64")

    if settings.ai_extraction_fake_mode:
        fixture = _pick_fake_fixture(text or image_base64 or "")
        logger.info("AI extract_recipe: FAKE MODE — fixture %r", fixture["_label"])
        return ExtractionResult(
            cuisine=fixture["cuisine"],
            protein=fixture["protein"],
            ingredients=[
                ExtractedIngredient(
                    name=i["name"],
                    quantity=float(i["quantity"]),
                    unit=i["unit"],
                    preparation=i["preparation"],
                    original_text=i["original_text"],
                    suggested_section=None,
                )
                for i in fixture["ingredients"]
            ],
            input_tokens=0,
            output_tokens=0,
            title=fixture.get("title"),
            servings=fixture.get("servings"),
        )

    _require_enabled("extract_recipe")

    if text and len(text) > MAX_INPUT_TEXT_CHARS:
        logger.warning("AI extract_recipe: input truncated %d -> %d", len(text), MAX_INPUT_TEXT_CHARS)
        text = text[:MAX_INPUT_TEXT_CHARS]

    parts: list[genai_types.Part] = []
    if image_base64:
        parts.append(
            genai_types.Part.from_bytes(
                data=base64.b64decode(image_base64), mime_type=image_media_type or "image/jpeg"
            )
        )
    if text:
        parts.append(genai_types.Part.from_text(text=_wrap_untrusted(text)))

    raw = _call_gemini(
        db,
        call_type=call_type,
        context_id=context_id,
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        response_schema=_GExtraction,
        parts=parts,
    )
    try:
        data = json.loads(_strip_code_fence(raw))
        ingredients = [
            ExtractedIngredient(
                name=i["name"],
                quantity=float(i["quantity"]),
                unit=i.get("unit"),
                preparation=i.get("preparation"),
                original_text=i.get("original_text", ""),
                suggested_section=None,
            )
            for i in data["ingredients"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("AI extract_recipe: bad response %r", raw, exc_info=True)
        raise AiExtractionError("Gemini's response could not be parsed.") from exc

    logger.info("AI extract_recipe: %d ingredient(s)", len(ingredients))
    return ExtractionResult(
        cuisine=data.get("cuisine"),
        protein=data.get("protein"),
        ingredients=ingredients,
        input_tokens=0,
        output_tokens=0,
        title=_clean_title(data.get("title")),
        servings=_clean_servings(data.get("servings")),
    )


# --- call 2: substitution flagging ----------------------------------------------


def flag_substitutions(
    db: Session, *, context_id: str | None, ingredient_names: list[str]
) -> list[SubstitutionFlag]:
    """Per-recipe substitution candidates for the given ingredient names. Enrichment — the
    caller treats failure as "no flags". Fake mode returns canned flags for known names."""
    names = [n for n in ingredient_names if n]
    if not names:
        return []

    if settings.ai_extraction_fake_mode:
        out = []
        for n in names:
            if n in _FAKE_SUBSTITUTION_FLAGS:
                sub, note = _FAKE_SUBSTITUTION_FLAGS[n]
                out.append(SubstitutionFlag(original=n, suggested_substitute=sub, note=note))
        logger.info("AI flag_substitutions: FAKE MODE — %d flag(s)", len(out))
        return out

    _require_enabled("flag_substitutions")
    parts = [genai_types.Part.from_text(text=_wrap_untrusted(json.dumps(names)))]
    raw = _call_gemini(
        db,
        call_type="flag_substitutions",
        context_id=context_id,
        system_prompt=SUBSTITUTIONS_SYSTEM_PROMPT,
        response_schema=_GFlags,
        parts=parts,
    )
    try:
        data = json.loads(_strip_code_fence(raw))
        name_set = set(names)
        flags = []
        for f in data.get("flags", []):
            if f.get("original") not in name_set or not f.get("suggested_substitute"):
                continue
            note = f.get("note")
            # Capture-Fixes-Staged.md issue 4 (2026-09-07) — the prompt above asks for a
            # ~10-word note, but nothing stops the model ignoring that. Cheap defensive
            # backstop rather than trusting the wording alone: an overlong note (the kind of
            # "why this works" rationale the maintainer doesn't want, e.g. "Regular butter
            # contains milk solids that brown and burn faster than ghee...") is dropped, not
            # truncated mid-sentence.
            if isinstance(note, str) and len(note) > _MAX_SUBSTITUTION_NOTE_CHARS:
                logger.info(
                    "AI flag_substitutions: dropped an overlong note (%d chars) for %r",
                    len(note), f.get("original"),
                )
                note = None
            flags.append(
                SubstitutionFlag(
                    original=f["original"],
                    suggested_substitute=f["suggested_substitute"],
                    note=note,
                )
            )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("AI flag_substitutions: bad response %r", raw, exc_info=True)
        raise AiExtractionError("Gemini's substitution response could not be parsed.") from exc

    logger.info("AI flag_substitutions: %d flag(s)", len(flags))
    return flags


# --- call 3: section suggestion -------------------------------------------------


def suggest_sections(
    db: Session, *, context_id: str | None, ingredient_names: list[str]
) -> dict[str, str]:
    """{ingredient name: section} for names the model is confident about. Sections are
    allow-list validated (§0a). Enrichment — caller treats failure as "no sections"."""
    names = [n for n in ingredient_names if n]
    if not names:
        return {}

    if settings.ai_extraction_fake_mode:
        out = {n: _FAKE_SECTION_MAP[n] for n in names if n in _FAKE_SECTION_MAP}
        logger.info("AI suggest_sections: FAKE MODE — %d section(s)", len(out))
        return out

    _require_enabled("suggest_sections")
    parts = [genai_types.Part.from_text(text=_wrap_untrusted(json.dumps(names)))]
    raw = _call_gemini(
        db,
        call_type="suggest_sections",
        context_id=context_id,
        system_prompt=SECTIONS_SYSTEM_PROMPT,
        response_schema=_GSections,
        parts=parts,
    )
    try:
        data = json.loads(_strip_code_fence(raw))
        name_set = set(names)
        out: dict[str, str] = {}
        for entry in data.get("sections", []):
            n = entry.get("name")
            section = _clean_suggested_section(entry.get("section"))
            if n in name_set and section is not None:
                out[n] = section
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("AI suggest_sections: bad response %r", raw, exc_info=True)
        raise AiExtractionError("Gemini's section response could not be parsed.") from exc

    logger.info("AI suggest_sections: %d section(s)", len(out))
    return out


# --- call 4: unit-spelling classification (admin reduction, unrelated to capture) -------


def classify_units(
    db: Session, *, context_id: str | None = None, unit_texts: list[str]
) -> dict[str, str]:
    """{raw unit string: canonical standard unit} for entries the model is confident are a
    same-magnitude spelling variant of g/kg/ml/l/tsp/tbsp/cup — never a genuinely different or
    discrete unit (allow-list validated against _STANDARD_UNITS regardless of what comes
    back). Called by services/unit_synonyms.py > learn_new_units(), which treats any failure
    here (disabled/quota/parse/network) as "no match" — the unit is simply left as its own
    distinct unit, exactly today's behaviour without this feature. See CLAUDE.md >
    Ingredient Unit Handling > Admin reduction."""
    texts = [u for u in unit_texts if u]
    if not texts:
        return {}

    if settings.ai_extraction_fake_mode:
        out = {u: _FAKE_UNIT_CLASSIFICATIONS[u] for u in texts if u in _FAKE_UNIT_CLASSIFICATIONS}
        logger.info("AI classify_units: FAKE MODE — %d match(es)", len(out))
        return out

    _require_enabled("classify_units")
    # Household's own typed input, not scraped/photographed content — this is the one call in
    # this package that skips the §0a untrusted-content delimiter (see prompts.py docstring).
    parts = [genai_types.Part.from_text(text=json.dumps(texts))]
    raw = _call_gemini(
        db,
        call_type="classify_units",
        context_id=context_id,
        system_prompt=UNIT_CLASSIFICATION_SYSTEM_PROMPT,
        response_schema=_GUnitClassifications,
        parts=parts,
    )
    try:
        data = json.loads(_strip_code_fence(raw))
        text_set = set(texts)
        out: dict[str, str] = {}
        for entry in data.get("units", []):
            unit = entry.get("unit")
            canonical = entry.get("canonical")
            if unit in text_set and canonical in _STANDARD_UNITS and canonical != unit:
                out[unit] = canonical
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("AI classify_units: bad response %r", raw, exc_info=True)
        raise AiExtractionError("Gemini's unit classification response could not be parsed.") from exc

    logger.info("AI classify_units: %d match(es)", len(out))
    return out


# --- orchestrator ------------------------------------------------------------


def capture_recipe(
    db: Session,
    *,
    call_type: str,
    context_id: str | None = None,
    text: str | None = None,
    image_base64: str | None = None,
    image_media_type: str | None = None,
) -> ExtractionResult:
    """Run all three calls and merge. Call 1 (extraction) is required — its failure
    propagates. Calls 2 and 3 are enrichment: an AiExtractionError from either is logged and
    swallowed (the recipe is still usable). M3 turns a swallowed *quota* failure into a
    queued retry instead.

    Calls through the package's own attributes (``_pkg.extract_recipe`` etc.), not the bare
    module-local names, deliberately: before the Phase 5-review package split, this
    orchestrator and the three calls it makes all lived in one file, so a test patching
    ``app.services.ai_extraction.suggest_sections`` was — by coincidence of being one
    module — already patching exactly what this function called. Routing through the
    package keeps that patchability (see ``tests/services/test_capture_queue.py``'s
    "section suggestion fails" case) without the caller having to know these functions now
    physically live in ``calls.py`` alongside it. The import is deferred to call time — a
    module-level import here would bind ``_pkg`` to the package while its own ``__init__``
    is still mid-import (this module is one of the things it imports), before ``__init__``
    has reached the lines that actually populate ``extract_recipe`` etc. on it."""
    from app.services import ai_extraction as _pkg

    result = _pkg.extract_recipe(
        db,
        call_type=call_type,
        context_id=context_id,
        text=text,
        image_base64=image_base64,
        image_media_type=image_media_type,
    )
    names = [i.name for i in result.ingredients]

    try:
        sections = _pkg.suggest_sections(db, context_id=context_id, ingredient_names=names)
        for ing in result.ingredients:
            ing.suggested_section = sections.get(ing.name)
    except AiExtractionError:
        logger.warning("capture_recipe: section suggestion failed — will retry via the queue", exc_info=True)
        result.pending_tasks.append("suggest_sections")

    try:
        result.substitution_flags = _pkg.flag_substitutions(
            db, context_id=context_id, ingredient_names=names
        )
    except AiExtractionError:
        # Not retried post-capture — it's only useful in the interactive review. No flags
        # simply means the user swaps manually later if they want.
        logger.warning("capture_recipe: substitution flagging failed — continuing without", exc_info=True)

    return result
