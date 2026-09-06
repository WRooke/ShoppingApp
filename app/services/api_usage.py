"""Cost calculation and usage logging for Claude API calls (see CLAUDE.md > Data Model >
`api_usage`, CLAUDE.md > Diagnostics & Logging — "every external API call ... log the attempt
at INFO, log success at INFO, log failure at ERROR" — and CLAUDE.md > Security §0b, API Usage
Observability).

**2026-09-06:** this module used to also enforce a hard AU$0.50 lifetime spend cap
(`enforce_spend_cap()`, `SpendCapExceededError`, `get_spend_cap_usd_cents()`,
`estimate_worst_case_cost_usd_cents()`). That cap has been removed — see the Non-Negotiable
Operating Rules banner and Security §0b in CLAUDE.md for why (short version: Anthropic billing
is prepaid, not an open invoice, so there was nothing left for an in-app dollar ceiling to
protect against). What's left is purely observational: calculate what a call cost, log it, and
let the diagnostics page total it up. Nothing in this module refuses a call any more — the
enable switch and fake mode in `claude_client.py` (Security §0c) are what gate real calls now.

Deliberately separate from `claude_client.py` conceptually — this is where the cost math and
the `api_usage`/`api_usage_resets` tables live — but `claude_client.py` still imports and calls
straight into `log_api_usage()` after every real API call, so a real call can never go unlogged
because a caller forgot. See CLAUDE.md > Code Architecture & Maintainability for why
`claude_client.py` is otherwise the DB-free one.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.diagnostics import ApiUsage, ApiUsageReset

logger = logging.getLogger(__name__)

# USD per 1M tokens. Phase 3.9 M5 removes this whole module (Gemini's free tier has no
# per-call cost — see CLAUDE.md > AI Provider Migration). Until then the Gemini models are
# listed at $0 so log_api_usage() keeps working during M1-M4 without a pricing lookup error.
_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "gemini-2.5-flash": {"input": 0.0, "output": 0.0},
    "gemini-2.5-flash-lite": {"input": 0.0, "output": 0.0},
}


class UnknownModelPricingError(Exception):
    """Raised when cost can't be calculated because the model isn't in the pricing table."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"No pricing entry for model {model!r}")


def calculate_cost_usd_cents(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cents for one call, given token counts. Raises UnknownModelPricingError for an
    unpriced model rather than silently returning 0 — a wrong-but-plausible spend figure on
    the diagnostics page is worse than a loud failure (see CLAUDE.md > Diagnostics & Logging)."""
    pricing = _PRICING_USD_PER_MTOK.get(model)
    if pricing is None:
        raise UnknownModelPricingError(model)
    dollars = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return dollars * 100


def get_last_reset_at(db: Session):
    """The most recent time the diagnostics "reset spend tracker" button was used, or None if
    it never has been. See `reset_api_usage_display()` below."""
    return db.query(func.max(ApiUsageReset.reset_at)).scalar()


def get_lifetime_totals(db: Session) -> tuple[float, int, int, object]:
    """True lifetime totals across every api_usage row ever recorded, unaffected by any
    display reset — (spend_usd_cents, input_tokens, output_tokens, last_call_timestamp)."""
    spend_cents, in_tok, out_tok, last_ts = db.query(
        func.coalesce(func.sum(ApiUsage.cost_usd_cents), 0.0),
        func.coalesce(func.sum(ApiUsage.input_tokens), 0),
        func.coalesce(func.sum(ApiUsage.output_tokens), 0),
        func.max(ApiUsage.timestamp),
    ).one()
    return float(spend_cents or 0.0), int(in_tok or 0), int(out_tok or 0), last_ts


def get_display_totals(db: Session) -> tuple[float, int, int, object, object]:
    """Totals since the last reset (or lifetime, if never reset) — this is what the
    diagnostics page's running counter shows. Returns
    (spend_usd_cents, input_tokens, output_tokens, last_call_timestamp, reset_at)."""
    reset_at = get_last_reset_at(db)
    query = db.query(
        func.coalesce(func.sum(ApiUsage.cost_usd_cents), 0.0),
        func.coalesce(func.sum(ApiUsage.input_tokens), 0),
        func.coalesce(func.sum(ApiUsage.output_tokens), 0),
        func.max(ApiUsage.timestamp),
    )
    if reset_at is not None:
        query = query.filter(ApiUsage.timestamp > reset_at)
    spend_cents, in_tok, out_tok, last_ts = query.one()
    return float(spend_cents or 0.0), int(in_tok or 0), int(out_tok or 0), last_ts, reset_at


def reset_api_usage_display(db: Session) -> ApiUsageReset:
    """Backs the diagnostics "reset spend tracker" button (CLAUDE.md > Security §0b). Inserts
    a new reset marker — never deletes or edits an `api_usage` row, so the underlying call log
    stays a complete, genuinely append-only record regardless of how many times this is
    clicked."""
    marker = ApiUsageReset()
    db.add(marker)
    db.commit()
    db.refresh(marker)
    logger.info("api_usage display reset at %s (underlying log untouched)", marker.reset_at)
    return marker


def log_api_usage(
    db: Session,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    call_type: str,
    context_id: str | None = None,
) -> ApiUsage:
    """Writes one row to `api_usage`. `call_type` is one of 'recipe_url', 'recipe_photo',
    'ingredient_normalise' per CLAUDE.md > Data Model. `context_id` is freetext for
    traceability (e.g. a recipe id) — nullable because a capture call happens before the
    recipe exists yet."""
    cost_cents = calculate_cost_usd_cents(model, input_tokens, output_tokens)
    usage = ApiUsage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd_cents=cost_cents,
        call_type=call_type,
        context_id=context_id,
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)
    logger.info(
        "api_usage logged: model=%s call_type=%s context_id=%s input_tokens=%d "
        "output_tokens=%d cost_usd_cents=%.4f",
        model,
        call_type,
        context_id,
        input_tokens,
        output_tokens,
        cost_cents,
    )
    return usage
