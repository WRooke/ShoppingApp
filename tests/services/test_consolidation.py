"""Unit tests for app/services/consolidation.py — pure, no DB. Every rounding /
unit rule from the 2026-09-06 grilling is exercised here (CLAUDE.md > Scaling Logic
> Rounding & unit rules).
"""

from __future__ import annotations

from app.services.consolidation import IngredientLine, consolidate


def L(name, qty, unit=None, is_no_scale=False):
    return IngredientLine(name=name, quantity=qty, unit=unit, is_no_scale=is_no_scale)


def one(lines):
    result = consolidate(lines)
    assert len(result) == 1, result
    return result[0]


# --- summing + ceil-to-clean-step (never rounds down) -----------------------


def test_mass_sums_and_ceils_up_nearest_25_at_or_above_100():
    item = one([L("passata", 200, "g"), L("passata", 140, "g")])  # 340
    assert item.unit == "g" and item.quantity == 350  # ceil to 25


def test_mass_below_100_ceils_to_nearest_5():
    item = one([L("tomato paste", 32, "g"), L("tomato paste", 20, "g")])  # 52
    assert item.quantity == 55 and item.unit == "g"


def test_mass_promoted_to_kg_when_at_least_1000():
    item = one([L("flour", 600, "g"), L("flour", 450, "g")])  # 1050 -> ceil 25 -> 1050
    assert item.unit == "kg" and item.quantity == 1.05


def test_kg_and_g_merge():
    item = one([L("chicken", 1.2, "kg"), L("chicken", 300, "g")])  # 1500
    assert item.unit == "kg" and item.quantity == 1.5


# --- australian volume conversions merge ---------------------------------


def test_tbsp_is_20ml_and_merges_with_ml():
    # 2 tbsp (40 ml) + 100 ml = 140 -> ceil 25 -> 150
    item = one([L("soy sauce", 2, "tbsp"), L("soy sauce", 100, "ml")])
    assert item.unit == "ml" and item.quantity == 150


def test_tsp_is_5ml():
    item = one([L("vanilla", 3, "tsp")])  # 15 ml -> ceil 5 -> 15
    assert item.unit == "ml" and item.quantity == 15


def test_litre_promotion():
    item = one([L("stock", 400, "ml"), L("stock", 0.8, "L")])  # 1200 -> ceil 25 -> 1200
    assert item.unit == "L" and item.quantity == 1.2


def test_pure_cup_ingredient_shown_back_in_cups_not_clean_rounded():
    # 0.5 cup + 0.25 cup = 0.75 cup (187.5 ml) -> shown as 0.75 cup, NOT ceil-to-5 ml
    item = one([L("cream", 0.5, "cup"), L("cream", 0.25, "cup")])
    assert item.unit == "cup" and item.quantity == 0.75


def test_cup_mixed_with_ml_uses_ml_rule():
    # 1 cup (250) + 30 ml = 280 -> ceil 25 -> 300 ml
    item = one([L("milk", 1, "cup"), L("milk", 30, "ml")])
    assert item.unit == "ml" and item.quantity == 300


# --- discrete / count / free-text -------------------------------------


def test_count_sums_and_ceils_to_whole_even_scaling_down():
    item = one([L("eggs", 1.5, None), L("eggs", 1.0, None)])  # 2.5 -> 3
    assert item.unit is None and item.quantity == 3


def test_free_text_unit_treated_as_discrete_keeps_label():
    item = one([L("tinned tomatoes", 1, "can"), L("tinned tomatoes", 1.5, "can")])  # 2.5 -> 3
    assert item.unit == "can" and item.quantity == 3


# --- irreconcilable: mass + volume ---------------------------------------


def test_mass_plus_volume_flagged_not_merged():
    item = one([L("cream", 100, "g"), L("cream", 200, "ml")])
    assert item.needs_review is True
    assert item.quantity is None and item.unit is None
    assert sorted(item.review_parts) == ["100 g", "200 ml"]


def test_count_plus_mass_flagged():
    item = one([L("onion", 2, None), L("onion", 200, "g")])
    assert item.needs_review is True
    assert set(item.review_parts) == {"2", "200 g"}


# --- to taste ----------------------------------------------------------


def test_pure_to_taste_item_has_no_number():
    item = one([L("salt", 1, "pinch", is_no_scale=True)])
    assert item.is_no_scale is True
    assert item.quantity is None and item.unit is None


def test_real_quantity_plus_to_taste_keeps_quantity_and_flags_also():
    item = one([L("pepper", 2, "g"), L("pepper", 1, "to taste", is_no_scale=True)])
    assert item.quantity == 5 and item.unit == "g"  # 2 -> ceil 5
    assert item.also_to_taste is True


# --- name grouping ----------------------------------------------------------
#
# Phase 3.9 M4: consolidate() is PURE — no substitution logic. The effective (post-swap)
# name is resolved by the caller (sessions.consolidate_session), so here two lines that
# already carry the same name just merge onto one line.


def test_same_effective_name_merges_into_one_line():
    result = consolidate([L("regular feta", 100, "g"), L("regular feta", 150, "g")])
    assert len(result) == 1
    assert result[0].name == "regular feta" and result[0].quantity == 250


def test_names_normalised_and_sorted():
    result = consolidate([L("  Beef  Mince ", 500, "g"), L("apple", 2, None)])
    assert [i.name for i in result] == ["apple", "beef mince"]
