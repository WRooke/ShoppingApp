"""Unit tests for app/services/scaling.py — pure arithmetic, no DB, no network.

scaling.py deliberately only multiplies (see CLAUDE.md > Scaling Logic, revised at the
2026-09-06 Phase 4 kickoff): rounding and unit conversion live downstream in
consolidation.py / purchase_units.py, and are tested there.
"""

from __future__ import annotations

import pytest

from app.services import scaling


# --- scaling_factor ------------------------------------------------------------


def test_scaling_factor_basic():
    assert scaling.scaling_factor(4, 6) == 1.5
    assert scaling.scaling_factor(4, 4) == 1.0
    assert scaling.scaling_factor(6, 4) == pytest.approx(2 / 3)


def test_scaling_factor_rejects_non_positive_base():
    with pytest.raises(ValueError):
        scaling.scaling_factor(0, 4)
    with pytest.raises(ValueError):
        scaling.scaling_factor(-2, 4)


# --- scale_quantity: plain multiplication, no rounding ------------------------


def test_scale_quantity_multiplies_exactly_no_rounding():
    r = scaling.scale_quantity(337.0, "g", 1.0)
    assert r.quantity == 337.0 and r.unit == "g" and r.scaled is True

    r = scaling.scale_quantity(500.0, "g", 1.5)
    assert r.quantity == 750.0

    # deliberately "ugly" — scaling must NOT tidy it
    r = scaling.scale_quantity(200.0, "g", 2 / 3)
    assert r.quantity == pytest.approx(133.3333, rel=1e-4)


def test_scale_quantity_preserves_unit_verbatim_including_kg_and_free_text():
    assert scaling.scale_quantity(1.6, "kg", 1.5).unit == "kg"
    assert scaling.scale_quantity(2, "can", 1.5).unit == "can"
    assert scaling.scale_quantity(3, None, 1.5).unit is None


def test_scale_quantity_discrete_not_rounded_here():
    # 3 eggs scaled to half — stays 1.5; round-up happens in consolidation, not here
    r = scaling.scale_quantity(3, None, 0.5)
    assert r.quantity == 1.5


def test_scale_quantity_factor_below_one_and_zero_quantity():
    assert scaling.scale_quantity(0.0, "g", 3.0).quantity == 0.0
    assert scaling.scale_quantity(4, None, 0.25).quantity == 1.0


@pytest.mark.parametrize("unit", ["pinch", "Pinch", "  to taste  ", "TO TASTE", "splash", "dash", "drizzle"])
def test_scale_quantity_no_scale_units_pass_through_untouched(unit):
    r = scaling.scale_quantity(1.0, unit, 5.0)
    assert r.quantity == 1.0
    assert r.unit == unit  # verbatim, not normalised
    assert r.scaled is False


def test_scale_quantity_real_units_report_scaled_true():
    assert scaling.scale_quantity(10, "ml", 2.0).scaled is True
    assert scaling.scale_quantity(2, None, 2.0).scaled is True
