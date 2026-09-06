"""Unit tests for app/services/api_usage.py — cost calculation and usage logging. No network
involved (see CLAUDE.md > Code Architecture & Maintainability > Tests).

**2026-09-06:** this used to also cover spend-cap enforcement (a hard AU$0.50 lifetime cap).
That cap was removed — see CLAUDE.md > Non-Negotiable Operating Rules and Security §0b — so
those tests are gone too. What remains is purely observational: cost math, logging, and the
display-reset mechanism (`api_usage_resets`) that backs the diagnostics "reset spend tracker"
button.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.diagnostics import ApiUsage, ApiUsageReset
from app.services.api_usage import (
    UnknownModelPricingError,
    calculate_cost_usd_cents,
    get_display_totals,
    get_last_reset_at,
    get_lifetime_totals,
    log_api_usage,
    reset_api_usage_display,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


# --- cost calculation --------------------------------------------------------


def test_calculate_cost_usd_cents_haiku():
    # 1,000,000 input tokens @ $1.00 + 1,000,000 output tokens @ $5.00 = $6.00 = 600 cents
    cost = calculate_cost_usd_cents("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(600.0)


def test_calculate_cost_usd_cents_small_call():
    # A typical single-recipe extraction: ~1500 input, ~400 output tokens.
    cost = calculate_cost_usd_cents("claude-haiku-4-5", 1500, 400)
    expected = (1500 * 1.00 + 400 * 5.00) / 1_000_000 * 100
    assert cost == pytest.approx(expected)


def test_calculate_cost_usd_cents_unknown_model_raises():
    with pytest.raises(UnknownModelPricingError):
        calculate_cost_usd_cents("claude-opus-5", 100, 100)


# --- logging -----------------------------------------------------------------


def test_log_api_usage_writes_row(db):
    usage = log_api_usage(
        db,
        model="claude-haiku-4-5",
        input_tokens=1500,
        output_tokens=400,
        call_type="recipe_url",
        context_id="42",
    )
    assert usage.id is not None
    assert usage.cost_usd_cents == pytest.approx((1500 * 1.00 + 400 * 5.00) / 1_000_000 * 100)

    stored = db.query(ApiUsage).one()
    assert stored.model == "claude-haiku-4-5"
    assert stored.call_type == "recipe_url"
    assert stored.context_id == "42"
    assert stored.input_tokens == 1500
    assert stored.output_tokens == 400


def test_log_api_usage_context_id_optional(db):
    usage = log_api_usage(
        db, model="claude-haiku-4-5", input_tokens=10, output_tokens=10, call_type="recipe_photo"
    )
    assert usage.context_id is None


# --- lifetime + display totals -----------------------------------------------


def test_get_lifetime_totals_empty(db):
    spend, in_tok, out_tok, last_ts = get_lifetime_totals(db)
    assert spend == 0.0
    assert in_tok == 0
    assert out_tok == 0
    assert last_ts is None


def test_get_lifetime_totals_sums_all_rows(db):
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=2000, output_tokens=400, call_type="recipe_photo")
    expected = calculate_cost_usd_cents("claude-haiku-4-5", 1000, 200) + calculate_cost_usd_cents(
        "claude-haiku-4-5", 2000, 400
    )
    spend, in_tok, out_tok, last_ts = get_lifetime_totals(db)
    assert spend == pytest.approx(expected)
    assert in_tok == 3000
    assert out_tok == 600
    assert last_ts is not None


def test_get_display_totals_matches_lifetime_when_never_reset(db):
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    spend, in_tok, out_tok, last_ts, reset_at = get_display_totals(db)
    lifetime_spend, lifetime_in, lifetime_out, lifetime_last = get_lifetime_totals(db)
    assert spend == pytest.approx(lifetime_spend)
    assert in_tok == lifetime_in
    assert out_tok == lifetime_out
    assert last_ts == lifetime_last
    assert reset_at is None


def test_reset_api_usage_display_inserts_marker_and_zeroes_display_totals(db):
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    assert get_last_reset_at(db) is None

    marker = reset_api_usage_display(db)
    assert marker.id is not None
    assert marker.reset_at is not None
    assert db.query(ApiUsageReset).count() == 1

    spend, in_tok, out_tok, last_ts, reset_at = get_display_totals(db)
    assert spend == 0.0
    assert in_tok == 0
    assert out_tok == 0
    assert last_ts is None
    assert reset_at == marker.reset_at


def test_reset_does_not_touch_underlying_api_usage_rows(db):
    """The whole point of the reset marker design (CLAUDE.md > Security §0b): api_usage stays
    a genuine, complete, append-only log no matter how many times the display is reset."""
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    reset_api_usage_display(db)

    assert db.query(ApiUsage).count() == 1
    lifetime_spend, lifetime_in, lifetime_out, _ = get_lifetime_totals(db)
    assert lifetime_in == 1000
    assert lifetime_out == 200
    assert lifetime_spend > 0


def test_display_totals_only_count_calls_after_most_recent_reset(db):
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    reset_api_usage_display(db)
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=500, output_tokens=100, call_type="recipe_url")

    spend, in_tok, out_tok, last_ts, reset_at = get_display_totals(db)
    assert in_tok == 500
    assert out_tok == 100
    assert reset_at is not None

    # Lifetime totals still include both calls.
    lifetime_spend, lifetime_in, lifetime_out, _ = get_lifetime_totals(db)
    assert lifetime_in == 1500
    assert lifetime_out == 300
