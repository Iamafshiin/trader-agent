import argparse
import csv
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from trader_agent.market_data.candles import Candle
from trader_agent.storage.candles import TEHRAN_UTC_OFFSET
from trader_agent.strategy.tcp_vp import (
    EntrySignal,
    ExitSignal,
    Params,
    PullbackState,
    evaluate,
    load_params,
)

WINDOW = 300
STEP = {"15": 900, "60": 3600, "240": 14400}
SLOW_OF = {"15": "60", "60": "240"}


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


def bucket_open(t: int, step: int) -> int:
    return t - (t + TEHRAN_UTC_OFFSET) % step


def hour_open(t: int) -> int:
    return bucket_open(t, STEP["60"])


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


def to_hourly(c15: Sequence[Candle]) -> list[tuple[int, Candle]]:
    return aggregate(c15, STEP["60"])


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


def replay(
    params: Params,
    symbol: str,
    bars: Sequence[Candle],
    resolution: str = "15",
    slow_exit_only: bool = False,
) -> Iterator[LabeledSignal]:
    step = STEP[resolution]
    slow_step = STEP[SLOW_OF[resolution]]
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
            if slow_exit_only and not sig.reason.startswith("1h"):
                continue
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trader-agent-signals")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markets", nargs="+", default=["BTCTMN", "ETHTMN", "USDTTMN"])
    parser.add_argument("--resolution", choices=sorted(SLOW_OF), default="15")
    args = parser.parse_args(argv)
    params = load_params()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer: csv.DictWriter[str] | None = None
        for market in args.markets:
            candles = load_candles(args.db, market, args.resolution)
            count = 0
            for row in replay(params, candles[0].symbol, candles, args.resolution):
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(asdict(row)))
                    writer.writeheader()
                writer.writerow(asdict(row))
                count += 1
            print(f"{market}: {len(candles)} candles, {count} signals")


if __name__ == "__main__":
    main()
