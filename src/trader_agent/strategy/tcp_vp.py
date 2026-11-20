import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from trader_agent.market_data.bars import LABEL as RESOLUTION_LABEL
from trader_agent.market_data.bars import STEP as RESOLUTION_SECONDS
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
    signal_resolution: str
    trend_resolution: str
    exit_on_signal_trend: bool
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


DEFAULT_VERSION = "tcp-vp-2"


def load_params(path: Path | None = None, version: str = DEFAULT_VERSION) -> Params:
    if path is None:
        bundled = resources.files("trader_agent.strategy").joinpath(f"{version}.json")
        text = bundled.read_text("utf-8")
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
        "signal_resolution": str(raw.get("signal_resolution", "15")),
        "trend_resolution": str(raw.get("trend_resolution", "60")),
        "exit_on_signal_trend": bool(raw.get("exit_on_signal_trend", True)),
    }
    for name in DECIMAL_FIELDS:
        values[name] = Decimal(str(raw[name]))
    if values["ema_fast"] >= values["ema_slow"]:
        raise ValueError("ema_fast must be below ema_slow")
    sig_res, trend_res = values["signal_resolution"], values["trend_resolution"]
    if sig_res not in RESOLUTION_SECONDS or trend_res not in RESOLUTION_SECONDS:
        raise ValueError("unknown signal or trend resolution")
    if RESOLUTION_SECONDS[sig_res] >= RESOLUTION_SECONDS[trend_res]:
        raise ValueError("trend_resolution must be slower than signal_resolution")
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
    signal_bars: Sequence[Candle],
    trend_bars: Sequence[Candle],
    in_position: bool,
    state: PullbackState,
    data_ok: bool,
    price_step: Decimal,
) -> Signal | None:
    if not data_ok:
        state.reset()
        return None
    if len(signal_bars) < params.warmup_candles or len(trend_bars) < params.warmup_candles:
        return None
    ts = trend(signal_bars, params.ema_fast, params.ema_slow)
    tt = trend(trend_bars, params.ema_fast, params.ema_slow)
    if ts is None or tt is None:
        return None
    last = signal_bars[-1]
    if in_position:
        state.reset()
        if params.exit_on_signal_trend and ts.down:
            label = RESOLUTION_LABEL[params.signal_resolution]
            return ExitSignal(symbol, last.open_time, f"{label} trend turned down")
        if tt.down:
            label = RESOLUTION_LABEL[params.trend_resolution]
            return ExitSignal(symbol, last.open_time, f"{label} trend turned down")
        return None
    if not (ts.up and tt.up):
        state.reset()
        return None
    if last.close < ts.fast:
        state.low = last.low if state.low is None else min(state.low, last.low)
        if state.since is None:
            state.since = last.open_time
        return None
    if state.low is not None and state.since is not None and last.close > ts.fast:
        low = min(state.low, last.low)
        state.reset()
        a = atr(
            [c.high for c in signal_bars],
            [c.low for c in signal_bars],
            [c.close for c in signal_bars],
            params.atr_period,
        )
        if a is None:
            return None
        buffer = max(params.stop_atr_mult * a, price_step)
        return EntrySignal(symbol, last.open_time, low, a, buffer, low - buffer)
    return None
