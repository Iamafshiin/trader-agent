import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader_agent.exchange.models import Kind, MarketRules, Order, Side
from trader_agent.market_data.candles import Candle
from trader_agent.paper.exchange import Book, Costs, Fill, PaperAccount, PaperExchange, asset_of
from trader_agent.risk.gate import AccountView, RiskGate
from trader_agent.strategy.tcp_vp import EntrySignal, ExitSignal, Params, PullbackState, evaluate

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_ms INTEGER, version TEXT,"
    " config_hash TEXT, mode TEXT, config TEXT)",
    "CREATE TABLE IF NOT EXISTS accounts (run_id TEXT PRIMARY KEY, body TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS trades (run_id TEXT, at_ms INTEGER, symbol TEXT, side TEXT,"
    " kind TEXT, amount TEXT, price TEXT, fee TEXT, slippage TEXT, reason TEXT)",
    "CREATE TABLE IF NOT EXISTS equity (run_id TEXT, at_ms INTEGER, equity TEXT, cash TEXT,"
    " exposure TEXT)",
    "CREATE TABLE IF NOT EXISTS decisions (run_id TEXT, at_ms INTEGER, symbol TEXT, body TEXT)",
]


@dataclass(frozen=True)
class MarketInput:
    c15: Sequence[Candle]
    c60: Sequence[Candle]
    book: Book
    data_ok: bool
    context: dict[str, Any]


class PaperStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        for stmt in SCHEMA:
            self.conn.execute(stmt)
        self.conn.commit()

    def ensure_run(self, run_id: str, params: Params, mode: str, now_ms: int) -> None:
        row = self.conn.execute("SELECT config_hash FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row and row[0] != params.config_hash:
            raise RuntimeError(f"run {run_id} was started with a different config")
        if not row:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        now_ms,
                        params.version,
                        params.config_hash,
                        mode,
                        json.dumps(params.raw),
                    ),
                )

    def load_account(self, run_id: str) -> PaperAccount | None:
        row = self.conn.execute("SELECT body FROM accounts WHERE run_id=?", (run_id,)).fetchone()
        return PaperAccount.from_json(json.loads(row[0])) if row else None

    def save_account(self, run_id: str, account: PaperAccount) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO accounts VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET body=excluded.body",
                (run_id, json.dumps(account.to_json())),
            )

    def add_trade(self, run_id: str, fill: Fill, reason: str) -> None:
        o = fill.order
        with self.conn:
            self.conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    fill.at_ms,
                    o.symbol,
                    o.side.value,
                    o.kind.value,
                    str(o.amount),
                    str(fill.price),
                    str(fill.fee),
                    str(fill.slippage),
                    reason,
                ),
            )

    def add_equity(self, run_id: str, at_ms: int, equity: Decimal, cash: Decimal) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO equity VALUES (?, ?, ?, ?, ?)",
                (run_id, at_ms, str(equity), str(cash), str(equity - cash)),
            )

    def add_decision(self, run_id: str, at_ms: int, symbol: str, body: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?)",
                (run_id, at_ms, symbol, json.dumps(body, default=str)),
            )


Alert = Callable[[str], None]


class PaperEngine:
    def __init__(
        self,
        run_id: str,
        params: Params,
        store: PaperStore,
        gate: RiskGate,
        rules: dict[str, MarketRules],
        alert: Alert,
        now_ms: int,
    ) -> None:
        self.run_id = run_id
        self.params = params
        self.store = store
        self.gate = gate
        self.rules = rules
        self.alert = alert
        store.ensure_run(run_id, params, "rule-baseline", now_ms)
        account = store.load_account(run_id) or PaperAccount(params.starting_balance_rls)
        costs = Costs(
            params.maker_fee, params.taker_fee, params.slippage_normal, params.slippage_stop
        )
        self.exchange = PaperExchange(account, costs)
        self.pullbacks = {s: PullbackState() for s in params.symbols}
        self.books: dict[str, Book] = {}

    def in_position(self, symbol: str) -> bool:
        held = self.exchange.account.holdings.get(asset_of(symbol), Decimal(0))
        rules = self.rules.get(symbol)
        return (rules.floor_amount(held) if rules else held) > 0

    def _view(self) -> AccountView:
        return AccountView(
            self.exchange.equity(self.books),
            self.exchange.exposure(self.books),
            dict(self.exchange.account.holdings),
        )

    def on_trade(self, symbol: str, price: Decimal, now_ms: int) -> None:
        book = self.books.get(symbol, Book(None, None, now_ms))
        fill = self.exchange.on_trade(symbol, price, book, now_ms)
        if fill is not None:
            self.store.add_trade(self.run_id, fill, "protective stop")
            self.store.save_account(self.run_id, self.exchange.account)
            self.alert(f"[paper] STOP {symbol} sold {fill.order.amount} @ {fill.price:.0f}")

    def on_candle_close(self, now_ms: int, inputs: dict[str, MarketInput]) -> None:
        for symbol, given in inputs.items():
            self.books[symbol] = given.book
        try:
            view = self._view()
        except LookupError as exc:
            self.alert(f"[paper] cannot mark equity: {exc}")
            return
        halted = self.gate.observe(view.equity, now_ms)
        if halted:
            self.alert(f"[paper] RISK HALT: {halted}. Manual reset required.")
        self.store.add_equity(self.run_id, now_ms, view.equity, self.exchange.account.cash)
        for symbol in self.params.symbols:
            inp = inputs.get(symbol)
            if inp is None:
                continue
            rules = self.rules.get(symbol)
            step = rules.price_step if rules else Decimal(0)
            signal = evaluate(
                self.params,
                symbol,
                inp.c15,
                inp.c60,
                self.in_position(symbol),
                self.pullbacks[symbol],
                inp.data_ok,
                step,
            )
            record: dict[str, Any] = {"data_ok": inp.data_ok, **inp.context}
            if isinstance(signal, EntrySignal):
                record["signal"] = {"type": "entry", **asdict(signal)}
                record["action"] = self._enter(signal, inp, rules, now_ms)
            elif isinstance(signal, ExitSignal):
                record["signal"] = {"type": "exit", **asdict(signal)}
                record["action"] = self._exit(signal, inp, now_ms)
            self.store.add_decision(self.run_id, now_ms, symbol, record)
        self.store.save_account(self.run_id, self.exchange.account)

    def _enter(
        self, sig: EntrySignal, inp: MarketInput, rules: MarketRules | None, now_ms: int
    ) -> str:
        p = self.params
        ask = inp.book.ask
        if rules is None:
            return "skip: market rules unknown"
        if ask is None or inp.book.bid is None:
            return "skip: empty book"
        if sig.stop >= ask:
            return "skip: stop at or above entry"
        view = self._view()
        budget = view.equity * p.position_fraction
        unit = ask * (1 + p.slippage_normal) * (1 + p.taker_fee)
        amount = rules.floor_amount(budget / unit)
        if not self.exchange.rules_check(rules, amount, ask):
            return "skip: below minimum order"
        if view.exposure + amount * unit > view.equity * p.max_deployed_fraction:
            return "skip: max deployed"
        order = Order(
            self.exchange.next_id("buy"), sig.symbol, Side.BUY, Kind.LIMIT, amount, price=ask
        )
        decision = self.gate.check(
            order, view, unit / (1 + p.taker_fee), p.taker_fee, inp.data_ok, True
        )
        if not decision.allowed:
            return f"blocked: {decision.reason}"
        fill = self.exchange.market_buy_at_touch(order, inp.book, now_ms)
        self.store.add_trade(self.run_id, fill, "entry")
        held = rules.floor_amount(self.exchange.account.holdings[asset_of(sig.symbol)])
        stop = Order(
            self.exchange.next_id("stop"),
            sig.symbol,
            Side.SELL,
            Kind.STOP_MARKET,
            held,
            stop_price=rules.floor_price(sig.stop),
        )
        self.exchange.place_stop(stop)
        self.alert(
            f"[paper] BUY {sig.symbol} {amount} @ {fill.price:.0f}, stop {stop.stop_price:.0f}"
        )
        return f"bought {amount}"

    def _exit(self, sig: ExitSignal, inp: MarketInput, now_ms: int) -> str:
        asset = asset_of(sig.symbol)
        rules = self.rules.get(sig.symbol)
        held = self.exchange.account.holdings.get(asset, Decimal(0))
        amount = rules.floor_amount(held) if rules else held
        if inp.book.bid is None:
            return "skip: empty book"
        order = Order(
            self.exchange.next_id("sell"),
            sig.symbol,
            Side.SELL,
            Kind.LIMIT,
            amount,
            price=inp.book.bid,
        )
        decision = self.gate.check(
            order, self._view(), inp.book.bid, self.params.taker_fee, inp.data_ok, True
        )
        if not decision.allowed:
            return f"blocked: {decision.reason}"
        self.exchange.cancel_stop(sig.symbol)
        fill = self.exchange.market_sell_at_touch(order, inp.book, now_ms)
        self.store.add_trade(self.run_id, fill, sig.reason)
        self.alert(f"[paper] SELL {sig.symbol} {amount} @ {fill.price:.0f} ({sig.reason})")
        return f"sold {amount}"
