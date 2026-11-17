import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from trader_agent.market_data.streams import (
    RawWriter,
    StreamRecorder,
    StreamState,
    channels_for,
    completeness_report,
    is_fresh,
    kind_of,
    read_records,
)

DAY_MS = 1_794_873_600_000


class FakeWS:
    def __init__(self, incoming: list[str]) -> None:
        self.incoming = list(incoming)
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if not self.incoming:
            raise ConnectionError("closed")
        return self.incoming.pop(0)

    async def __aenter__(self) -> "FakeWS":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def push(channel: str, offset: int, data: Any) -> str:
    return json.dumps({"push": {"channel": channel, "pub": {"data": data, "offset": offset}}})


def sub_ok(i: int, epoch: str, offset: int, **extra: Any) -> str:
    return json.dumps({"id": i, "subscribe": {"epoch": epoch, "offset": offset, **extra}})


def make(
    tmp_path: Path, sessions: list[FakeWS], channels: list[str], now: list[int]
) -> tuple[StreamRecorder, StreamState, RawWriter]:
    state = StreamState()
    writer = RawWriter(tmp_path)
    queue = list(sessions)

    async def seed(symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "bids": [], "asks": []}

    recorder = StreamRecorder(
        lambda: queue.pop(0),
        channels,
        writer,
        state,
        seed=seed,
        clock_ms=lambda: now[0],
        state_path=tmp_path / "state" / "streams.json",
    )
    return recorder, state, writer


def test_channel_naming() -> None:
    assert channels_for(["BTCIRT"]) == [
        "public:orderbook-BTCIRT",
        "public:trades-BTCIRT",
        "public:candle-BTCIRT-15",
    ]
    assert kind_of("public:candle-BTCIRT-15") == "candle"


def test_records_pushes_answers_pings_and_seeds(tmp_path: Path) -> None:
    channels = ["public:orderbook-BTCIRT", "public:trades-BTCIRT"]
    ws = FakeWS(
        [
            json.dumps({"id": 1, "connect": {"client": "c"}}),
            sub_ok(2, "e1", 10),
            sub_ok(3, "e2", 50),
            "{}",
            push("public:orderbook-BTCIRT", 11, {"asks": [["1", "2"]]})
            + "\n"
            + push("public:trades-BTCIRT", 51, {"price": "1"}),
        ]
    )
    now = [DAY_MS + 1000]
    recorder, state, writer = make(tmp_path, [ws], channels, now)
    with pytest.raises(ConnectionError):
        asyncio.run(recorder.run_once())
    writer.close()
    assert "{}" in ws.sent
    assert json.loads(ws.sent[1]) == {"subscribe": {"channel": channels[0]}, "id": 2}
    book = read_records(tmp_path / "raw" / "ws" / "orderbook" / "2026-11-17.jsonl.gz")
    assert [r.get("seed", False) for r in book] == [True, False]
    assert state.channels[channels[0]].offset == 11
    assert state.channels[channels[1]].messages == 1


def test_detects_offset_gaps(tmp_path: Path) -> None:
    state = StreamState()
    state.on_subscribed("c", {"epoch": "e", "offset": 5})
    state.on_publication("c", 6, 1)
    state.on_publication("c", 9, 2)
    assert state.channels["c"].gaps == 1
    assert state.channels["c"].lost == 2


def test_reconnect_requests_recovery_and_counts_unrecovered(tmp_path: Path) -> None:
    channel = "public:trades-BTCIRT"
    first = FakeWS([sub_ok(2, "e", 5), push(channel, 6, {})])
    second = FakeWS([sub_ok(2, "e", 9)])
    now = [DAY_MS]
    recorder, state, _ = make(tmp_path, [first, second], [channel], now)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            asyncio.run(recorder.run_once())
    sub = json.loads(second.sent[1])["subscribe"]
    assert sub == {"channel": channel, "recover": True, "epoch": "e", "offset": 6}
    assert state.channels[channel].gaps == 1


def test_recovered_publications_are_recorded(tmp_path: Path) -> None:
    channel = "public:trades-BTCIRT"
    first = FakeWS([sub_ok(2, "e", 5)])
    pubs = [{"offset": 6, "data": {"p": 1}}, {"offset": 7, "data": {"p": 2}}]
    second = FakeWS([sub_ok(2, "e", 7, recovered=True, publications=pubs)])
    recorder, state, _ = make(tmp_path, [first, second], [channel], [DAY_MS])
    for _ in range(2):
        with pytest.raises(ConnectionError):
            asyncio.run(recorder.run_once())
    assert state.channels[channel].gaps == 0
    assert state.channels[channel].messages == 2


def test_freshness_fails_closed() -> None:
    state = StreamState()
    assert not is_fresh(state, "public:orderbook-BTCIRT", DAY_MS)
    state.on_publication("public:orderbook-BTCIRT", 1, DAY_MS)
    assert is_fresh(state, "public:orderbook-BTCIRT", DAY_MS + 60_000)
    assert not is_fresh(state, "public:orderbook-BTCIRT", DAY_MS + 121_000)


def test_completeness_report(tmp_path: Path) -> None:
    writer = RawWriter(tmp_path)
    channel = "public:trades-BTCIRT"
    for offset, t in [(1, 0), (2, 1_000), (5, 3_601_000)]:
        writer.write(
            "trades", {"recv_ms": DAY_MS + t, "channel": channel, "offset": offset, "data": {}}
        )
    writer.close()
    [report] = completeness_report(tmp_path, "2026-11-17")
    assert report.messages == 3
    assert report.offset_gaps == 1
    assert report.lost == 2
    assert report.max_silence_s == 3600.0


def test_reader_tolerates_truncated_file(tmp_path: Path) -> None:
    writer = RawWriter(tmp_path)
    writer.write("trades", {"recv_ms": DAY_MS, "channel": "x", "offset": 1, "data": {}})
    writer.flush()
    path = tmp_path / "raw" / "ws" / "trades" / "2026-11-17.jsonl.gz"
    assert len(read_records(path)) == 1
    writer.close()
