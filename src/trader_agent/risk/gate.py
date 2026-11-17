import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trader_agent.exchange.models import Order, Side

TEHRAN = timedelta(hours=3, minutes=30)


def tehran_day(now_ms: int) -> str:
    return (datetime.fromtimestamp(now_ms / 1000, UTC) + TEHRAN).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Limits:
    per_order: Decimal = Decimal("0.01")
    total_exposure: Decimal = Decimal("0.10")
    daily_loss: Decimal = Decimal("0.01")
    max_drawdown: Decimal = Decimal("0.05")


@dataclass(frozen=True)
class AccountView:
    equity: Decimal
    exposure: Decimal
    holdings: dict[str, Decimal]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


class RiskState:
    def __init__(self, path: Path, run_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS risk_state (run_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self._run_id = run_id
        row = self._conn.execute("SELECT body FROM risk_state WHERE run_id=?", (run_id,)).fetchone()
        body = json.loads(row[0]) if row else {}
        self.day: str | None = body.get("day")
        self.start_of_day: Decimal | None = _dec(body.get("start_of_day"))
        self.high_water: Decimal | None = _dec(body.get("high_water"))
        self.halt_reason: str | None = body.get("halt_reason")

    def save(self) -> None:
        body = {
            "day": self.day,
            "start_of_day": _str(self.start_of_day),
            "high_water": _str(self.high_water),
            "halt_reason": self.halt_reason,
        }
        with self._conn:
            self._conn.execute(
                "INSERT INTO risk_state VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET body=excluded.body",
                (self._run_id, json.dumps(body)),
            )

    def close(self) -> None:
        self._conn.close()


def _dec(v: str | None) -> Decimal | None:
    return None if v is None else Decimal(v)


def _str(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


class RiskGate:
    def __init__(self, state: RiskState, kill_switch: Path, limits: Limits = Limits()) -> None:
        self.state = state
        self.kill_switch = kill_switch
        self.limits = limits

    def observe(self, equity: Decimal, now_ms: int) -> str | None:
        s = self.state
        day = tehran_day(now_ms)
        if s.day != day:
            s.day = day
            s.start_of_day = equity
        if s.high_water is None or equity > s.high_water:
            s.high_water = equity
        newly_halted = None
        if s.halt_reason is None and s.start_of_day is not None:
            if equity <= s.start_of_day * (1 - self.limits.daily_loss):
                s.halt_reason = f"daily loss limit hit on {day}"
            elif equity <= s.high_water * (1 - self.limits.max_drawdown):
                s.halt_reason = "max drawdown limit hit"
            newly_halted = s.halt_reason
        s.save()
        return newly_halted

    def reset_halt(self) -> None:
        self.state.halt_reason = None
        self.state.save()

    def check(
        self,
        order: Order,
        account: AccountView,
        reference_price: Decimal,
        fee_rate: Decimal,
        data_fresh: bool,
        rules_known: bool,
    ) -> Decision:
        if self.kill_switch.exists():
            return Decision(False, "kill switch engaged")
        asset = order.symbol.removesuffix("IRT")
        if order.side is Side.SELL:
            if order.amount > account.holdings.get(asset, Decimal(0)):
                return Decision(False, "sell exceeds holdings")
            return Decision(True)
        s = self.state
        if s.halt_reason is not None:
            return Decision(False, f"risk halt: {s.halt_reason}")
        if not data_fresh:
            return Decision(False, "market data stale")
        if not rules_known:
            return Decision(False, "market rules unknown")
        if s.start_of_day is None or account.equity <= 0:
            return Decision(False, "start-of-day equity unknown")
        cost = order.amount * reference_price * (1 + fee_rate)
        if cost > account.equity * self.limits.per_order:
            return Decision(False, "per-order limit")
        if account.exposure + cost > account.equity * self.limits.total_exposure:
            return Decision(False, "total exposure limit")
        return Decision(True)
