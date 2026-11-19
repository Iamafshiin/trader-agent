import argparse
import asyncio
import contextlib
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from trader_agent.ops.bale import Alerter, find_chat_ids
from trader_agent.ops.summary import build_report, gather, load_state, save_state
from trader_agent.paper.engine import PaperStore
from trader_agent.paper.service import PaperService
from trader_agent.risk.gate import RiskState
from trader_agent.settings import Settings, SettingsError, load_settings
from trader_agent.storage.candles import CandleStore
from trader_agent.strategy.tcp_vp import load_params


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


def _settings_or_exit() -> Settings | None:
    try:
        return load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return None


def _run_paper(args: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    service = PaperService(settings, load_params(), args.run_id)

    async def run() -> None:
        task = asyncio.current_task()
        if task is not None and sys.platform != "win32":
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await service.run()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


def _paper_status(args: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    db = settings.data_path("db") / "paper.sqlite3"
    store = PaperStore(db)
    run = store.conn.execute(
        "SELECT version, config_hash, started_ms FROM runs WHERE run_id=?", (args.run_id,)
    ).fetchone()
    if run is None:
        print(f"no run '{args.run_id}'")
        return 1
    account = store.load_account(args.run_id)
    last_eq = store.conn.execute(
        "SELECT at_ms, equity FROM equity WHERE run_id=? ORDER BY at_ms DESC LIMIT 1",
        (args.run_id,),
    ).fetchone()
    trades = store.conn.execute(
        "SELECT COUNT(*) FROM trades WHERE run_id=?", (args.run_id,)
    ).fetchone()[0]
    risk = RiskState(db, args.run_id)
    started = datetime.fromtimestamp(run[2] / 1000, UTC).isoformat(timespec="minutes")
    print(f"run: {args.run_id} ({run[0]}, config {run[1][:12]}, started {started})")
    if last_eq:
        print(f"equity: {Decimal(last_eq[1]):,.0f} rial")
    if account:
        print(f"cash: {account.cash:,.0f} rial")
        for asset, qty in account.holdings.items():
            if qty:
                print(f"holding {asset}: {qty}")
        for sym, stop in account.stops.items():
            print(f"stop {sym}: {stop.amount} @ {stop.stop_price}")
    print(f"trades: {trades}")
    print(f"risk halt: {risk.halt_reason or 'none'}")
    print(f"kill switch: {'ENGAGED' if (settings.trader_data_dir / 'HALT').exists() else 'off'}")
    return 0


def _halt(args: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    flag = settings.trader_data_dir / "HALT"
    if args.off:
        flag.unlink(missing_ok=True)
        print("kill switch off")
    else:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        print("kill switch ENGAGED")
    return 0


def _reset_risk_halt(args: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    state = RiskState(settings.data_path("db") / "paper.sqlite3", args.run_id)
    print(f"clearing risk halt: {state.halt_reason or 'none'}")
    state.halt_reason = None
    state.save()
    return 0


def _bale_chat_id(_: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    if settings.bale_bot_token is None:
        print("BALE_BOT_TOKEN is not set", file=sys.stderr)
        return 2
    token = settings.bale_bot_token.get_secret_value()

    async def run() -> list[dict[str, object]]:
        async with httpx.AsyncClient(timeout=20) as client:
            return await find_chat_ids(token, client)

    chats = asyncio.run(run())
    if not chats:
        print("no messages yet: send any message to your bot in Bale, then retry")
        return 1
    for chat in chats:
        print(f"chat_id={chat['id']} type={chat['type']} name={chat['name']}")
    return 0


def _hourly_summary(args: argparse.Namespace) -> int:
    settings = _settings_or_exit()
    if settings is None:
        return 2
    root = settings.trader_data_dir
    state_path = root / "state" / "summary.json"
    prev = load_state(state_path)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    start = settings.burnin_start
    start_ms = int(start.timestamp() * 1000) if start is not None else None
    report = build_report(gather(root, now_ms, prev, start_ms), prev)
    print(report.text)
    if args.dry_run:
        return 0
    token = settings.bale_bot_token

    async def send() -> bool:
        async with httpx.AsyncClient(timeout=20) as client:
            alerter = Alerter(
                token.get_secret_value() if token else None, settings.bale_chat_id, client
            )
            return await alerter.send_now(report.text)

    if not asyncio.run(send()):
        print("bale delivery failed", file=sys.stderr)
        return 1
    save_state(state_path, report.state)
    return 0


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
    paper = sub.add_parser("run-paper", help="run the rule-baseline paper loop with live data")
    paper.add_argument("--run-id", default="shakedown")
    paper.set_defaults(handler=_run_paper)
    status = sub.add_parser("paper-status", help="show a paper run's account and halts")
    status.add_argument("--run-id", default="shakedown")
    status.set_defaults(handler=_paper_status)
    halt = sub.add_parser("halt", help="engage the kill switch (blocks all orders)")
    halt.add_argument("--off", action="store_true", help="release the kill switch")
    halt.set_defaults(handler=_halt)
    reset = sub.add_parser("reset-risk-halt", help="manually clear a risk halt")
    reset.add_argument("--run-id", default="shakedown")
    reset.set_defaults(handler=_reset_risk_halt)
    bale = sub.add_parser("bale-chat-id", help="list chat ids that messaged the Bale bot")
    bale.set_defaults(handler=_bale_chat_id)
    summary = sub.add_parser("hourly-summary", help="send the Persian status summary to Bale")
    summary.add_argument("--dry-run", action="store_true", help="print only, do not send")
    summary.set_defaults(handler=_hourly_summary)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result
