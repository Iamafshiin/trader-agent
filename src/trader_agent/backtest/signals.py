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
STEP_15 = 900
STEP_60 = 3600


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


def hour_open(t: int) -> int:
    return t - (t + TEHRAN_UTC_OFFSET) % STEP_60


def to_hourly(c15: Sequence[Candle]) -> list[tuple[int, Candle]]:
    out: list[tuple[int, Candle]] = []
    group: list[Candle] = []
    for c in c15:
        if group and hour_open(c.open_time) != hour_open(group[0].open_time):
            out.append(merge(group))
            group = []
        group.append(c)
    if group:
        out.append(merge(group))
    return out


def merge(group: Sequence[Candle]) -> tuple[int, Candle]:
    start = hour_open(group[0].open_time)
    candle = Candle(
        group[0].symbol,
        "60",
        start,
        group[0].open,
        max(c.high for c in group),
        min(c.low for c in group),
        group[-1].close,
        sum((c.volume for c in group), Decimal(0)),
    )
    return start + STEP_60, candle


def replay(params: Params, symbol: str, c15: Sequence[Candle]) -> Iterator[LabeledSignal]:
    hourly = to_hourly(c15)
    h_closed = 0
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
            c15[i].open_time,
            proceeds,
            reason,
            i - i_in,
            ret,
            int(ret > 0),
        )

    for i, bar in enumerate(c15):
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
        bar_close = bar.open_time + STEP_15
        while h_closed < len(hourly) and hourly[h_closed][0] <= bar_close:
            h_closed += 1
        lo = max(0, i + 1 - WINDOW)
        w15 = c15[lo : i + 1]
        w60 = [c for _, c in hourly[max(0, h_closed - WINDOW) : h_closed]]
        data_ok = (
            i > 0
            and c15[i - 1].open_time == bar.open_time - STEP_15
            and bool(w60)
            and w60[-1].open_time == hour_open(bar_close) - STEP_60
        )
        sig = evaluate(params, symbol, w15, w60, entry is not None, state, data_ok, Decimal(1))
        if isinstance(sig, EntrySignal):
            pending_entry = sig
        elif isinstance(sig, ExitSignal):
            pending_exit = sig


def load_wallex(db: Path, market: str) -> list[Candle]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?immutable=1", uri=True)
    try:
        rows = conn.execute(
            "SELECT open_time, open, high, low, close, volume FROM candles"
            " WHERE symbol = ? AND resolution = '15' ORDER BY open_time",
            (market,),
        ).fetchall()
    finally:
        conn.close()
    symbol = market.removesuffix("TMN") + "IRT"
    return [
        Candle(symbol, "15", t, *(Decimal(repr(v)) for v in (o, h, lo, c, vol)))
        for t, o, h, lo, c, vol in rows
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trader-agent-signals")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markets", nargs="+", default=["BTCTMN", "ETHTMN", "USDTTMN"])
    args = parser.parse_args(argv)
    params = load_params()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer: csv.DictWriter[str] | None = None
        for market in args.markets:
            candles = load_wallex(args.db, market)
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
