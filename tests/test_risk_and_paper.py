from decimal import Decimal
from pathlib import Path

import pytest

from trader_agent.exchange.models import InvalidTransition, Kind, MarketRules, Order, Side, Status
from trader_agent.market_data.candles import Candle
from trader_agent.paper.engine import MarketInput, PaperEngine, PaperStore
from trader_agent.paper.exchange import Book
from trader_agent.risk.gate import AccountView, Limits, RiskGate, RiskState, tehran_day
from trader_agent.strategy.tcp_vp import load_params

D = Decimal
DAY0 = 1_794_873_600_000
PARAMS = load_params()
RULES = {
    s: MarketRules(s, D(a), D(10), D(500000))
    for s, a in [("BTCIRT", "0.000001"), ("ETHIRT", "0.00001"), ("USDTIRT", "0.01")]
}


def gate(tmp_path: Path, run: str = "r") -> RiskGate:
    return RiskGate(RiskState(tmp_path / "risk.sqlite3", run), tmp_path / "HALT")


def buy(amount: str) -> Order:
    return Order("b", "BTCIRT", Side.BUY, Kind.LIMIT, D(amount))


def view(equity: int = 1000, exposure: int = 0, btc: str = "0") -> AccountView:
    return AccountView(D(equity), D(exposure), {"BTC": D(btc)})


def test_order_state_machine_rejects_bad_transitions() -> None:
    o = buy("1")
    o.move(Status.ACTIVE)
    o.move(Status.FILLED)
    with pytest.raises(InvalidTransition):
        o.move(Status.CANCELED)


def test_tehran_day_rolls_at_2030_utc() -> None:
    assert tehran_day(DAY0 - 12_600_000 - 1) == "2026-11-16"
    assert tehran_day(DAY0 - 12_600_000) == "2026-11-17"


def test_buy_blocked_until_start_of_day_known(tmp_path: Path) -> None:
    g = gate(tmp_path)
    assert g.check(buy("1"), view(), D(5), D(0), True, True).reason == "start-of-day equity unknown"
    g.observe(D(1000), DAY0)
    assert g.check(buy("1"), view(), D(5), D(0), True, True).allowed


@pytest.mark.parametrize(
    ("amount", "exposure", "allowed", "reason"),
    [
        ("2", 0, True, ""),
        ("2.01", 0, False, "per-order limit"),
        ("2", 90, True, ""),
        ("2", 91, False, "total exposure limit"),
    ],
)
def test_order_limits_at_boundaries(
    tmp_path: Path, amount: str, exposure: int, allowed: bool, reason: str
) -> None:
    g = gate(tmp_path)
    g.observe(D(1000), DAY0)
    d = g.check(buy(amount), view(exposure=exposure), D(5), D(0), True, True)
    assert (d.allowed, d.reason) == (allowed, reason)


def test_fail_closed_on_stale_data_and_unknown_rules(tmp_path: Path) -> None:
    g = gate(tmp_path)
    g.observe(D(1000), DAY0)
    assert g.check(buy("1"), view(), D(5), D(0), False, True).reason == "market data stale"
    assert g.check(buy("1"), view(), D(5), D(0), True, False).reason == "market rules unknown"


def test_daily_loss_halts_and_survives_restart(tmp_path: Path) -> None:
    g = gate(tmp_path)
    g.observe(D(1000), DAY0)
    assert g.observe(D(991), DAY0 + 1000) is None
    assert g.observe(D(990), DAY0 + 2000) is not None
    g.state.close()
    g2 = gate(tmp_path)
    assert not g2.check(buy("1"), view(), D(5), D(0), True, True).allowed
    assert g2.check(
        Order("s", "BTCIRT", Side.SELL, Kind.LIMIT, D(1)), view(btc="1"), D(5), D(0), True, True
    ).allowed
    g2.observe(D(1000), DAY0 + 86_400_000)
    assert g2.state.halt_reason is not None
    g2.reset_halt()
    assert g2.check(buy("1"), view(), D(5), D(0), True, True).allowed


def test_drawdown_halt_across_days(tmp_path: Path) -> None:
    g = gate(tmp_path)
    g.observe(D(1000), DAY0)
    g.observe(D(995), DAY0 + 86_400_000)
    g.observe(D(986), DAY0 + 2 * 86_400_000)
    g.observe(D(977), DAY0 + 3 * 86_400_000)
    g.observe(D(968), DAY0 + 4 * 86_400_000)
    assert g.state.halt_reason is None
    assert g.observe(D(950), DAY0 + 5 * 86_400_000 + 1) is not None
    assert g.state.halt_reason == "max drawdown limit hit"


def test_kill_switch_blocks_everything(tmp_path: Path) -> None:
    g = gate(tmp_path)
    g.observe(D(1000), DAY0)
    (tmp_path / "HALT").touch()
    sell = Order("s", "BTCIRT", Side.SELL, Kind.LIMIT, D(1))
    assert g.check(sell, view(btc="1"), D(5), D(0), True, True).reason == "kill switch engaged"


def series(symbol: str, res: str, n: int, start: float, step: float) -> list[Candle]:
    out = []
    for i in range(n):
        c = D(str(start + i * step))
        out.append(Candle(symbol, res, i * 900, c, c + 1, c - 1, c, D(1)))
    return out


def make_engine(tmp_path: Path, alerts: list[str]) -> PaperEngine:
    return PaperEngine(
        "study",
        PARAMS,
        PaperStore(tmp_path / "paper.sqlite3"),
        gate(tmp_path, "study"),
        RULES,
        alerts.append,
        DAY0,
    )


def btc_inputs(c15: list[Candle], bid: int, ask: int, ok: bool = True) -> dict[str, MarketInput]:
    c60 = series("BTCIRT", "60", 300, 1_000_000, 1000)
    return {"BTCIRT": MarketInput(c15, c60, Book(D(bid), D(ask), DAY0), ok, {})}


def entry_candles() -> list[Candle]:
    base = series("BTCIRT", "15", 300, 1_000_000, 1000)
    last = base[-1].close
    dip = Candle("BTCIRT", "15", 300 * 900, last, last, last - 20000, last - 15000, D(1))
    up = Candle("BTCIRT", "15", 301 * 900, last, last + 5000, last - 16000, last + 5000, D(1))
    return [*base, dip, up]


def test_engine_enters_sets_stop_and_stop_fills(tmp_path: Path) -> None:
    alerts: list[str] = []
    eng = make_engine(tmp_path, alerts)
    c = entry_candles()
    eng.on_candle_close(DAY0, btc_inputs(c[:-1], 1_300_000, 1_300_010))
    eng.on_candle_close(DAY0 + 900_000, btc_inputs(c, 1_300_000, 1_300_010))
    acct = eng.exchange.account
    assert eng.in_position("BTCIRT")
    stop = acct.stops["BTCIRT"]
    assert stop.stop_price is not None and stop.stop_price < D(1_300_010)
    spent = PARAMS.starting_balance_rls - acct.cash
    assert spent <= PARAMS.starting_balance_rls * D("0.01")
    assert any("BUY BTCIRT" in a for a in alerts)
    eng.on_trade("BTCIRT", stop.stop_price - 10, DAY0 + 1_000_000)
    assert not eng.in_position("BTCIRT")
    assert "BTCIRT" not in acct.stops
    trades = eng.store.conn.execute("SELECT reason FROM trades ORDER BY at_ms").fetchall()
    assert [r[0] for r in trades] == ["entry", "protective stop"]


def enter_position(eng: PaperEngine) -> None:
    c = entry_candles()
    eng.on_candle_close(DAY0, btc_inputs(c[:-1], 1_300_000, 1_300_010))
    eng.on_candle_close(DAY0 + 900_000, btc_inputs(c, 1_300_000, 1_300_010))
    assert eng.in_position("BTCIRT")


def test_flatten_sells_through_gate_and_cancels_stop(tmp_path: Path) -> None:
    alerts: list[str] = []
    eng = make_engine(tmp_path, alerts)
    enter_position(eng)
    results = eng.flatten(DAY0 + 1_000_000)
    assert [(s, st) for s, st, _ in results] == [("BTCIRT", "sold")]
    assert not eng.in_position("BTCIRT")
    assert "BTCIRT" not in eng.exchange.account.stops
    trades = eng.store.conn.execute("SELECT reason FROM trades ORDER BY at_ms").fetchall()
    assert [r[0] for r in trades] == ["entry", "operator flatten"]
    assert any("FLATTEN BTCIRT" in a for a in alerts)
    assert eng.flatten(DAY0 + 1_100_000) == []


def test_flatten_respects_kill_switch(tmp_path: Path) -> None:
    eng = make_engine(tmp_path, [])
    enter_position(eng)
    (tmp_path / "HALT").touch()
    results = eng.flatten(DAY0 + 1_000_000)
    assert [(s, st) for s, st, _ in results] == [("BTCIRT", "blocked")]
    assert eng.in_position("BTCIRT")
    assert "BTCIRT" in eng.exchange.account.stops


def test_engine_state_survives_restart(tmp_path: Path) -> None:
    eng = make_engine(tmp_path, [])
    c = entry_candles()
    eng.on_candle_close(DAY0, btc_inputs(c[:-1], 1_300_000, 1_300_010))
    eng.on_candle_close(DAY0 + 900_000, btc_inputs(c, 1_300_000, 1_300_010))
    cash = eng.exchange.account.cash
    eng2 = make_engine(tmp_path, [])
    assert eng2.exchange.account.cash == cash
    assert "BTCIRT" in eng2.exchange.account.stops


def test_engine_rejects_changed_config_for_same_run(tmp_path: Path) -> None:
    make_engine(tmp_path, [])
    store = PaperStore(tmp_path / "paper.sqlite3")
    other = load_params()
    object.__setattr__(other, "config_hash", "x" * 64)
    with pytest.raises(RuntimeError):
        store.ensure_run("study", other, "rule-baseline", DAY0)


def test_engine_skips_entry_on_stale_data(tmp_path: Path) -> None:
    eng = make_engine(tmp_path, [])
    c = entry_candles()
    eng.on_candle_close(DAY0, btc_inputs(c[:-1], 1_300_000, 1_300_010))
    eng.on_candle_close(DAY0 + 900_000, btc_inputs(c, 1_300_000, 1_300_010, ok=False))
    assert not eng.in_position("BTCIRT")


def test_limits_default_values() -> None:
    assert Limits() == Limits(D("0.01"), D("0.10"), D("0.01"), D("0.05"))
