import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from trader_agent.market_data.candles import Candle
from trader_agent.strategy.indicators import atr, ema


@dataclass(frozen=True)
class Params:
    version: str
    symbols: tuple[str, ...]
    ema_fast: int
    ema_slow: int
    warmup_candles: int
    atr_period: int
    stop_atr_mult: Decimal
    position_fraction: Decimal
    max_deployed_fraction: Decimal
    starting_balance_rls: Decimal
    value_area_share: Decimal
    profile_row_fraction: Decimal
    maker_fee: Decimal
    taker_fee: Decimal
    slippage_normal: Decimal
    slippage_stop: Decimal
    signal_expiry_s: int
    config_hash: str
    raw: dict[str, Any]


DECIMAL_FIELDS = (
    "stop_atr_mult",
    "position_fraction",
    "max_deployed_fraction",
    "starting_balance_rls",
    "value_area_share",
    "profile_row_fraction",
    "maker_fee",
    "taker_fee",
    "slippage_normal",
    "slippage_stop",
)


def load_params(path: Path | None = None) -> Params:
    if path is None:
        text = resources.files("trader_agent.strategy").joinpath("tcp-vp-1.json").read_text("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    values: dict[str, Any] = {
        "version": raw["version"],
        "symbols": tuple(raw["symbols"]),
        "ema_fast": int(raw["ema_fast"]),
        "ema_slow": int(raw["ema_slow"]),
        "warmup_candles": int(raw["warmup_candles"]),
        "atr_period": int(raw["atr_period"]),
        "signal_expiry_s": int(raw["signal_expiry_s"]),
    }
    for name in DECIMAL_FIELDS:
        values[name] = Decimal(str(raw[name]))
    if values["ema_fast"] >= values["ema_slow"]:
        raise ValueError("ema_fast must be below ema_slow")
    return Params(
        **values,
        config_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        raw=raw,
    )


@dataclass
class PullbackState:
    low: Decimal | None = None
    since: int | None = None

    def reset(self) -> None:
        self.low = None
        self.since = None


@dataclass(frozen=True)
class Trend:
    fast: Decimal
    slow: Decimal

    @property
    def up(self) -> bool:
        return self.fast > self.slow

    @property
    def down(self) -> bool:
        return self.fast < self.slow


@dataclass(frozen=True)
class EntrySignal:
    symbol: str
    candle_time: int
    pullback_low: Decimal
    atr: Decimal
    stop_buffer: Decimal
    stop: Decimal


@dataclass(frozen=True)
class ExitSignal:
    symbol: str
    candle_time: int
    reason: str


Signal = EntrySignal | ExitSignal


def trend(candles: Sequence[Candle], fast: int, slow: int) -> Trend | None:
    closes = [c.close for c in candles]
    f, s = ema(closes, fast)[-1], ema(closes, slow)[-1]
    if f is None or s is None:
        return None
    return Trend(f, s)


def evaluate(
    params: Params,
    symbol: str,
    c15: Sequence[Candle],
    c60: Sequence[Candle],
    in_position: bool,
    state: PullbackState,
    data_ok: bool,
    price_step: Decimal,
) -> Signal | None:
    if not data_ok:
        state.reset()
        return None
    if len(c15) < params.warmup_candles or len(c60) < params.warmup_candles:
        return None
    t15 = trend(c15, params.ema_fast, params.ema_slow)
    t60 = trend(c60, params.ema_fast, params.ema_slow)
    if t15 is None or t60 is None:
        return None
    last = c15[-1]
    if in_position:
        state.reset()
        if t15.down:
            return ExitSignal(symbol, last.open_time, "15m trend turned down")
        if t60.down:
            return ExitSignal(symbol, last.open_time, "1h trend turned down")
        return None
    if not (t15.up and t60.up):
        state.reset()
        return None
    if last.close < t15.fast:
        state.low = last.low if state.low is None else min(state.low, last.low)
        if state.since is None:
            state.since = last.open_time
        return None
    if state.low is not None and state.since is not None and last.close > t15.fast:
        low = min(state.low, last.low)
        state.reset()
        a = atr(
            [c.high for c in c15],
            [c.low for c in c15],
            [c.close for c in c15],
            params.atr_period,
        )
        if a is None:
            return None
        buffer = max(params.stop_atr_mult * a, price_step)
        return EntrySignal(symbol, last.open_time, low, a, buffer, low - buffer)
    return None
