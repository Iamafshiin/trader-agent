from decimal import Decimal

from trader_agent.backtest.signals import STEP, aggregate, hour_open, replay, to_hourly
from trader_agent.market_data.candles import Candle
from trader_agent.storage.candles import TEHRAN_UTC_OFFSET
from trader_agent.strategy.tcp_vp import load_params

D = Decimal
PARAMS = load_params()
BASE = 1800


def bar(i: int, o: float, h: float, lo: float, c: float) -> Candle:
    return Candle("BTCIRT", "15", BASE + i * 900, D(str(o)), D(str(h)), D(str(lo)), D(str(c)), D(1))


def flat(i: int, price: float) -> Candle:
    return bar(i, price, price + 1, price - 1, price)


def uptrend(n: int) -> list[Candle]:
    return [flat(i, 1000 + i) for i in range(n)]


def test_hourly_bars_align_to_tehran_hours() -> None:
    hours = to_hourly(uptrend(8))
    assert [close for close, _ in hours] == [BASE + 3600, BASE + 7200]
    assert all(hour_open(c.open_time) == c.open_time for _, c in hours)
    first = hours[0][1]
    assert (first.open, first.close, first.high, first.low) == (D(1000), D(1003), D(1004), D(999))


def test_four_hour_bars_align_to_tehran_midnight() -> None:
    hours = [c for _, c in to_hourly(uptrend(40))]
    blocks = aggregate(hours, STEP["240"])
    assert [(c.open_time + TEHRAN_UTC_OFFSET) % 14400 for _, c in blocks] == [0, 0, 0]
    assert blocks[0][1].open == D(1000)


def test_stopped_trade_loses_after_costs() -> None:
    candles = uptrend(1100)
    n = len(candles)
    top = 1000 + n
    candles += [flat(n + k, top - 15) for k in range(3)]
    candles.append(flat(n + 3, top + 5))
    candles.append(flat(n + 4, top + 6))
    candles.append(bar(n + 5, top + 6, top + 6, top - 200, top - 190))
    rows = list(replay(PARAMS, "BTCIRT", candles))
    assert len(rows) == 1
    row = rows[0]
    assert row.signal_time == candles[n + 3].open_time
    assert row.entry_time == candles[n + 4].open_time
    assert row.exit_reason == "protective stop"
    assert row.exit_time == candles[n + 5].open_time
    assert row.win == 0
    assert row.net_return < 0


def test_gap_blocks_signals() -> None:
    candles = uptrend(1100)
    n = len(candles)
    top = 1000 + n
    candles += [flat(n + k, top - 15) for k in range(3)]
    candles.append(flat(n + 4, top + 5))
    assert list(replay(PARAMS, "BTCIRT", candles)) == []
