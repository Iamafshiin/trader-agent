import gzip
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from trader_agent.market_data.candles import (
    CandleCollector,
    CandleSourceError,
    RawLog,
    parse_udf,
    request_windows,
)
from trader_agent.storage.candles import CandleStore

NOW = 1_794_906_000


def udf(times: list[int]) -> dict[str, Any]:
    n = len(times)
    return {
        "s": "ok",
        "t": times,
        "o": [100.0] * n,
        "h": [110.0] * n,
        "l": [90.0] * n,
        "c": [105.5] * n,
        "v": [0.06929091] * n,
    }


def test_parse_keeps_exact_decimals() -> None:
    payload = json.loads(json.dumps(udf([900])), parse_float=Decimal)
    [candle] = parse_udf("BTCIRT", "15", payload)
    assert candle.volume == Decimal("0.06929091")
    assert candle.close == Decimal("105.5")


def test_parse_no_data_is_empty() -> None:
    assert parse_udf("BTCIRT", "15", {"s": "no_data"}) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"s": "error", "errmsg": "bad symbol"},
        {**udf([900, 1800]), "c": [1.0]},
        udf([901]),
        udf([1800, 900]),
        {**udf([900]), "h": [80.0]},
        {**udf([900]), "v": [-1.0]},
    ],
)
def test_parse_rejects_bad_payloads(payload: dict[str, Any]) -> None:
    with pytest.raises(CandleSourceError):
        parse_udf("BTCIRT", "15", payload)


def test_request_windows_respect_cap() -> None:
    windows = list(request_windows(0, 900 * 768, "15"))
    assert windows == [(0, 900 * 500), (900 * 500, 900 * 768)]


class FakeNobitex:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        lo, hi = int(params["from"]), int(params["to"])
        step = 900
        times = list(range(lo + (-lo) % step, hi + 1, step))
        times = [t for t in times if t != lo + 3 * step]
        return httpx.Response(200, json=udf(times))


def make_collector(tmp_path: Path, fake: FakeNobitex) -> tuple[CandleCollector, CandleStore]:
    client = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(fake))
    store = CandleStore(tmp_path / "db" / "candles.sqlite3")
    sleeps: list[float] = []
    collector = CandleCollector(
        client, store, RawLog(tmp_path), clock=lambda: NOW, sleep=sleeps.append
    )
    return collector, store


def test_collect_is_idempotent_and_reports_gaps(tmp_path: Path) -> None:
    fake = FakeNobitex()
    collector, store = make_collector(tmp_path, fake)
    first = collector.collect("BTCIRT", "15", days=1)
    assert first.inserted == first.received == 95
    assert first.missing == 1
    second = collector.collect("BTCIRT", "15", days=1)
    assert second.inserted == 0
    assert store.count("BTCIRT", "15") == 95


def test_collect_excludes_open_candle(tmp_path: Path) -> None:
    fake = FakeNobitex()
    collector, store = make_collector(tmp_path, fake)
    collector.collect("BTCIRT", "15", days=1)
    end = NOW - NOW % 900
    assert max(store.open_times("BTCIRT", "15", 0, NOW + 900)) == end - 900


def test_collect_writes_raw_log(tmp_path: Path) -> None:
    fake = FakeNobitex()
    collector, _ = make_collector(tmp_path, fake)
    collector.collect("BTCIRT", "15", days=1)
    [log] = list((tmp_path / "raw" / "udf_history").glob("*.jsonl.gz"))
    with gzip.open(log, "rt", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh]
    assert records[0]["params"]["symbol"] == "BTCIRT"
    assert records[0]["status"] == 200


def test_collect_sends_requested_range(tmp_path: Path) -> None:
    fake = FakeNobitex()
    collector, _ = make_collector(tmp_path, fake)
    collector.collect("ETHIRT", "15", days=8)
    assert len(fake.calls) == 2
    assert {c["symbol"] for c in fake.calls} == {"ETHIRT"}
    assert {c["resolution"] for c in fake.calls} == {"15"}


def test_hourly_candles_align_to_tehran_time() -> None:
    payload = udf([1_794_213_000])
    [candle] = parse_udf("BTCIRT", "60", payload)
    assert candle.open_time == 1_794_213_000
    with pytest.raises(CandleSourceError):
        parse_udf("BTCIRT", "60", udf([1_794_214_800]))


def test_missing_count_uses_tehran_hour_grid(tmp_path: Path) -> None:
    store = CandleStore(tmp_path / "c.sqlite3")
    start = 1_794_213_000
    candles = parse_udf("BTCIRT", "60", udf([start, start + 3600]))
    store.insert(candles, fetched_at=start)
    assert store.missing_count("BTCIRT", "60", start - 1800, start + 3 * 3600) == 1
