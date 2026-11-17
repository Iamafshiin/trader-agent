from decimal import Decimal

import pytest

from trader_agent.market_data.candles import Candle
from trader_agent.strategy.indicators import atr, ema
from trader_agent.strategy.tcp_vp import (
    EntrySignal,
    ExitSignal,
    PullbackState,
    evaluate,
    load_params,
)
from trader_agent.strategy.volume_profile import build_profile

D = Decimal
PARAMS = load_params()
STEP = D(10)


def candle(i: int, close: float, low: float | None = None, res: str = "15") -> Candle:
    c = D(str(close))
    lo = D(str(low)) if low is not None else c - 1
    return Candle("BTCIRT", res, i * 900, c, c + 1, lo, c, D(1))


def rising(n: int, start: float = 1000.0, step: float = 1.0, res: str = "15") -> list[Candle]:
    return [candle(i, start + i * step, res=res) for i in range(n)]


def test_ema_seeds_with_sma() -> None:
    out = ema([D(1), D(2), D(3), D(4)], 3)
    assert out[:2] == [None, None]
    assert out[2] == D(2)
    assert out[3] == D(3)


def test_atr_wilder() -> None:
    highs = [D(10)] * 4
    lows = [D(8)] * 4
    closes = [D(9)] * 4
    assert atr(highs, lows, closes, 3) == D(2)
    assert atr(highs, lows, closes, 4) is None


def test_params_are_versioned_and_hashed() -> None:
    assert PARAMS.version == "tcp-vp-1"
    assert (PARAMS.ema_fast, PARAMS.ema_slow, PARAMS.warmup_candles) == (20, 50, 250)
    assert PARAMS.stop_atr_mult == D("0.25")
    assert len(PARAMS.config_hash) == 64
    assert load_params().config_hash == PARAMS.config_hash


def test_volume_profile_value_area() -> None:
    trades = [(D(100), D(1)), (D("100.2"), D(5)), (D("100.4"), D(2)), (D("99.8"), D(2))]
    p = build_profile(trades, D(100), D("0.001"), D("0.70"))
    assert p is not None
    assert D("100.2") <= p.poc < D("100.3")
    assert p.val <= D("100.2") < p.vah
    assert p.total_volume == D(10)


def run(c15: list[Candle], c60: list[Candle], state: PullbackState, pos: bool = False) -> object:
    return evaluate(PARAMS, "BTCIRT", c15, c60, pos, state, True, STEP)


def test_no_signal_before_warmup() -> None:
    state = PullbackState()
    assert run(rising(100), rising(300, res="60"), state) is None


def test_pullback_then_reclaim_enters_with_stop_below_low() -> None:
    c60 = rising(300, res="60")
    base = rising(300)
    state = PullbackState()
    last = float(base[-1].close)
    dip = candle(300, last - 15, low=last - 20)
    assert run([*base, dip], c60, state) is None
    assert state.low == D(str(last - 20))
    reclaim = candle(301, last + 5, low=last - 25)
    sig = run([*base, dip, reclaim], c60, state)
    assert isinstance(sig, EntrySignal)
    assert sig.pullback_low == D(str(last - 25))
    assert sig.stop == sig.pullback_low - sig.stop_buffer
    assert sig.stop_buffer >= STEP
    assert state.low is None


def test_reclaim_requires_later_candle() -> None:
    state = PullbackState()
    sig = run(rising(300), rising(300, res="60"), state)
    assert sig is None
    assert state.low is None


def test_hourly_downtrend_blocks_and_resets_pullback() -> None:
    base = rising(300)
    last = float(base[-1].close)
    state = PullbackState()
    run([*base, candle(300, last - 15)], rising(300, res="60"), state)
    assert state.low is not None
    falling_60 = rising(300, start=2000, step=-1, res="60")
    assert run([*base, candle(300, last - 15), candle(301, last + 5)], falling_60, state) is None
    assert state.low is None


def test_stale_data_resets_pullback() -> None:
    state = PullbackState(low=D(1), since=0)
    assert evaluate(PARAMS, "BTCIRT", [], [], False, state, False, STEP) is None
    assert state.low is None


@pytest.mark.parametrize(
    ("c15_step", "c60_step", "reason"),
    [(-1.0, 1.0, "15m trend turned down"), (1.0, -1.0, "1h trend turned down")],
)
def test_exit_when_either_trend_turns_down(c15_step: float, c60_step: float, reason: str) -> None:
    c15 = rising(300, start=2000, step=c15_step)
    c60 = rising(300, start=2000, step=c60_step, res="60")
    sig = run(c15, c60, PullbackState(), pos=True)
    assert isinstance(sig, ExitSignal)
    assert sig.reason == reason


def test_holds_position_while_both_trends_up() -> None:
    assert run(rising(300), rising(300, res="60"), PullbackState(), pos=True) is None
