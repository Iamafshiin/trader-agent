import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
import websockets

from trader_agent.market_data.candles import (
    DEFAULT_RESOLUTIONS,
    DEFAULT_SYMBOLS,
    CandleCollector,
    CandleSourceError,
    RawLog,
)
from trader_agent.market_data.streams import (
    WS_URL,
    RawWriter,
    StreamRecorder,
    StreamState,
    channels_for,
    completeness_report,
    make_seeder,
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


def _collect_streams(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    headers = {"User-Agent": settings.nobitex_user_agent}
    root = settings.trader_data_dir

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url=settings.nobitex_base_url, headers=headers, timeout=20
        ) as client:
            writer = RawWriter(root)
            recorder = StreamRecorder(
                lambda: websockets.connect(WS_URL, user_agent_header=headers["User-Agent"]),
                channels_for(args.symbols.split(",")),
                writer,
                StreamState(),
                seed=make_seeder(client),
                state_path=settings.data_path("state") / "streams.json",
            )
            task = asyncio.current_task()
            if task is not None and hasattr(signal, "SIGTERM") and sys.platform != "win32":
                asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
            try:
                await recorder.run_forever()
            except asyncio.CancelledError:
                pass
            finally:
                writer.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


def _stream_report(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    day = args.day or (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    reports = completeness_report(settings.trader_data_dir, day)
    out_dir = settings.data_path("reports", "completeness")
    (out_dir / f"{day}.json").write_text(
        json.dumps([asdict(r) for r in reports], indent=2), encoding="utf-8"
    )
    for r in reports:
        print(
            f"{r.channel}: messages={r.messages} gaps={r.offset_gaps} "
            f"lost={r.lost} max_silence_s={r.max_silence_s:.0f}"
        )
    return 0 if reports else 1


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
    streams = sub.add_parser("collect-streams", help="record Nobitex WebSocket streams")
    streams.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    streams.set_defaults(handler=_collect_streams)
    report = sub.add_parser("stream-report", help="daily completeness report (UTC day)")
    report.add_argument("--day", help="YYYY-MM-DD, default yesterday")
    report.set_defaults(handler=_stream_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result
