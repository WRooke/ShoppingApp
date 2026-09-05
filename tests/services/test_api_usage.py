"""Unit tests for app/services/api_usage.py — cost calculation, spend-cap enforcement, and
logging. No network involved (see CLAUDE.md > Code Architecture & Maintainability > Tests).

The spend cap tests are the highest-priority coverage in this suite — see CLAUDE.md >
Security > API Spend Cap, a standing rule that takes precedence over every other design
concern in this app.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.diagnostics import ApiUsage
from app.services import api_usage
from app.services.api_usage import (
    SpendCapExceededError,
    UnknownModelPricingError,
    calculate_cost_usd_cents,
    enforce_spend_cap,
    estimate_worst_case_cost_usd_cents,
    get_spend_cap_usd_cents,
    get_total_spend_usd_cents,
    log_api_usage,
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


@pytest.fixture()
def cap_50_aud_cents(monkeypatch):
    """Pins the maintainer's cap to the documented default (50 AUD cents) regardless of what
    the real .env under test happens to set, so these tests don't depend on environment."""
    monkeypatch.setattr(api_usage.settings, "max_api_spend_aud_cents", 50.0)


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


# --- spend cap -----------------------------------------------------------


def test_get_total_spend_usd_cents_empty(db):
    assert get_total_spend_usd_cents(db) == 0.0


def test_get_total_spend_usd_cents_sums_all_rows(db):
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, call_type="recipe_url")
    log_api_usage(db, model="claude-haiku-4-5", input_tokens=2000, output_tokens=400, call_type="recipe_photo")
    expected = calculate_cost_usd_cents("claude-haiku-4-5", 1000, 200) + calculate_cost_usd_cents(
        "claude-haiku-4-5", 2000, 400
    )
    assert get_total_spend_usd_cents(db) == pytest.approx(expected)


def test_get_spend_cap_usd_cents_uses_conservative_conversion(cap_50_aud_cents):
    # 50 AUD cents * 0.55 (deliberately-low USD/AUD) = 27.5 USD cents.
    assert get_spend_cap_usd_cents() == pytest.approx(27.5)


def test_estimate_worst_case_cost_is_pessimistic():
    # A short prompt should still project a real (nonzero) cost because max_output_tokens
    # dominates the worst case — the whole point of a *worst-case* estimate.
    estimate = estimate_worst_case_cost_usd_cents(
        "claude-haiku-4-5", input_char_count=100, image_count=0, max_output_tokens=4096
    )
    assert estimate > 0
    # Must be at least the cost of max_output_tokens alone.
    floor = calculate_cost_usd_cents("claude-haiku-4-5", 0, 4096)
    assert estimate >= floor


def test_estimate_worst_case_cost_accounts_for_images():
    without_image = estimate_worst_case_cost_usd_cents(
        "claude-haiku-4-5", input_char_count=100, image_count=0, max_output_tokens=4096
    )
    with_image = estimate_worst_case_cost_usd_cents(
        "claude-haiku-4-5", input_char_count=100, image_count=1, max_output_tokens=4096
    )
    assert with_image > without_image


def test_enforce_spend_cap_allows_first_call(db, cap_50_aud_cents):
    # A single Haiku call (well within the ~27.5 USD-cent cap) should not raise.
    enforce_spend_cap(
        db, model="claude-haiku-4-5", input_char_count=2000, image_count=0, max_output_tokens=4096
    )


def test_enforce_spend_cap_blocks_once_cap_reached(db, cap_50_aud_cents):
    # Manually record spend right at the cap.
    cap = get_spend_cap_usd_cents()
    db.add(
        ApiUsage(
            model="claude-haiku-4-5",
            input_tokens=0,
            output_tokens=0,
            cost_usd_cents=cap,
            call_type="recipe_url",
        )
    )
    db.commit()

    with pytest.raises(SpendCapExceededError) as exc_info:
        enforce_spend_cap(
            db, model="claude-haiku-4-5", input_char_count=100, image_count=0, max_output_tokens=1
        )
    assert exc_info.value.cap_usd_cents == pytest.approx(cap)


def test_enforce_spend_cap_blocks_when_projected_call_would_exceed(db, cap_50_aud_cents):
    # Nothing spent yet, but request a call whose worst-case cost alone exceeds the ~27.5
    # USD-cent cap: ~800,000 chars / 3 chars-per-token ≈ 266k input tokens ≈ 26.7c, plus a
    # full 4096-token worst-case output (~2c) — comfortably over.
    with pytest.raises(SpendCapExceededError):
        enforce_spend_cap(
            db,
            model="claude-haiku-4-5",
            input_char_count=800_000,
            image_count=0,
            max_output_tokens=4096,
        )


def test_enforce_spend_cap_error_message_never_raises_on_construction(db, cap_50_aud_cents):
    db.add(
        ApiUsage(
            model="claude-haiku-4-5",
            input_tokens=0,
            output_tokens=0,
            cost_usd_cents=get_spend_cap_usd_cents(),
            call_type="recipe_url",
        )
    )
    db.commit()
    try:
        enforce_spend_cap(
            db, model="claude-haiku-4-5", input_char_count=10, image_count=0, max_output_tokens=1
        )
    except SpendCapExceededError as exc:
        # Just confirm the exception is informative, not a bare/blank message.
        assert "cap" in str(exc)
        assert exc.current_usd_cents >= 0
