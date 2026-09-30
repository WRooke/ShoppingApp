"""The Gemini task calls, plus the capture_recipe() orchestrator that runs the first two of
them for a single recipe capture.

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). This is the module the
rest of the app actually calls into — ``__init__.py`` re-exports every name here unchanged,
so nothing outside this package needed to change for the split.

**Two separate Gemini calls per capture** (M2; originally three — the AI substitution-flagging
call was removed 2026-09-30, see CLAUDE.md > Deferred Decisions and
docs/ingredient-handling.md's Substitution section: manual substitution stays, only the
AI *suggestion* layer was judged to add too little value for the call it cost), each with its
own system prompt, ``response_schema`` and fake fixture:
  1. ``extract_recipe()``      — ingredients + cuisine/protein (NO section suggestion)
  2. ``suggest_sections()``    — per-ingredient store section (allow-list validated)
``capture_recipe()`` runs both and merges the result. Call 2 is enrichment — if it fails the
recipe is still usable (M3 turns a quota failure into a queued retry).

A further call, unrelated to capture, lives here too for the same "one small stable
interface" reason (CLAUDE.md > Ingredient Unit Handling > Admin reduction, 2026-09-12):
  3. ``classify_units()``      — is a never-before-seen unit spelling a same-magnitude
                                 variant of a standard unit (g/kg/ml/l/tsp/tbsp/cup)?
                                 Called from ``services/unit_synonyms.py > learn_new_units()``
                                 after an ingredient save, not from ``capture_recipe()``. Its
                                 input is the household's own typed data, not scraped/
                                 photographed content, so — uniquely among these — it does
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
from app.services import ingredient_aliases, progress_tracker

from .client import (
    _call_gemini,
    _clean_servings,
    _clean_suggested_section,
    _clean_title,
    _require_enabled,
    _strip_code_fence,
)
from .fixtures import (
    _FAKE_INGREDIENT_GROUPINGS,
    _FAKE_SECTION_MAP,
    _FAKE_UNIT_CLASSIFICATIONS,
    _pick_fake_fixture,
)
from .prompts import (
    _MAX_GROUPING_REASON_CHARS,
    _STANDARD_UNITS,
    EXTRACTION_SYSTEM_PROMPT,
    INGREDIENT_GROUPING_SYSTEM_PROMPT,
    MAX_GROUPING_INPUT_NAMES,
    MAX_INPUT_TEXT_CHARS,
    MAX_USER_HINT_CHARS,
    SECTIONS_SYSTEM_PROMPT,
    UNIT_CLASSIFICATION_SYSTEM_PROMPT,
    format_hint_sections,
    _wrap_untrusted,
)
from .schemas import _GExtraction, _GGroupings, _GSections, _GUnitClassifications
from .types import (
    AiExtractionError,
    ExtractedIngredient,
    ExtractionResult,
    GroupingSuggestion,
)

logger = logging.getLogger(__name__)


# --- call 1: recipe extraction -----------------------------------------------------


def build_extraction_system_prompt(db: Session) -> str:
    """`EXTRACTION_SYSTEM_PROMPT` + the dynamic household-alias hint sections (Fix 2, F2.3).
    Lives here, not in `prompts.py` — that module is deliberately pure prompt strings with no
    sibling-module dependency (see its own docstring); this function is the `db`-touching
    assembly step, same layer as every other task function in this file that already mixes
    `db` with cross-service imports (e.g. `progress_tracker` above).

    Only ever called from the real (non-fake-mode) path below — fake mode returns before
    reaching this, so it stays a true zero-DB-dependency fixture path, unaffected by whatever
    is or isn't in a household's `ingredient_aliases` table.

    §0a: `ingredient_aliases` rows are not reliably direct household input — an `alias_name`
    can be, and often will be, text an AI extraction pulled from a scraped webpage or photo,
    only passively reviewed on the capture screen, not necessarily retyped by a person. That is
    exactly the "content from outside the household's own direct input" pattern §0a exists for,
    so both hint sections are wrapped in `_wrap_untrusted()` (via `format_hint_sections()`)
    exactly like the recipe content itself — this is NOT `classify_units()`'s exemption (a unit
    typed into a form field at that exact moment, touching nothing else first); ingredient
    names have always been freetext with no allow-list, so this introduces no new *output*-
    validation surface, only a new *input*-trust question, already answered by wrapping it."""
    system_pairs = ingredient_aliases.hint_pairs(db, source="system")
    user_pairs = ingredient_aliases.hint_pairs(db, source="user")
    capped_user_pairs: list[tuple[str, str]] = []
    budget = MAX_USER_HINT_CHARS
    for pair in user_pairs:
        cost = len(f'- "{pair[0]}" means "{pair[1]}"\n')
        if cost > budget:
            break
        capped_user_pairs.append(pair)
        budget -= cost
    return EXTRACTION_SYSTEM_PROMPT + format_hint_sections(system_pairs, capped_user_pairs)


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
        system_prompt=build_extraction_system_prompt(db),
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
        title=_clean_title(data.get("title")),
        servings=_clean_servings(data.get("servings")),
    )


# --- call 2: section suggestion -------------------------------------------------


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


# --- call 3: unit-spelling classification (admin reduction, unrelated to capture) -------


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


# --- call 4: ingredient-grouping discovery (Fix 5, unrelated to capture) ---------------


def suggest_ingredient_groupings(
    db: Session, *, context_id: str | None = None, names: list[str]
) -> list[GroupingSuggestion]:
    """AI-suggested "these names are the same shopping item" groups across a household's own
    real ingredient vocabulary (CLAUDE.md > Deferred Decisions > AI-assisted ingredient-
    grouping discovery). A review artifact, never auto-applied — see
    `scripts/suggest_ingredient_groupings.py`, the only caller. `names` should already exclude
    already-aliased names (see `services/recipes.py::distinct_ingredient_names`).

    §0a: `names` is the household's full historical `recipe_ingredients.name` list, most of
    which passed through `extract_recipe()` from a scraped webpage or photo at some point and
    was only passively reviewed on capture-review, not necessarily retyped — exactly "content
    from outside the household's own direct input", so (unlike `classify_units()`, whose input
    is typed into a form field at that exact moment) this call's input IS wrapped in
    `_wrap_untrusted()`, same as every other call whose input can carry untrusted history."""
    deduped = sorted({n for n in names if n})
    if not deduped:
        return []
    if len(deduped) > MAX_GROUPING_INPUT_NAMES:
        logger.warning(
            "AI suggest_ingredient_groupings: input truncated %d -> %d names",
            len(deduped), MAX_GROUPING_INPUT_NAMES,
        )
        deduped = deduped[:MAX_GROUPING_INPUT_NAMES]

    if settings.ai_extraction_fake_mode:
        name_set = set(deduped)
        out = [
            GroupingSuggestion(
                names=g["names"], suggested_canonical=g["suggested_canonical"], reason=g["reason"]
            )
            for g in _FAKE_INGREDIENT_GROUPINGS
            if name_set.issuperset(g["names"])
        ]
        logger.info("AI suggest_ingredient_groupings: FAKE MODE — %d group(s)", len(out))
        return out

    _require_enabled("suggest_ingredient_groupings")
    parts = [genai_types.Part.from_text(text=_wrap_untrusted(json.dumps(deduped)))]
    raw = _call_gemini(
        db,
        call_type="suggest_ingredient_groupings",
        context_id=context_id,
        system_prompt=INGREDIENT_GROUPING_SYSTEM_PROMPT,
        response_schema=_GGroupings,
        parts=parts,
    )
    try:
        data = json.loads(_strip_code_fence(raw))
        name_set = set(deduped)
        groups: list[GroupingSuggestion] = []
        for g in data.get("groups", []):
            valid_names = [n for n in g.get("names", []) if n in name_set]
            canonical = g.get("suggested_canonical")
            if len(valid_names) < 2 or not canonical:
                continue
            reason = g.get("reason")
            if isinstance(reason, str) and len(reason) > _MAX_GROUPING_REASON_CHARS:
                logger.info(
                    "AI suggest_ingredient_groupings: dropped an overlong reason (%d chars)",
                    len(reason),
                )
                reason = None
            groups.append(
                GroupingSuggestion(names=valid_names, suggested_canonical=canonical, reason=reason)
            )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("AI suggest_ingredient_groupings: bad response %r", raw, exc_info=True)
        raise AiExtractionError("Gemini's grouping response could not be parsed.") from exc

    logger.info("AI suggest_ingredient_groupings: %d group(s)", len(groups))
    return groups


# --- orchestrator ------------------------------------------------------------

# Real, backend-driven step names for the capture progress UI (CLAUDE.md > UI/UX > Real
# progress indicators) — polled via GET /api/v1/recipes/capture/progress/{token}, see
# app/services/progress_tracker.py. Order matches the actual call sequence below. Was
# ["extract", "sections", "substitutions"] until the AI substitution-flagging call was
# removed 2026-09-30 (manual substitution stays — see the module docstring).
PROGRESS_STEPS = ["extract", "sections"]


def capture_recipe(
    db: Session,
    *,
    call_type: str,
    context_id: str | None = None,
    text: str | None = None,
    image_base64: str | None = None,
    image_media_type: str | None = None,
    progress_token: str | None = None,
) -> ExtractionResult:
    """Run both calls and merge. Call 1 (extraction) is required — its failure propagates.
    Call 2 is enrichment: an AiExtractionError from it is logged and swallowed (the recipe is
    still usable). M3 turns a swallowed *quota* failure into a queued retry instead.

    `progress_token`, when given, drives `app.services.progress_tracker` — one real step per
    Gemini call, reported active/done/failed as each one actually happens (2026-09-23,
    replacing the frontend's old client-side-only rotating label with real backend state).
    A falsy token (the normal case for anything that isn't a user-initiated capture, e.g. the
    capture_queue retry poller) makes every progress_tracker call below a no-op.

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

    progress_tracker.start(progress_token, PROGRESS_STEPS)
    progress_tracker.step_active(progress_token, "extract")
    try:
        result = _pkg.extract_recipe(
            db,
            call_type=call_type,
            context_id=context_id,
            text=text,
            image_base64=image_base64,
            image_media_type=image_media_type,
        )
    except AiExtractionError as exc:
        progress_tracker.step_failed(progress_token, "extract", str(exc))
        raise
    progress_tracker.step_done(progress_token, "extract")
    names = [i.name for i in result.ingredients]

    progress_tracker.step_active(progress_token, "sections")
    try:
        sections = _pkg.suggest_sections(db, context_id=context_id, ingredient_names=names)
        for ing in result.ingredients:
            ing.suggested_section = sections.get(ing.name)
        progress_tracker.step_done(progress_token, "sections")
    except AiExtractionError as exc:
        logger.warning("capture_recipe: section suggestion failed — will retry via the queue", exc_info=True)
        result.pending_tasks.append("suggest_sections")
        progress_tracker.step_failed(progress_token, "sections", str(exc))

    return result
