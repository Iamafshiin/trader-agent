import asyncio
import gzip
import json
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

import httpx

WS_URL = "wss://ws.nobitex.ir/connection/websocket"
STREAM_KINDS = ("orderbook", "trades", "candle")


def channels_for(symbols: Iterable[str]) -> list[str]:
    out: list[str] = []
    for s in symbols:
        out += [f"public:orderbook-{s}", f"public:trades-{s}", f"public:candle-{s}-15"]
    return out


def kind_of(channel: str) -> str:
    name = channel.removeprefix("public:")
    return name.split("-", 1)[0]


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


class RawWriter:
    def __init__(self, root: Path) -> None:
        self._root = root / "raw" / "ws"
        self._files: dict[tuple[str, str], IO[str]] = {}

    def write(self, kind: str, record: dict[str, Any]) -> None:
        key = (kind, day_of(record["recv_ms"]))
        fh = self._files.get(key)
        if fh is None:
            for old in [k for k in self._files if k[0] == kind]:
                self._files.pop(old).close()
            path = self._root / kind / f"{key[1]}.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = gzip.open(path, "at", encoding="utf-8")
            self._files[key] = fh
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")

    def flush(self) -> None:
        for fh in self._files.values():
            fh.flush()

    def close(self) -> None:
        for fh in self._files.values():
            fh.close()
        self._files.clear()


@dataclass
class ChannelState:
    epoch: str | None = None
    offset: int | None = None
    last_recv_ms: int | None = None
    messages: int = 0
    gaps: int = 0
    lost: int = 0


@dataclass
class StreamState:
    channels: dict[str, ChannelState] = field(default_factory=dict)
    reconnects: int = 0

    def channel(self, name: str) -> ChannelState:
        return self.channels.setdefault(name, ChannelState())

    def on_subscribed(self, name: str, result: dict[str, Any]) -> None:
        ch = self.channel(name)
        if ch.offset is not None and not result.get("recovered", False):
            ch.gaps += 1
        if not result.get("recovered", False):
            ch.epoch = result.get("epoch")
            ch.offset = result.get("offset")

    def on_publication(self, name: str, offset: int | None, recv_ms: int) -> None:
        ch = self.channel(name)
        if offset is not None and ch.offset is not None and offset > ch.offset + 1:
            ch.gaps += 1
            ch.lost += offset - ch.offset - 1
        if offset is not None and (ch.offset is None or offset > ch.offset):
            ch.offset = offset
        ch.last_recv_ms = recv_ms
        ch.messages += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "reconnects": self.reconnects,
            "channels": {k: vars(v).copy() for k, v in self.channels.items()},
        }


@dataclass(frozen=True)
class FreshnessBounds:
    orderbook_s: float = 120.0
    trades_s: float = 900.0
    candle_grace_s: float = 60.0


def is_fresh(
    state: StreamState, channel: str, now_ms: int, bounds: FreshnessBounds = FreshnessBounds()
) -> bool:
    ch = state.channels.get(channel)
    if ch is None or ch.last_recv_ms is None:
        return False
    age = (now_ms - ch.last_recv_ms) / 1000
    kind = kind_of(channel)
    if kind == "orderbook":
        return age <= bounds.orderbook_s
    if kind == "trades":
        return age <= bounds.trades_s
    return age <= 900 + bounds.candle_grace_s


class WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


Connector = Callable[[], AbstractAsyncContextManager[Any]]


class StreamRecorder:
    def __init__(
        self,
        connect: Connector,
        channels: list[str],
        writer: RawWriter,
        state: StreamState,
        seed: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        state_path: Path | None = None,
        on_message: Callable[[str, Any, int], None] | None = None,
    ) -> None:
        self._on_message = on_message
        self._connect = connect
        self._channels = channels
        self._writer = writer
        self._state = state
        self._seed = seed
        self._clock_ms = clock_ms
        self._state_path = state_path
        self._pending: dict[int, str] = {}
        self._last_persist = 0

    def _subscribe_frames(self) -> list[str]:
        frames = [json.dumps({"connect": {"name": "trader-agent"}, "id": 1})]
        self._pending.clear()
        for i, name in enumerate(self._channels, start=2):
            sub: dict[str, Any] = {"channel": name}
            ch = self._state.channels.get(name)
            if ch and ch.epoch is not None and ch.offset is not None:
                sub.update(recover=True, epoch=ch.epoch, offset=ch.offset)
            self._pending[i] = name
            frames.append(json.dumps({"subscribe": sub, "id": i}))
        return frames

    async def handle(self, ws: WebSocketLike, raw: str | bytes) -> None:
        text = raw.decode() if isinstance(raw, bytes) else raw
        now = self._clock_ms()
        for line in text.splitlines():
            if not line.strip():
                continue
            msg = json.loads(line)
            if msg == {}:
                await ws.send("{}")
                continue
            if "id" in msg and msg["id"] in self._pending and "subscribe" in msg:
                name = self._pending.pop(msg["id"])
                result = msg["subscribe"]
                self._state.on_subscribed(name, result)
                for pub in result.get("publications", []) or []:
                    self._record(name, pub, now)
                await self._seed_book(name, now)
                continue
            if "error" in msg:
                raise ConnectionError(f"server error: {msg['error']}")
            push = msg.get("push")
            if push and "pub" in push:
                self._record(push["channel"], push["pub"], now)
        if now - self._last_persist >= 10_000:
            self._persist(now)

    def _record(self, channel: str, pub: dict[str, Any], now: int) -> None:
        offset = pub.get("offset")
        self._state.on_publication(channel, offset, now)
        self._writer.write(
            kind_of(channel),
            {"recv_ms": now, "channel": channel, "offset": offset, "data": pub.get("data")},
        )
        if self._on_message is not None:
            self._on_message(channel, pub.get("data"), now)

    async def _seed_book(self, channel: str, now: int) -> None:
        if self._seed is None or kind_of(channel) != "orderbook":
            return
        symbol = channel.removeprefix("public:orderbook-")
        data = await self._seed(symbol)
        if data is not None:
            self._writer.write(
                "orderbook",
                {"recv_ms": now, "channel": channel, "offset": None, "seed": True, "data": data},
            )
            if self._on_message is not None:
                self._on_message(channel, data, now)

    def _persist(self, now: int) -> None:
        self._last_persist = now
        self._writer.flush()
        if self._state_path is not None:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"at_ms": now, **self._state.snapshot()}), encoding="utf-8")
            tmp.replace(self._state_path)

    async def run_once(self, recv_timeout: float = 60.0) -> None:
        async with self._connect() as ws:
            for frame in self._subscribe_frames():
                await ws.send(frame)
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                await self.handle(ws, raw)

    async def run_forever(
        self,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        stop: asyncio.Event | None = None,
    ) -> None:
        delay = 1.0
        while stop is None or not stop.is_set():
            started = time.monotonic()
            try:
                await self.run_once()
            except (OSError, ConnectionError, TimeoutError, ValueError) as exc:
                print(f"stream disconnected: {type(exc).__name__}: {exc}", flush=True)
            except Exception as exc:
                if type(exc).__module__.startswith("websockets"):
                    print(f"stream disconnected: {type(exc).__name__}: {exc}", flush=True)
                else:
                    raise
            self._state.reconnects += 1
            self._persist(self._clock_ms())
            if time.monotonic() - started > 60:
                delay = 1.0
            await sleep(delay + random.uniform(0, delay / 2))
            delay = min(delay * 2, 60.0)


def make_seeder(client: httpx.AsyncClient) -> Callable[[str], Awaitable[dict[str, Any] | None]]:
    async def seed(symbol: str) -> dict[str, Any] | None:
        try:
            response = await client.get(f"/v3/orderbook/{symbol}")
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
        except httpx.HTTPError:
            return None

    return seed


def read_records(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    except EOFError:
        pass
    return out


@dataclass(frozen=True)
class ChannelReport:
    channel: str
    messages: int
    offset_gaps: int
    lost: int
    max_silence_s: float
    first_ms: int | None
    last_ms: int | None


def completeness_report(root: Path, day: str) -> list[ChannelReport]:
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for kind in STREAM_KINDS:
        path = root / "raw" / "ws" / kind / f"{day}.jsonl.gz"
        if not path.exists():
            continue
        for rec in read_records(path):
            if rec.get("seed"):
                continue
            by_channel.setdefault(rec["channel"], []).append(rec)
    day_start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    day_end = day_start + 86_400_000
    reports: list[ChannelReport] = []
    for channel, recs in sorted(by_channel.items()):
        times = [r["recv_ms"] for r in recs]
        edges = [day_start, *times, min(day_end, max(times))]
        silence = max(b - a for a, b in zip(edges, edges[1:], strict=False)) / 1000
        gaps = lost = 0
        prev: int | None = None
        for r in recs:
            off = r.get("offset")
            if off is None:
                continue
            if prev is not None and off > prev + 1:
                gaps += 1
                lost += off - prev - 1
            prev = off if prev is None else max(prev, off)
        reports.append(
            ChannelReport(channel, len(recs), gaps, lost, silence, min(times), max(times))
        )
    return reports
