from collections.abc import Sequence
from decimal import Decimal


def ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = Decimal(2) / Decimal(period + 1)
    current = sum(values[:period], Decimal(0)) / Decimal(period)
    out[period - 1] = current
    for i in range(period, len(values)):
        current = (values[i] - current) * k + current
        out[i] = current
    return out


def atr(
    highs: Sequence[Decimal], lows: Sequence[Decimal], closes: Sequence[Decimal], period: int
) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    current = sum(ranges[:period], Decimal(0)) / Decimal(period)
    for tr in ranges[period:]:
        current = (current * (period - 1) + tr) / Decimal(period)
    return current
