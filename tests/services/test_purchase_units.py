"""Unit tests for app/services/purchase_units.py — pure, no DB. Algorithm and
display rules: CLAUDE.md > Scaling Logic > Purchase unit resolution.
"""

from __future__ import annotations

from app.services.purchase_units import PackOption, resolve_packs


def _opt(label, qty):
    return PackOption(label=label, qty=qty)


def test_no_options_returns_none():
    assert resolve_packs(500, []) is None


def test_single_pack_ceils_up():
    r = resolve_packs(750, [_opt("500g pack", 500)])
    assert r.counts == [("500g pack", 2)]
    assert r.total_purchased == 1000
    assert r.overage == 250
    assert r.display_qty == "2 × 500g pack"


def test_single_pack_exact_fit_no_overage():
    r = resolve_packs(1000, [_opt("500g pack", 500)])
    assert r.counts == [("500g pack", 2)]
    assert r.overage == 0
    assert r.show_overage is False


def test_single_pack_overage_shown_only_past_half_a_pack():
    # need 550 -> 2 x 500 = 1000, overage 450 > 250 (half a pack) -> shown
    r = resolve_packs(550, [_opt("500g pack", 500)])
    assert r.overage == 450 and r.show_overage is True
    # need 900 -> 2 x 500 = 1000, overage 100 < 250 -> not shown
    r2 = resolve_packs(900, [_opt("500g pack", 500)])
    assert r2.overage == 100 and r2.show_overage is False


def test_several_packs_prefers_least_overage():
    # need 750, options {500, 1000} -> one 1000 (overage 250) beats two 500 (overage 250,
    # but 2 packs) -> tie on overage, fewer packs wins
    r = resolve_packs(750, [_opt("1kg tub", 1000), _opt("500g tub", 500)])
    assert r.counts == [("1kg tub", 1)]
    assert r.total_purchased == 1000


def test_several_packs_combines_when_that_is_tighter():
    # need 1400, options {500, 1000}: 1000+500 = 1500 (overage 100) beats 2x1000 = 2000
    r = resolve_packs(1400, [_opt("1kg", 1000), _opt("500g", 500)])
    assert sorted(r.counts) == [("1kg", 1), ("500g", 1)]
    assert r.total_purchased == 1500
    assert r.overage == 100


def test_several_packs_eggs_half_dozen_vs_dozen():
    # need 8 eggs: half-dozen (6) short, so a dozen (12), overage 4; 4 < 6 -> not shown
    r = resolve_packs(8, [_opt("dozen", 12), _opt("half dozen", 6)])
    assert r.counts == [("dozen", 1)]
    assert r.overage == 4 and r.show_overage is False


def test_several_packs_two_half_dozen_beats_one_dozen_when_tighter():
    # need 10: 2 x half-dozen (12, overage 2) beats 1 dozen (12, overage 2) -> tie, then
    # fewer packs -> the dozen wins
    r = resolve_packs(10, [_opt("dozen", 12), _opt("half dozen", 6)])
    assert r.counts == [("dozen", 1)]
    # need 7: half-dozen (6) short; 2 x half-dozen (12, overage 5) vs dozen (12, overage 5)
    # -> tie, fewer packs -> dozen
    assert resolve_packs(7, [_opt("dozen", 12), _opt("half dozen", 6)]).counts == [("dozen", 1)]


def test_zero_required_still_buys_smallest_pack():
    r = resolve_packs(0, [_opt("1kg", 1000), _opt("500g", 500)])
    assert r.counts == [("500g", 1)]
    assert r.show_overage is False
