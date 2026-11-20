import argparse
import csv
import itertools
import math
import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from trader_agent.backtest.signals import STEP, aggregate, load_candles, replay
from trader_agent.market_data.candles import Candle
from trader_agent.strategy.tcp_vp import load_params

HOLDOUT_START = 1735677000
RESOLUTIONS = ("15", "60")
STOP_MULTS = ("0.25", "1", "2")
SLOW_EXIT_ONLY = (False, True)
WALLEX = ("BTCTMN", "ETHTMN", "USDTTMN")
NOBITEX = ("BTCIRT", "ETHIRT", "USDTIRT")


@dataclass(frozen=True)
class Config:
    resolution: str
    stop_mult: str
    slow_exit_only: bool

    @property
    def name(self) -> str:
        exit_rule = "slow-exit" if self.slow_exit_only else "both-exit"
        return f"{self.resolution}m/stop{self.stop_mult}/{exit_rule}"


def configs() -> list[Config]:
    return [
        Config(r, s, e) for r, s, e in itertools.product(RESOLUTIONS, STOP_MULTS, SLOW_EXIT_ONLY)
    ]


def stats(returns: list[float]) -> dict[str, float]:
    n = len(returns)
    if n == 0:
        return {"n": 0, "win": math.nan, "mean": math.nan, "t": math.nan}
    mean = statistics.fmean(returns)
    sd = statistics.stdev(returns) if n > 1 else math.nan
    t = mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else math.nan
    return {"n": n, "win": sum(r > 0 for r in returns) / n, "mean": mean, "t": t}


def wallex_bars(db: Path, market: str, resolution: str) -> list[Candle]:
    c15 = load_candles(db, market, "15")
    if resolution == "15":
        return c15
    return [c for _, c in aggregate(c15, STEP[resolution])]


def run(config: Config, wallex: Path, nobitex: Path | None) -> dict[str, object]:
    params = replace(load_params(), stop_atr_mult=Decimal(config.stop_mult))
    train: list[float] = []
    hold: list[float] = []
    for market in WALLEX:
        bars = wallex_bars(wallex, market, config.resolution)
        for row in replay(params, bars[0].symbol, bars, config.resolution, config.slow_exit_only):
            target = hold if row.signal_time >= HOLDOUT_START else train
            target.append(float(row.net_return))
    nob: list[float] = []
    if nobitex is not None and config.resolution == "60":
        for market in NOBITEX:
            bars = load_candles(nobitex, market, "60")
            nob += [
                float(row.net_return)
                for row in replay(params, market, bars, "60", config.slow_exit_only)
            ]
    out: dict[str, object] = {"config": config.name}
    for label, values in (("train", train), ("holdout", hold), ("nobitex", nob)):
        for key, value in stats(values).items():
            out[f"{label}_{key}"] = value
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trader-agent-sweep")
    parser.add_argument("--wallex", type=Path, required=True)
    parser.add_argument("--nobitex", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    grid = configs()
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run, grid, [args.wallex] * len(grid), [args.nobitex] * len(grid)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"trials: {len(grid)}")
    for row in rows:
        print(
            f"{row['config']:<26}"
            f" train n={row['train_n']} mean={row['train_mean']:.4f} t={row['train_t']:.2f}"
            f" | hold n={row['holdout_n']} mean={row['holdout_mean']:.4f}"
            f" | nob n={row['nobitex_n']} mean={row['nobitex_mean']:.4f}"
        )


if __name__ == "__main__":
    main()
