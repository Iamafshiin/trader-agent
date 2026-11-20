import argparse
import csv
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from trader_agent.market_data.bars import STEP, aggregate, bucket_open
from trader_agent.market_data.candles import Candle
from trader_agent.strategy.tcp_vp import (
    DEFAULT_VERSION,
    EntrySignal,
    ExitSignal,
    Params,
    PullbackState,
    evaluate,
    load_params,
)

WINDOW = 300


@dataclass(frozen=True)
class LabeledSignal:
    symbol: str
    signal_time: int
    entry_time: int
    entry_price: Decimal
    stop: Decimal
    atr: Decimal
    exit_time: int
    exit_price: Decimal
    exit_reason: str
    bars_held: int
    net_return: Decimal
    win: int


def replay(params: Params, symbol: str, bars: Sequence[Candle]) -> Iterator[LabeledSignal]:
    step = STEP[params.signal_resolution]
    slow_step = STEP[params.trend_resolution]
    slow = aggregate(bars, slow_step)
    s_closed = 0
    state = PullbackState()
    fee = params.taker_fee
    pending_entry: EntrySignal | None = None
    pending_exit: ExitSignal | None = None
    entry: tuple[EntrySignal, int, Decimal, int] | None = None

    def close(i: int, price: Decimal, reason: str) -> LabeledSignal:
        assert entry is not None
        sig, t_in, cost, i_in = entry
        proceeds = price * (1 - fee)
        ret = proceeds / cost - 1
        return LabeledSignal(
            symbol,
            sig.candle_time,
            t_in,
            cost,
            sig.stop,
            sig.atr,
            bars[i].open_time,
            proceeds,
            reason,
            i - i_in,
            ret,
            int(ret > 0),
        )

    for i, bar in enumerate(bars):
        if pending_entry is not None:
            if pending_entry.stop < bar.open:
                cost = bar.open * (1 + params.slippage_normal) * (1 + fee)
                entry = (pending_entry, bar.open_time, cost, i)
            pending_entry = None
        if pending_exit is not None and entry is not None:
            yield close(i, bar.open * (1 - params.slippage_normal), pending_exit.reason)
            entry = None
        pending_exit = None
        if entry is not None and bar.low <= entry[0].stop:
            price = min(bar.open, entry[0].stop) * (1 - params.slippage_stop)
            yield close(i, price, "protective stop")
            entry = None
        bar_close = bar.open_time + step
        while s_closed < len(slow) and slow[s_closed][0] <= bar_close:
            s_closed += 1
        w_fast = bars[max(0, i + 1 - WINDOW) : i + 1]
        w_slow = [c for _, c in slow[max(0, s_closed - WINDOW) : s_closed]]
        data_ok = (
            i > 0
            and bars[i - 1].open_time == bar.open_time - step
            and bool(w_slow)
            and w_slow[-1].open_time == bucket_open(bar_close, slow_step) - slow_step
        )
        sig = evaluate(
            params, symbol, w_fast, w_slow, entry is not None, state, data_ok, Decimal(1)
        )
        if isinstance(sig, EntrySignal):
            pending_entry = sig
        elif isinstance(sig, ExitSignal):
            pending_exit = sig


def load_candles(db: Path, market: str, resolution: str) -> list[Candle]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?immutable=1", uri=True)
    try:
        rows = conn.execute(
            "SELECT open_time, open, high, low, close, volume FROM candles"
            " WHERE symbol = ? AND resolution = ? ORDER BY open_time",
            (market, resolution),
        ).fetchall()
    finally:
        conn.close()
    symbol = market.removesuffix("TMN") + "IRT" if market.endswith("TMN") else market
    return [
        Candle(symbol, resolution, t, *(Decimal(str(v)) for v in (o, h, lo, c, vol)))
        for t, o, h, lo, c, vol in rows
    ]


def signal_bars(db: Path, market: str, source: str, params: Params) -> list[Candle]:
    bars = load_candles(db, market, source)
    if source == params.signal_resolution:
        return bars
    return [c for _, c in aggregate(bars, STEP[params.signal_resolution])]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trader-agent-signals")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markets", nargs="+", default=["BTCTMN", "ETHTMN", "USDTTMN"])
    parser.add_argument("--source-resolution", choices=["15", "60"], default="15")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    args = parser.parse_args(argv)
    params = load_params(version=args.version)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer: csv.DictWriter[str] | None = None
        for market in args.markets:
            candles = signal_bars(args.db, market, args.source_resolution, params)
            count = 0
            for row in replay(params, candles[0].symbol, candles):
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(asdict(row)))
                    writer.writeheader()
                writer.writerow(asdict(row))
                count += 1
            print(f"{market}: {len(candles)} candles, {count} signals")


if __name__ == "__main__":
    main()
