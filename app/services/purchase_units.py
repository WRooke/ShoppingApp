"""Purchase-unit resolution — pure arithmetic, no DB, no network. One of the three
highest bug-risk modules (CLAUDE.md > Code Architecture & Maintainability), heavily
unit-tested.

Given a required quantity and the pack sizes an ingredient is sold in (all already
normalised by the caller to ONE common unit — g, ml, or a bare count), work out which
whole packs to buy. Algorithm and display rules: CLAUDE.md > Scaling Logic > Purchase
unit resolution.
  * 0 packs  -> None (the caller just shows the required quantity)
  * 1 pack   -> ceil(required / pack) of it
  * several  -> brute-force small combinations (repeats allowed); pick the one that
               meets/exceeds the requirement with the least overage, then the fewest
               packs. The search space is tiny (2-3 packs deep, a handful of sizes).
Overage is reported only when it exceeds ~half of the largest pack in the chosen combo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PackOption:
    label: str
    qty: float  # in the caller's common unit


@dataclass(frozen=True)
class PackResolution:
    display_qty: str  # "2 × 500g pack"  /  "1 × 1kg tub + 1 × 500g tub"
    total_purchased: float  # in the common unit
    overage: float  # total_purchased - required, >= 0
    show_overage: bool  # overage > 0.5 * largest chosen pack
    counts: list[tuple[str, int]] = field(default_factory=list)  # (label, n>0)


def _format(counts: list[tuple[str, int]]) -> str:
    return " + ".join(f"{n} × {label}" for label, n in counts if n > 0)


def resolve_packs(required: float, options: list[PackOption]) -> PackResolution | None:
    """`options` must all be in the same unit as `required`. Returns None for an empty
    option list."""
    usable = [o for o in options if o.qty > 0]
    if not usable:
        return None
    if required <= 0:
        # Nothing needed, but there IS a pack size — buy the smallest single pack.
        smallest = min(usable, key=lambda o: o.qty)
        return PackResolution(
            display_qty=_format([(smallest.label, 1)]),
            total_purchased=smallest.qty,
            overage=smallest.qty,
            show_overage=False,
            counts=[(smallest.label, 1)],
        )

    if len(usable) == 1:
        opt = usable[0]
        n = max(1, math.ceil(required / opt.qty))
        total = n * opt.qty
        overage = total - required
        return PackResolution(
            display_qty=_format([(opt.label, n)]),
            total_purchased=total,
            overage=overage,
            show_overage=overage > 0.5 * opt.qty,
            counts=[(opt.label, n)],
        )

    # Several pack sizes — brute force over small combinations.
    usable = sorted(usable, key=lambda o: o.qty, reverse=True)  # try big packs first
    smallest_qty = min(o.qty for o in usable)
    max_per_pack = math.ceil(required / smallest_qty) + 1

    best: tuple[float, int, tuple[int, ...]] | None = None  # (overage, pack_count, counts)

    def recurse(idx: int, remaining: float, chosen: list[int]) -> None:
        # DFS over "how many of pack `idx`" (0..cap). When `remaining` <= 0 the combo covers
        # the requirement — score it (overage, then pack count) and keep the best. `cap`
        # keeps the branching tiny; the pack list is a handful of sizes, 2-3 deep.
        nonlocal best
        if remaining <= 0:
            total = sum(c * usable[i].qty for i, c in enumerate(chosen))
            overage = total - required
            pack_count = sum(chosen)
            key = (overage, pack_count, tuple(chosen))
            if best is None or key < best:
                best = key
            return
        if idx >= len(usable):
            return
        # cap this pack's count so the search stays tiny
        cap = min(max_per_pack, math.ceil(remaining / usable[idx].qty) + 1)
        for n in range(cap, -1, -1):
            chosen.append(n)
            recurse(idx + 1, remaining - n * usable[idx].qty, chosen)
            chosen.pop()

    recurse(0, required, [])
    if best is None:  # shouldn't happen — one big pack always covers it
        opt = usable[0]
        n = math.ceil(required / opt.qty)
        best = (n * opt.qty - required, n, tuple([n] + [0] * (len(usable) - 1)))

    overage, pack_count, counts_tuple = best
    counts = [(usable[i].label, n) for i, n in enumerate(counts_tuple) if n > 0]
    total = required + overage
    largest_chosen = max(usable[i].qty for i, n in enumerate(counts_tuple) if n > 0)
    return PackResolution(
        display_qty=_format(counts),
        total_purchased=total,
        overage=overage,
        show_overage=overage > 0.5 * largest_chosen,
        counts=counts,
    )
