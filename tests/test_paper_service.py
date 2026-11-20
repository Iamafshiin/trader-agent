from decimal import Decimal
from pathlib import Path

import pytest

from trader_agent.cli.main import main
from trader_agent.market_data.candles import Candle
from trader_agent.paper.service import (
    PaperService,
    best_prices,
    is_signal_boundary,
    last_closed_open,
    latest_closed_hour_open,
    parse_rules,
    warmup_days,
)
from trader_agent.settings import load_settings
from trader_agent.strategy.tcp_vp import load_params

D = Decimal

OPTIONS = {
    "nobitex": {
        "minOrders": {"rls": "500000", "usdt": "0.5"},
        "amountPrecisions": {"BTCIRT": "0.000001", "ETHIRT": "0.00001"},
        "pricePrecisions": {"BTCIRT": "10", "ETHIRT": "10"},
    }
}


def test_parse_rules_skips_unknown_markets() -> None:
    rules = parse_rules(OPTIONS, ("BTCIRT", "ETHIRT", "USDTIRT"))
    assert set(rules) == {"BTCIRT", "ETHIRT"}
    assert rules["BTCIRT"].amount_step == D("0.000001")
    assert rules["BTCIRT"].min_notional == D(500000)
    assert rules["BTCIRT"].floor_amount(D("0.0000019")) == D("0.000001")


def test_best_prices_handle_order_and_empty_sides() -> None:
    assert best_prices(
        {"bids": [["90", "1"], ["95", "1"]], "asks": [["101", "1"], ["100", "2"]]}
    ) == (
        D(95),
        D(100),
    )
    assert best_prices({"bids": [], "asks": []}) == (None, None)


def test_latest_closed_hour_uses_tehran_alignment() -> None:
    now_ms = (1_794_213_000 + 3600 + 120) * 1000
    assert latest_closed_hour_open(now_ms) == 1_794_213_000


def test_on_message_updates_books_and_trade_buffer(tmp_path: Path) -> None:
    settings = load_settings(trader_data_dir=tmp_path)
    svc = PaperService(settings, load_params(), "t")
    svc.on_message("public:orderbook-BTCIRT", {"bids": [["10", "1"]], "asks": [["12", "1"]]}, 5)
    assert svc.books["BTCIRT"].bid == D(10)
    svc.on_message("public:trades-BTCIRT", {"price": "11", "volume": "0.5", "time": 1}, 5)
    svc.on_message(
        "public:trades-BTCIRT", {"price": "11", "volume": "0.5", "time": 200_000_000}, 200_000_000
    )
    assert [t for t, _, _ in svc.trades["BTCIRT"]] == [200_000_000]


def test_inputs_fail_closed_without_data(tmp_path: Path) -> None:
    settings = load_settings(trader_data_dir=tmp_path)
    svc = PaperService(settings, load_params(), "t")
    inputs = svc.inputs(1_794_906_000_000)
    assert all(not i.data_ok for i in inputs.values())


def hourly(n: int, start: int) -> list[Candle]:
    return [
        Candle("BTCIRT", "60", start + i * 3600, D(p), D(p + 1), D(p - 1), D(p), D(1))
        for i, p in enumerate(range(100, 100 + n))
    ]


def test_v2_inputs_build_closed_four_hour_bars_from_hourly(tmp_path: Path) -> None:
    settings = load_settings(trader_data_dir=tmp_path)
    svc = PaperService(settings, load_params(), "t")
    start = 1_794_213_000 - 1300 * 3600
    bars = hourly(1300 + 2, start)
    svc.candles.insert(bars, fetched_at=0)
    now_s = start + (1300 + 2) * 3600 + 60
    inp = svc.inputs(now_s * 1000)["BTCIRT"]
    checks = inp.context["checks"]
    assert checks["candle_1h_current"] is True
    assert checks["candle_4h_current"] is True
    assert len(inp.signal_bars) == 300
    assert len(inp.trend_bars) == 300
    last_4h = inp.trend_bars[-1]
    assert last_4h.open_time + 14400 <= now_s
    assert last_4h.open_time == last_closed_open(now_s, 14400)


def test_v2_runs_only_on_hourly_boundaries_and_backfills_enough_history() -> None:
    v2 = load_params()
    hour = 1_794_213_000
    assert is_signal_boundary(hour + 20, v2)
    assert not is_signal_boundary(hour + 900 + 20, v2)
    assert is_signal_boundary(hour + 900 + 20, load_params(version="tcp-vp-1"))
    assert warmup_days(v2) * 24 >= 300 * 4
    assert warmup_days(load_params(version="tcp-vp-1")) * 24 >= 300


def test_halt_command_toggles_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    assert main(["halt"]) == 0
    assert (tmp_path / "HALT").exists()
    assert main(["halt", "--off"]) == 0
    assert not (tmp_path / "HALT").exists()
