from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal


@dataclass(frozen=True)
class Profile:
    poc: Decimal
    vah: Decimal
    val: Decimal
    total_volume: Decimal


def build_profile(
    trades: Iterable[tuple[Decimal, Decimal]],
    last_price: Decimal,
    row_fraction: Decimal,
    value_area_share: Decimal,
) -> Profile | None:
    row = last_price * row_fraction
    if row <= 0:
        return None
    rows: dict[int, Decimal] = {}
    for price, volume in trades:
        idx = int((price / row).to_integral_value(rounding=ROUND_FLOOR))
        rows[idx] = rows.get(idx, Decimal(0)) + volume
    total = sum(rows.values(), Decimal(0))
    if total <= 0:
        return None
    poc_idx = min(rows, key=lambda i: (-rows[i], i))
    lo = hi = poc_idx
    covered = rows[poc_idx]
    target = total * value_area_share
    lowest, highest = min(rows), max(rows)
    while covered < target and (lo > lowest or hi < highest):
        up = rows.get(hi + 1, Decimal(0)) if hi < highest else Decimal(-1)
        down = rows.get(lo - 1, Decimal(0)) if lo > lowest else Decimal(-1)
        if up >= down:
            hi += 1
            covered += max(up, Decimal(0))
        else:
            lo -= 1
            covered += max(down, Decimal(0))
    return Profile(
        poc=(Decimal(poc_idx) + Decimal("0.5")) * row,
        vah=Decimal(hi + 1) * row,
        val=Decimal(lo) * row,
        total_volume=total,
    )
