from collections.abc import Sequence
from decimal import Decimal

from trader_agent.market_data.candles import Candle
from trader_agent.storage.candles import TEHRAN_UTC_OFFSET

STEP = {"15": 900, "60": 3600, "240": 14400}
LABEL = {"15": "15m", "60": "1h", "240": "4h"}


def bucket_open(t: int, step: int) -> int:
    return t - (t + TEHRAN_UTC_OFFSET) % step


def aggregate(bars: Sequence[Candle], step: int) -> list[tuple[int, Candle]]:
    out: list[tuple[int, Candle]] = []
    group: list[Candle] = []
    for c in bars:
        if group and bucket_open(c.open_time, step) != bucket_open(group[0].open_time, step):
            out.append(merge(group, step))
            group = []
        group.append(c)
    if group:
        out.append(merge(group, step))
    return out


def merge(group: Sequence[Candle], step: int) -> tuple[int, Candle]:
    start = bucket_open(group[0].open_time, step)
    candle = Candle(
        group[0].symbol,
        str(step // 60),
        start,
        group[0].open,
        max(c.high for c in group),
        min(c.low for c in group),
        group[-1].close,
        sum((c.volume for c in group), Decimal(0)),
    )
    return start + step, candle


def closed_bars(bars: Sequence[Candle], step: int, now_s: int) -> list[Candle]:
    return [c for close, c in aggregate(bars, step) if close <= now_s]
