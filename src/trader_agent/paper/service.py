import asyncio
import time
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import websockets

from trader_agent.exchange.models import MarketRules
from trader_agent.market_data.bars import LABEL, STEP, bucket_open, closed_bars
from trader_agent.market_data.candles import Candle, CandleCollector, CandleSourceError, RawLog
from trader_agent.market_data.streams import (
    WS_URL,
    FreshnessBounds,
    RawWriter,
    StreamRecorder,
    StreamState,
    channels_for,
    is_fresh,
    make_seeder,
)
from trader_agent.ops.bale import Alerter
from trader_agent.ops.commands import CommandHandler, CommandPoller, HttpBaleClient
from trader_agent.paper.engine import MarketInput, PaperEngine, PaperStore
from trader_agent.paper.exchange import Book
from trader_agent.risk.gate import RiskGate, RiskState
from trader_agent.settings import Settings
from trader_agent.storage.candles import CandleStore
from trader_agent.strategy.tcp_vp import Params, trend
from trader_agent.strategy.volume_profile import build_profile

DAY_MS = 86_400_000
WINDOW_MS = 900_000
WINDOW = 300
STORED = ("15", "60")


def parse_rules(options: dict[str, Any], symbols: tuple[str, ...]) -> dict[str, MarketRules]:
    n = options["nobitex"]
    min_rls = Decimal(str(n["minOrders"]["rls"]))
    return {
        s: MarketRules(
            s,
            Decimal(str(n["amountPrecisions"][s])),
            Decimal(str(n["pricePrecisions"][s])),
            min_rls,
        )
        for s in symbols
        if s in n["amountPrecisions"] and s in n["pricePrecisions"]
    }


def best_prices(data: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    bids = [Decimal(str(p)) for p, _ in data.get("bids") or []]
    asks = [Decimal(str(p)) for p, _ in data.get("asks") or []]
    return (max(bids) if bids else None, min(asks) if asks else None)


def latest_closed_hour_open(now_ms: int) -> int:
    return last_closed_open(now_ms // 1000, 3600)


def last_closed_open(now_s: int, step: int) -> int:
    return bucket_open(now_s, step) - step


def warmup_days(params: Params) -> float:
    step = STEP[params.trend_resolution]
    return max(12.0, (WINDOW + 2) * step / 86400)


def is_signal_boundary(now_s: int, params: Params) -> bool:
    return bucket_open(now_s, STEP[params.signal_resolution]) == bucket_open(now_s, 900)


class PaperService:
    def __init__(self, settings: Settings, params: Params, run_id: str) -> None:
        self.settings = settings
        self.params = params
        self.run_id = run_id
        self.root = settings.trader_data_dir
        self.headers = {"User-Agent": settings.nobitex_user_agent}
        self.stream_state = StreamState()
        self.bounds = FreshnessBounds()
        self.books: dict[str, Book] = {}
        self.trades: dict[str, deque[tuple[int, Decimal, Decimal]]] = {
            s: deque() for s in params.symbols
        }
        self.engine: PaperEngine | None = None
        self.candles = CandleStore(settings.data_path("db") / "candles.sqlite3")

    def on_message(self, channel: str, data: Any, recv_ms: int) -> None:
        if not isinstance(data, dict):
            return
        name = channel.removeprefix("public:")
        kind, _, rest = name.partition("-")
        if kind == "orderbook":
            bid, ask = best_prices(data)
            self.books[rest] = Book(bid, ask, recv_ms)
            if self.engine is not None:
                self.engine.books[rest] = self.books[rest]
        elif kind == "trades" and rest in self.trades:
            price, volume = Decimal(str(data["price"])), Decimal(str(data["volume"]))
            buf = self.trades[rest]
            buf.append((int(data.get("time", recv_ms)), price, volume))
            while buf and buf[0][0] < recv_ms - DAY_MS - WINDOW_MS:
                buf.popleft()
            if self.engine is not None:
                self.engine.on_trade(rest, price, recv_ms)

    def backfill(self, spans: dict[str, float]) -> list[str]:
        errors: list[str] = []
        store = CandleStore(self.settings.data_path("db") / "candles.sqlite3")
        with httpx.Client(
            base_url=self.settings.nobitex_base_url, headers=self.headers, timeout=20
        ) as client:
            collector = CandleCollector(client, store, RawLog(self.root))
            for symbol in self.params.symbols:
                for res, days in spans.items():
                    try:
                        collector.collect(symbol, res, days)
                    except (httpx.HTTPError, CandleSourceError) as exc:
                        errors.append(f"{symbol}/{res}: {exc}")
        store.close()
        return errors

    def bars(self, symbol: str, resolution: str, now_s: int) -> list[Candle]:
        if resolution in STORED:
            return self.candles.load(symbol, resolution, WINDOW)
        step = STEP[resolution]
        hourly = self.candles.load(symbol, "60", WINDOW * step // 3600 + step // 3600)
        return closed_bars(hourly, step, now_s)[-WINDOW:]

    def inputs(self, now_ms: int) -> dict[str, MarketInput]:
        now_s = now_ms // 1000
        sig_res, trend_res = self.params.signal_resolution, self.params.trend_resolution
        sig_label, trend_label = LABEL[sig_res], LABEL[trend_res]
        out: dict[str, MarketInput] = {}
        for s in self.params.symbols:
            sig_bars = self.bars(s, sig_res, now_s)
            trend_bars = self.bars(s, trend_res, now_s)
            cd = self.candles.load(s, "D", 80)
            book = self.books.get(s, Book(None, None, 0))
            checks = {
                f"candle_{sig_label}_current": bool(sig_bars)
                and sig_bars[-1].open_time == last_closed_open(now_s, STEP[sig_res]),
                f"candle_{trend_label}_current": bool(trend_bars)
                and trend_bars[-1].open_time == last_closed_open(now_s, STEP[trend_res]),
                "orderbook_fresh": is_fresh(
                    self.stream_state, f"public:orderbook-{s}", now_ms, self.bounds
                ),
                "book_two_sided": book.bid is not None and book.ask is not None,
            }
            context: dict[str, Any] = {"checks": checks}
            td = trend(cd, self.params.ema_fast, self.params.ema_slow) if cd else None
            context["trend_1d_up"] = None if td is None else td.up
            last = sig_bars[-1].close if sig_bars else None
            if last is not None:
                trades = self.trades[s]
                rolling = [(p, v) for t, p, v in trades if t >= now_ms - DAY_MS]
                prior = [
                    (p, v)
                    for t, p, v in trades
                    if now_ms - DAY_MS - WINDOW_MS <= t < now_ms - DAY_MS
                ]
                for label, window in (("profile_24h", rolling), ("profile_prev_day_15m", prior)):
                    prof = build_profile(
                        window, last, self.params.profile_row_fraction, self.params.value_area_share
                    )
                    context[label] = (
                        None
                        if prof is None
                        else {
                            "poc": prof.poc,
                            "vah": prof.vah,
                            "val": prof.val,
                            "volume": prof.total_volume,
                        }
                    )
            out[s] = MarketInput(sig_bars, trend_bars, book, all(checks.values()), context)
        return out

    async def fetch_rules(self, client: httpx.AsyncClient) -> dict[str, MarketRules]:
        r = await client.get("/v2/options")
        r.raise_for_status()
        return parse_rules(r.json(), self.params.symbols)

    async def scheduler(self, alerter: Alerter) -> None:
        assert self.engine is not None
        while True:
            now = time.time()
            next_tick = (int(now) // 900 + 1) * 900 + 20
            await asyncio.sleep(max(0.0, next_tick - now))
            errors = await asyncio.to_thread(self.backfill, {"15": 0.25, "60": 0.5, "D": 3})
            if errors:
                alerter.post("[paper] candle fetch errors: " + "; ".join(errors)[:500])
            now_ms = int(time.time() * 1000)
            if not is_signal_boundary(now_ms // 1000, self.params):
                continue
            try:
                self.engine.on_candle_close(now_ms, self.inputs(now_ms))
            except Exception as exc:
                alerter.post(f"[paper] engine error: {type(exc).__name__}: {exc}")
                raise

    async def run(self) -> None:
        async with (
            httpx.AsyncClient(
                base_url=self.settings.nobitex_base_url, headers=self.headers, timeout=20
            ) as client,
            httpx.AsyncClient(timeout=20) as bale_client,
        ):
            token = self.settings.bale_bot_token
            alerter = Alerter(
                token.get_secret_value() if token else None, self.settings.bale_chat_id, bale_client
            )
            sender = asyncio.create_task(alerter.run())
            poller = None
            if token and self.settings.bale_chat_id:
                poller = asyncio.create_task(
                    CommandPoller(
                        HttpBaleClient(token.get_secret_value(), bale_client),
                        self.settings.bale_chat_id,
                        CommandHandler(
                            self.root, self.run_id, self.settings.data_path("db") / "paper.sqlite3"
                        ),
                    ).run()
                )
            rules = await self.fetch_rules(client)
            errors = await asyncio.to_thread(
                self.backfill, {"15": 8, "60": warmup_days(self.params), "D": 80}
            )
            now_ms = int(time.time() * 1000)
            risk = RiskState(self.settings.data_path("db") / "paper.sqlite3", self.run_id)
            gate = RiskGate(risk, self.root / "HALT")
            self.engine = PaperEngine(
                self.run_id,
                self.params,
                PaperStore(self.settings.data_path("db") / "paper.sqlite3"),
                gate,
                rules,
                alerter.post,
                now_ms,
            )
            self.engine.books.update(self.books)
            alerter.post(
                f"[paper] run '{self.run_id}' started: {self.params.version} "
                f"{self.params.config_hash[:12]}, markets {', '.join(sorted(rules))}"
                + (f", backfill errors: {len(errors)}" if errors else "")
            )
            writer = RawWriter(self.root)
            recorder = StreamRecorder(
                lambda: websockets.connect(WS_URL, user_agent_header=self.headers["User-Agent"]),
                channels_for(self.params.symbols),
                writer,
                self.stream_state,
                seed=make_seeder(client),
                state_path=self.settings.data_path("state") / "streams.json",
                on_message=self.on_message,
            )
            try:
                await asyncio.gather(recorder.run_forever(), self.scheduler(alerter))
            finally:
                writer.close()
                tasks = [t for t in (sender, poller) if t is not None]
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await alerter.send_now(f"[paper] run '{self.run_id}' stopped")


def kill_switch_path(root: Path) -> Path:
    return root / "HALT"
