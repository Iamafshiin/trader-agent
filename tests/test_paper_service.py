from decimal import Decimal
from pathlib import Path

import pytest

from trader_agent.cli.main import main
from trader_agent.paper.service import (
    PaperService,
    best_prices,
    latest_closed_hour_open,
    parse_rules,
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


def test_halt_command_toggles_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    assert main(["halt"]) == 0
    assert (tmp_path / "HALT").exists()
    assert main(["halt", "--off"]) == 0
    assert not (tmp_path / "HALT").exists()
