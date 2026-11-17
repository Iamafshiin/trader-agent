import argparse
import sys
from collections.abc import Sequence

import httpx

from trader_agent.market_data.candles import (
    DEFAULT_RESOLUTIONS,
    DEFAULT_SYMBOLS,
    CandleCollector,
    CandleSourceError,
    RawLog,
)
from trader_agent.settings import SettingsError, load_settings
from trader_agent.storage.candles import CandleStore


def _check_config(_: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    for key, value in settings.summary().items():
        print(f"{key}: {value}")
    return 0


def _collect_candles(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    store = CandleStore(settings.data_path("db") / "candles.sqlite3")
    headers = {"User-Agent": settings.nobitex_user_agent}
    failed = False
    with httpx.Client(base_url=settings.nobitex_base_url, headers=headers, timeout=20) as client:
        collector = CandleCollector(client, store, RawLog(settings.trader_data_dir))
        for symbol in args.symbols.split(","):
            for resolution in args.resolutions.split(","):
                try:
                    r = collector.collect(symbol, resolution, args.days)
                except (httpx.HTTPError, CandleSourceError) as exc:
                    failed = True
                    print(f"{symbol} {resolution}: FAILED {exc}", file=sys.stderr)
                    continue
                print(
                    f"{r.symbol} {r.resolution}: received={r.received} "
                    f"inserted={r.inserted} missing={r.missing}"
                )
    store.close()
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trader-agent",
        description="Autonomous Nobitex spot trading (paper mode)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-config", help="validate settings and print a safe summary")
    check.set_defaults(handler=_check_config)
    collect = sub.add_parser("collect-candles", help="backfill recent Nobitex candles")
    collect.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    collect.add_argument("--resolutions", default=",".join(DEFAULT_RESOLUTIONS))
    collect.add_argument("--days", type=float, default=8.0)
    collect.set_defaults(handler=_collect_candles)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result
