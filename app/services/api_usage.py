"""Cost calculation, spend-cap enforcement, and logging for Claude API calls (see CLAUDE.md >
Data Model > `api_usage`, CLAUDE.md > Diagnostics & Logging — "every external API call ...
log the attempt at INFO, log success at INFO, log failure at ERROR" — and CLAUDE.md >
Security > API Spend Cap, a highest-priority standing rule).

Deliberately separate from `claude_client.py` conceptually — this is where the cost math and
the `api_usage` table live — but `claude_client.py` imports and calls straight into
`enforce_spend_cap()` / `log_api_usage()` before/after every real API call, specifically so the
spend cap cannot be bypassed by a caller forgetting to check it. See CLAUDE.md > Code
Architecture & Maintainability for why `claude_client.py` is otherwise the DB-free one.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.models.diagnostics import ApiUsage

logger = logging.getLogger(__name__)

# USD per 1M tokens. Extend this dict as other models are used — see CLAUDE.md >
# Tech Stack (Haiku 4.5 chosen for recipe extraction: cheapest model, ~$0.005/recipe).
_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}

# Deliberately BELOW the real historical AUD/USD rate (roughly 0.60-0.70 USD per AUD in
# recent years) — see CLAUDE.md > Security > API Spend Cap. Using a low "USD per AUD" figure
# makes the computed USD-cent ceiling *smaller* than the true equivalent of the maintainer's
# AUD cap, so the enforced limit stays stricter than 50c AUD even if the real exchange rate
# drifts. Never raise this to "get a more accurate" cap — the whole point is the pad.
_CONSERVATIVE_USD_PER_AUD = 0.55


class UnknownModelPricingError(Exception):
    """Raised when cost can't be calculated because the model isn't in the pricing table."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"No pricing entry for model {model!r}")


class SpendCapExceededError(Exception):
    """Raised when a call would push (or has already pushed) total Claude API spend past the
    maintainer's hard cap (see CLAUDE.md > Security > API Spend Cap). Never caught and
    silently ignored anywhere — routers translate this straight to a blocking error response,
    per CLAUDE.md > API Conventions."""

    def __init__(self, current_usd_cents: float, projected_usd_cents: float, cap_usd_cents: float) -> None:
        self.current_usd_cents = current_usd_cents
        self.projected_usd_cents = projected_usd_cents
        self.cap_usd_cents = cap_usd_cents
        super().__init__(
            f"Spend cap would be exceeded: current={current_usd_cents:.2f}c "
            f"projected_call={projected_usd_cents:.2f}c cap={cap_usd_cents:.2f}c (all USD)"
        )


def calculate_cost_usd_cents(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cents for one call, given token counts. Raises UnknownModelPricingError for an
    unpriced model rather than silently returning 0 — a wrong-but-plausible spend figure on
    the diagnostics page is worse than a loud failure (see CLAUDE.md > Diagnostics & Logging)."""
    pricing = _PRICING_USD_PER_MTOK.get(model)
    if pricing is None:
        raise UnknownModelPricingError(model)
    dollars = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return dollars * 100


def get_spend_cap_usd_cents() -> float:
    """The maintainer's AUD cap (`.env` > MAX_API_SPEND_AUD_CENTS), converted to a
    conservative USD-cent ceiling. See the `_CONSERVATIVE_USD_PER_AUD` comment above."""
    return settings.max_api_spend_aud_cents * _CONSERVATIVE_USD_PER_AUD


def get_total_spend_usd_cents(db: Session) -> float:
    """Cumulative spend across every api_usage row ever recorded — this is a lifetime total,
    not a per-day/per-session figure, matching the maintainer's "at all times" cap wording."""
    total = db.query(func.coalesce(func.sum(ApiUsage.cost_usd_cents), 0.0)).scalar()
    return float(total or 0.0)


def estimate_worst_case_cost_usd_cents(
    model: str, *, input_char_count: int, image_count: int, max_output_tokens: int
) -> float:
    """A deliberately pessimistic pre-call cost estimate, used to refuse a call *before* it's
    made rather than only noticing the overspend after the fact. Two conservative choices:
      - ~3 characters per input token (real English/HTML text is usually ~4+) — overestimates
        input tokens, so overestimates cost.
      - every image charged at a flat 1600 tokens (a generous worst case for a single photo
        at the resolutions this app handles) rather than trying to compute the real figure.
    Assumes the call always spends the full `max_output_tokens` — the true worst case, since
    actual output is not known until after the (billable) call completes."""
    estimated_input_tokens = (input_char_count // 3) + (image_count * 1600)
    return calculate_cost_usd_cents(model, estimated_input_tokens, max_output_tokens)


def enforce_spend_cap(
    db: Session,
    *,
    model: str,
    input_char_count: int,
    image_count: int,
    max_output_tokens: int,
) -> None:
    """Refuses to proceed if the worst-case cost of the call about to be made would push
    cumulative spend past the maintainer's cap. Must be called before every billable API call
    — see CLAUDE.md > Security > API Spend Cap. Raises SpendCapExceededError; never returns a
    partial/soft warning, because a soft warning is a safeguard someone can learn to ignore."""
    cap = get_spend_cap_usd_cents()
    current = get_total_spend_usd_cents(db)
    projected_call_cost = estimate_worst_case_cost_usd_cents(
        model, input_char_count=input_char_count, image_count=image_count,
        max_output_tokens=max_output_tokens,
    )
    if current + projected_call_cost > cap:
        logger.error(
            "Spend cap would be exceeded: current=%.2fc projected_call=%.2fc cap=%.2fc "
            "(cap is MAX_API_SPEND_AUD_CENTS=%.2f converted conservatively to USD) — "
            "refusing to call the Claude API. Raise MAX_API_SPEND_AUD_CENTS in .env to "
            "proceed; this requires explicit maintainer approval.",
            current, projected_call_cost, cap, settings.max_api_spend_aud_cents,
        )
        raise SpendCapExceededError(current, projected_call_cost, cap)


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
