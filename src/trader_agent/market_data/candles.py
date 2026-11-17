import gzip
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from trader_agent.storage.candles import TEHRAN_UTC_OFFSET, CandleStore

RESOLUTION_SECONDS: dict[str, int] = {"15": 900, "60": 3600, "D": 86400}
MAX_CANDLES_PER_REQUEST = 500
DEFAULT_SYMBOLS = ("BTCIRT", "ETHIRT", "USDTIRT")
DEFAULT_RESOLUTIONS = ("15", "60", "D")


class CandleSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candle:
    symbol: str
    resolution: str
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class CollectResult:
    symbol: str
    resolution: str
    received: int
    inserted: int
    missing: int


def parse_udf(symbol: str, resolution: str, payload: dict[str, Any]) -> list[Candle]:
    status = payload.get("s")
    if status == "no_data":
        return []
    if status != "ok":
        raise CandleSourceError(f"{symbol}/{resolution}: {payload.get('errmsg', status)}")
    keys = ("t", "o", "h", "l", "c", "v")
    columns = [payload.get(k) for k in keys]
    if not all(isinstance(c, list) for c in columns):
        raise CandleSourceError(f"{symbol}/{resolution}: missing columns")
    lengths = {len(c) for c in columns if isinstance(c, list)}
    if len(lengths) != 1:
        raise CandleSourceError(f"{symbol}/{resolution}: column lengths differ")
    step = RESOLUTION_SECONDS[resolution]
    candles: list[Candle] = []
    for t, o, h, low, c, v in zip(*columns, strict=True):
        open_time = int(t)
        if resolution != "D" and (open_time + TEHRAN_UTC_OFFSET) % step:
            raise CandleSourceError(f"{symbol}/{resolution}: misaligned time {open_time}")
        candle = Candle(
            symbol, resolution, open_time, *(Decimal(str(x)) for x in (o, h, low, c, v))
        )
        if not (
            candle.low
            <= min(candle.open, candle.close)
            <= max(candle.open, candle.close)
            <= candle.high
        ):
            raise CandleSourceError(f"{symbol}/{resolution}: inconsistent OHLC at {open_time}")
        if candle.volume < 0:
            raise CandleSourceError(f"{symbol}/{resolution}: negative volume at {open_time}")
        candles.append(candle)
    times = [c.open_time for c in candles]
    if times != sorted(set(times)):
        raise CandleSourceError(f"{symbol}/{resolution}: times not strictly increasing")
    return candles


def request_windows(start: int, end: int, resolution: str) -> Iterator[tuple[int, int]]:
    span = RESOLUTION_SECONDS[resolution] * MAX_CANDLES_PER_REQUEST
    cursor = start
    while cursor < end:
        upper = min(cursor + span, end)
        yield cursor, upper
        cursor = upper


class RawLog:
    def __init__(self, root: Path) -> None:
        self._root = root

    def append(self, record: dict[str, Any]) -> None:
        day = datetime.fromtimestamp(record["fetched_at"], UTC).strftime("%Y-%m-%d")
        path = self._root / "raw" / "udf_history" / f"{day}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")


class CandleCollector:
    def __init__(
        self,
        client: httpx.Client,
        store: CandleStore,
        raw_log: RawLog,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 1.1,
    ) -> None:
        self._client = client
        self._store = store
        self._raw = raw_log
        self._clock = clock
        self._sleep = sleep
        self._min_interval = min_interval
        self._last_request: float | None = None

    def _fetch(self, symbol: str, resolution: str, start: int, end: int) -> list[Candle]:
        if self._last_request is not None:
            wait = self._min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        params: dict[str, str | int] = {
            "symbol": symbol,
            "resolution": resolution,
            "from": start,
            "to": end,
        }
        self._last_request = self._clock()
        response = self._client.get("/market/udf/history", params=params)
        response.raise_for_status()
        text = response.text
        self._raw.append(
            {
                "fetched_at": int(self._clock()),
                "params": params,
                "status": response.status_code,
                "body": text,
            }
        )
        return parse_udf(symbol, resolution, json.loads(text, parse_float=Decimal))

    def collect(self, symbol: str, resolution: str, days: float) -> CollectResult:
        step = RESOLUTION_SECONDS[resolution]
        now = int(self._clock())
        end = now - now % step
        start = end - int(days * 86400)
        candles: list[Candle] = []
        for lo, hi in request_windows(start, end, resolution):
            candles.extend(self._fetch(symbol, resolution, lo, hi))
        closed = {c.open_time: c for c in candles if c.open_time + step <= now}
        inserted = self._store.insert(list(closed.values()), fetched_at=now)
        missing = (
            self._store.missing_count(symbol, resolution, start, end) if resolution != "D" else 0
        )
        return CollectResult(symbol, resolution, len(closed), inserted, missing)
