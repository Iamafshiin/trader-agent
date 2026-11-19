import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trader_agent.dashboard.app import create_app
from trader_agent.dashboard.data import Reader, open_ro
from trader_agent.market_data.candles import Candle
from trader_agent.paper.engine import PaperStore
from trader_agent.paper.exchange import PaperAccount
from trader_agent.risk.gate import RiskState
from trader_agent.storage.candles import CandleStore
from trader_agent.strategy.tcp_vp import load_params

D = Decimal
BASE = 1_795_000_500
NOW_MS = (BASE + 100 * 900) * 1000


def seed(root: Path) -> None:
    db = root / "db"
    store = CandleStore(db / "candles.sqlite3")
    candles = [
        Candle("BTCIRT", "15", BASE + i * 900, D(100 + i), D(102 + i), D(99 + i), D(101 + i), D(5))
        for i in range(120)
    ]
    store.insert(candles, 0)
    store.close()
    paper = PaperStore(db / "paper.sqlite3")
    params = load_params()
    paper.ensure_run("study", params, "paper", NOW_MS - 10_000)
    account = PaperAccount(D(900_000_000), {"BTC": D("0.5")})
    paper.save_account("study", account)
    paper.add_equity("study", NOW_MS - 900_000, D(1_000_000_000), D(900_000_000))
    paper.add_equity("study", NOW_MS, D(1_010_000_000), D(900_000_000))
    paper.add_decision(
        "study",
        BASE * 1000 + 80 * 900_000 + 20_000,
        "BTCIRT",
        {"data_ok": True, "signal": {"type": "entry"}, "action": "filled", "critic": {"ok": 1}},
    )
    paper.add_decision("study", NOW_MS, "BTCIRT", {"data_ok": False})
    paper.conn.close()
    risk = RiskState(db / "paper.sqlite3", "study")
    risk.halt_reason = "max drawdown limit hit"
    risk.save()
    risk.close()
    state = root / "state"
    state.mkdir()
    (state / "streams.json").write_text(
        json.dumps(
            {
                "at_ms": NOW_MS,
                "reconnects": 2,
                "channels": {
                    "public:orderbook-BTCIRT": {
                        "messages": 10,
                        "gaps": 1,
                        "lost": 3,
                        "last_recv_ms": NOW_MS - 5000,
                    }
                },
            }
        )
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    seed(tmp_path)
    return tmp_path


@pytest.fixture
def client(root: Path) -> TestClient:
    reader = Reader(root, load_params(), NOW_MS - 86_400_000)
    return TestClient(create_app(reader))


def test_index_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "lightweight-charts" in r.text


def test_candles_with_ema_profile_and_markers(client: TestClient) -> None:
    r = client.get("/api/candles", params={"symbol": "BTCIRT", "resolution": "15", "limit": 60})
    body = r.json()
    assert len(body["candles"]) == 60
    assert len(body["ema_fast"]["data"]) == 60
    assert len(body["ema_slow"]["data"]) == 60
    assert body["profile"]["val"] <= body["profile"]["poc"] <= body["profile"]["vah"]
    assert body["markers"] == [{"time": BASE + 79 * 900, "type": "entry"}]


def test_candles_rejects_unknown_inputs(client: TestClient) -> None:
    assert client.get("/api/candles", params={"symbol": "XXX"}).status_code == 404
    assert (
        client.get("/api/candles", params={"symbol": "BTCIRT", "resolution": "5"}).status_code
        == 404
    )


def test_paper_state(client: TestClient, root: Path) -> None:
    body = client.get("/api/paper").json()
    assert body["run_id"] == "study"
    assert body["equity"] == 1_010_000_000
    assert body["halt_reason"] == "max drawdown limit hit"
    assert body["kill_switch"] is False
    assert len(body["curve"]) == 2
    assert body["positions"][0]["symbol"] == "BTCIRT"
    assert body["positions"][0]["value"] == pytest.approx(0.5 * 220)
    (root / "HALT").touch()
    assert client.get("/api/paper").json()["kill_switch"] is True


def test_streams_and_overview(client: TestClient) -> None:
    streams = client.get("/api/streams").json()
    assert streams["reconnects"] == 2
    assert streams["channels"][0]["gaps"] == 1
    overview = client.get("/api/overview").json()
    assert overview["burnin"]["days"] == 7
    assert 0 < overview["burnin"]["progress"] <= 1


def test_decisions_expose_critic(client: TestClient) -> None:
    body = client.get("/api/decisions").json()
    assert len(body["decisions"]) == 2
    assert body["decisions"][1]["critic"] == {"ok": 1}


def test_empty_data_dir_is_handled(tmp_path: Path) -> None:
    client = TestClient(create_app(Reader(tmp_path, load_params(), None)))
    assert client.get("/api/paper").json()["available"] is False
    assert client.get("/api/decisions").json()["available"] is False
    assert client.get("/api/streams").json()["available"] is False
    assert client.get("/api/candles", params={"symbol": "BTCIRT"}).json()["candles"] == []
    assert client.get("/api/overview").json()["burnin"] is None


def test_connection_is_read_only(root: Path) -> None:
    with open_ro(root / "db" / "paper.sqlite3") as conn:
        assert conn is not None
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM equity")
