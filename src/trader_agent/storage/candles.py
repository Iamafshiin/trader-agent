import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trader_agent.market_data.candles import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, resolution, open_time)
)
"""

STEP = {"15": 900, "60": 3600, "D": 86400}
TEHRAN_UTC_OFFSET = 12600


class CandleStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert(self, candles: "list[Candle]", fetched_at: int) -> int:
        rows = [
            (
                c.symbol,
                c.resolution,
                c.open_time,
                str(c.open),
                str(c.high),
                str(c.low),
                str(c.close),
                str(c.volume),
                fetched_at,
            )
            for c in candles
        ]
        before = self._conn.total_changes
        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        return self._conn.total_changes - before

    def open_times(self, symbol: str, resolution: str, start: int, end: int) -> list[int]:
        cur = self._conn.execute(
            "SELECT open_time FROM candles WHERE symbol=? AND resolution=? "
            "AND open_time>=? AND open_time<? ORDER BY open_time",
            (symbol, resolution, start, end),
        )
        return [row[0] for row in cur]

    def missing_count(self, symbol: str, resolution: str, start: int, end: int) -> int:
        step = STEP[resolution]
        first = start + (-(start + TEHRAN_UTC_OFFSET)) % step
        expected = set(range(first, end, step))
        return len(expected - set(self.open_times(symbol, resolution, start, end)))

    def count(self, symbol: str, resolution: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND resolution=?", (symbol, resolution)
        )
        result: int = cur.fetchone()[0]
        return result
