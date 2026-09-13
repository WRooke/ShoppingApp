"""Model identity, public result types, and exceptions for AI extraction.

Part of the ``ai_extraction`` package (CLAUDE.md > Code Architecture & Maintainability >
File size and scope discipline; split from the former single-file module at the Phase 5
review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). Deliberately the package's only
module with **no** imports from any of its siblings — ``client.py`` and ``calls.py`` both
import from here, and keeping this one dependency-free is what keeps that a one-way edge
rather than a cycle (``ExtractionResult.model`` needs ``MODEL_ID`` at class-definition time,
and ``client.py`` needs to raise the exception classes below — if the model-ID constants
lived in ``client.py`` instead, those two facts would point at each other).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Primary model, then the fallback the chain drops to on a 429. See CLAUDE.md > AI Provider
# Migration > Fallback & retry. A 429 from BOTH -> AiQuotaExhaustedError -> the caller queues.
#
# Floating aliases, not pinned versions (maintainer's call, 2026-09-07 at M7): the spec's
# original pin `gemini-2.5-flash` was retired by Google between the spec being written
# (2026-09-06) and M7 being run (2026-09-07) — a newly-created key gets 404
# "no longer available to new users". `*-latest` always resolves to the current
# flash / flash-lite, so this class of break can't recur. Trade-off accepted: a model
# swap underneath us could shift extraction behaviour without a code change — the capture
# review step (user confirms every ingredient before save) is the backstop.
MODEL_ID = "gemini-flash-latest"
FALLBACK_MODEL_ID = "gemini-flash-lite-latest"


@dataclass
class ExtractedIngredient:
    name: str
    quantity: float
    unit: str | None
    preparation: str | None
    original_text: str
    suggested_section: str | None = None  # populated by suggest_sections(), not extract_recipe()


@dataclass(frozen=True)
class SubstitutionFlag:
    original: str
    suggested_substitute: str
    note: str | None = None


@dataclass
class ExtractionResult:
    """2026-09-13 code review: this used to also carry `input_tokens`/`output_tokens`, hardcoded
    to 0 in every branch of `extract_recipe()` and never actually read by anything (confirmed by
    a repo-wide grep) — the real per-call token counts are computed inside `client.py >
    _call_gemini()` and logged straight to `ai_call_log` (§0b), which is the single source of
    truth for usage/diagnostics. Removed rather than wired through, since nothing needs a second
    copy of that data riding on this object. If a future feature wants a capture's own token
    cost, read it from `ai_call_log` by `context_id`, don't resurrect these fields."""

    cuisine: str | None
    protein: str | None
    ingredients: list[ExtractedIngredient]
    # Capture-Fixes-Staged.md issues 1 & 2 (2026-09-07) — title/servings were never
    # extracted at all; the review screen showed a blank name box and a hardcoded "4". Both
    # are AI-prefilled here but stay fully editable on the review screen (CLAUDE.md >
    # Recipe Capture > After extraction).
    title: str | None = None
    servings: int | None = None
    substitution_flags: list[SubstitutionFlag] = field(default_factory=list)
    # Enrichment sub-tasks that failed/queued during capture_recipe() and are still owed to
    # the recipe (Phase 3.9 M6). Currently only "suggest_sections" is ever retried; a failed
    # "flag_substitutions" is not (it's only useful in the interactive review). The save path
    # writes this to recipes.ai_tasks_pending and enqueues the retry.
    pending_tasks: list[str] = field(default_factory=list)
    model: str = MODEL_ID


class AiExtractionError(Exception):
    """A Gemini call failed, or succeeded but returned an unparseable body. Callers translate
    this to the {"ok": false, "error": ...} envelope (EXTRACTION_FAILED)."""


class AiQuotaExhaustedError(AiExtractionError):
    """Both the primary and fallback Gemini models returned 429 (RESOURCE_EXHAUSTED).
    Subclass of AiExtractionError so ``except AiExtractionError`` still catches it — but a
    caller that can queue the work (capture endpoints) catches this specifically. See
    CLAUDE.md > AI Provider Migration > Fallback & retry / Queueing."""


class AiExtractionDisabledError(Exception):
    """Raised instead of ever calling the real API when settings.ai_extraction_enabled is
    False (the default) — CLAUDE.md > Security > §0c. Fixed by the maintainer setting
    AI_EXTRACTION_ENABLED=true, never by an agent editing that value."""

    def __init__(self) -> None:
        super().__init__(
            "AI recipe extraction is disabled (AI_EXTRACTION_ENABLED is not 'true' in .env). "
            "This is a deliberate default — see CLAUDE.md > Security > §0c."
        )
