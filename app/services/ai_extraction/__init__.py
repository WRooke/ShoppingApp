"""Google Gemini API integration — recipe capture AI calls.

Phase 3.9 (see CLAUDE.md > AI Provider Migration). One integration behind one small stable
interface (CLAUDE.md > Code Architecture & Maintainability > "External integrations sit
behind a small, stable interface"): the rest of the app calls ``capture_recipe()`` (the
orchestrator) or the individual task functions, never ``google.genai`` directly. No
``fastapi`` import anywhere in this package.

**Package layout** (split from a single ~860-line file at the Phase 5 review, 2026-09-12 —
see CLAUDE.md > Deferred Decisions; the old file's own ``# NOTE`` had this plan staged since
the Phase 3.9 M-review):
  * ``types.py``    — model-ID constants + the public dataclasses + exception classes.
                       No imports from any sibling module (see its own docstring for why —
                       keeping this one dependency-free is what keeps the package's import
                       graph a one-way line instead of a cycle).
  * ``prompts.py``   — every system prompt + the §0a untrusted-content wrapper.
  * ``schemas.py``   — the Gemini ``response_schema`` Pydantic models.
  * ``fixtures.py``  — canned fake-mode responses (§0c).
  * ``client.py``    — ``_call_gemini`` (the Flash→Flash-Lite fallback chain + §0b usage
                       logging), the §0c enable gate, and the response-cleaning helpers.
  * ``calls.py``     — the four task functions + the ``capture_recipe()`` orchestrator —
                       this is what every other module in the app actually calls.

This is a **pure structural move** — every name below resolved from this package exactly as
it did from the old single file; nothing outside this package changed. The only substance
change is in ``client.py``'s module docstring, which explains why ``genai``/``settings`` are
imported there (and re-exported here) rather than referenced through a different indirection
— so that `patch("app.services.ai_extraction.genai.Client", ...)`-style test patches (see
``tests/services/test_ai_extraction.py``) keep resolving to the same shared module object.

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

Two highest-priority standing rules (CLAUDE.md > Security §0a/§0c):
  * **§0c** — a real call needs ``settings.ai_extraction_enabled`` (off by default);
    ``settings.ai_extraction_fake_mode`` returns canned fixtures with no network. No agent
    flips the switch; the maintainer is asked before any real call even once it's on.
  * **§0a** — untrusted recipe content is wrapped in a non-guessable delimiter, the system
    prompt says treat it as data, input length is capped, and fixed-vocabulary fields
    (``suggested_section``) are allow-list validated on the way out.
§0b: every attempt is logged to ``ai_call_log`` (task / model / outcome / tokens).
"""

from __future__ import annotations

# Re-exported so a patch path like "app.services.ai_extraction.genai.Client" or
# "app.services.ai_extraction.settings.ai_extraction_enabled" keeps resolving — both names
# are the real shared module objects `client.py` imports, not copies, so patching an
# attribute on either here patches the exact object every call in the package actually uses.
from google import genai  # noqa: F401

from app.config import settings  # noqa: F401

from .calls import (
    capture_recipe,
    classify_units,
    extract_recipe,
    flag_substitutions,
    suggest_sections,
)
from .client import (
    MAX_OUTPUT_TOKENS,
    _call_gemini,
    _clean_servings,
    _clean_suggested_section,
    _clean_title,
    _is_quota_error,
    _require_enabled,
    _strip_code_fence,
)
from .fixtures import (
    _FAKE_FIXTURES,
    _FAKE_SECTION_MAP,
    _FAKE_SUBSTITUTION_FLAGS,
    _FAKE_UNIT_CLASSIFICATIONS,
    _pick_fake_fixture,
)
from .prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    MAX_INPUT_TEXT_CHARS,
    SECTIONS_SYSTEM_PROMPT,
    SUBSTITUTIONS_SYSTEM_PROMPT,
    UNIT_CLASSIFICATION_SYSTEM_PROMPT,
)
from .schemas import (
    _GExtraction,
    _GFlags,
    _GIngredient,
    _GSectionEntry,
    _GSections,
    _GUnitClassifications,
    _GUnitEntry,
)
from .types import (
    FALLBACK_MODEL_ID,
    MODEL_ID,
    AiExtractionDisabledError,
    AiExtractionError,
    AiQuotaExhaustedError,
    ExtractedIngredient,
    ExtractionResult,
    SubstitutionFlag,
)

__all__ = [
    "genai",
    "settings",
    "capture_recipe",
    "classify_units",
    "extract_recipe",
    "flag_substitutions",
    "suggest_sections",
    "MAX_OUTPUT_TOKENS",
    "MAX_INPUT_TEXT_CHARS",
    "MODEL_ID",
    "FALLBACK_MODEL_ID",
    "EXTRACTION_SYSTEM_PROMPT",
    "SECTIONS_SYSTEM_PROMPT",
    "SUBSTITUTIONS_SYSTEM_PROMPT",
    "UNIT_CLASSIFICATION_SYSTEM_PROMPT",
    "AiExtractionDisabledError",
    "AiExtractionError",
    "AiQuotaExhaustedError",
    "ExtractedIngredient",
    "ExtractionResult",
    "SubstitutionFlag",
]
