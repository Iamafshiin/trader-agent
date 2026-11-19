import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader_agent.storage.candles import STEP, TEHRAN_UTC_OFFSET
from trader_agent.strategy.indicators import ema
from trader_agent.strategy.tcp_vp import Params
from trader_agent.strategy.volume_profile import build_profile

BURNIN_DAYS = 7
MAX_CANDLES = 1000
DAY_S = 86_400
SIGNAL_LAG_MS = 30_000


@contextmanager
def open_ro(path: Path) -> Iterator[sqlite3.Connection | None]:
    if not path.exists():
        yield None
        return
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=1")
        yield conn
    finally:
        conn.close()


def now_ms() -> int:
    return int(time.time() * 1000)


class Reader:
    def __init__(self, root: Path, params: Params, burnin_start_ms: int | None) -> None:
        self.root = root
        self.params = params
        self.burnin_start_ms = burnin_start_ms
        self.candles_db = root / "db" / "candles.sqlite3"
        self.paper_db = root / "db" / "paper.sqlite3"
        self.streams_file = root / "state" / "streams.json"
        self.kill_file = root / "HALT"

    def symbols(self) -> list[str]:
        return list(self.params.symbols)

    def latest_run(self, conn: sqlite3.Connection) -> str | None:
        try:
            row = conn.execute(
                "SELECT run_id FROM runs ORDER BY started_ms DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
        return str(row[0]) if row else None

    def overview(self, at_ms: int) -> dict[str, Any]:
        burn: dict[str, Any] | None = None
        if self.burnin_start_ms is not None:
            total = BURNIN_DAYS * DAY_S * 1000
            elapsed = max(0, at_ms - self.burnin_start_ms)
            burn = {
                "start_ms": self.burnin_start_ms,
                "end_ms": self.burnin_start_ms + total,
                "days": BURNIN_DAYS,
                "progress": min(1.0, elapsed / total),
                "done": elapsed >= total,
            }
        return {
            "now_ms": at_ms,
            "symbols": self.symbols(),
            "version": self.params.version,
            "config_hash": self.params.config_hash[:12],
            "kill_switch": self.kill_file.exists(),
            "burnin": burn,
        }

    def streams(self, at_ms: int) -> dict[str, Any]:
        try:
            raw = json.loads(self.streams_file.read_text("utf-8"))
        except (OSError, ValueError):
            return {"available": False, "channels": [], "reconnects": 0, "updated_ms": None}
        rows = []
        for name, ch in sorted(raw.get("channels", {}).items()):
            last = ch.get("last_recv_ms")
            rows.append(
                {
                    "channel": name,
                    "messages": ch.get("messages", 0),
                    "gaps": ch.get("gaps", 0),
                    "lost": ch.get("lost", 0),
                    "last_recv_ms": last,
                    "age_s": None if last is None else max(0, (at_ms - last) // 1000),
                }
            )
        return {
            "available": True,
            "channels": rows,
            "reconnects": raw.get("reconnects", 0),
            "updated_ms": raw.get("at_ms"),
        }

    def candles(self, symbol: str, resolution: str, limit: int) -> dict[str, Any]:
        limit = max(1, min(limit, MAX_CANDLES))
        rows: list[Any] = []
        with open_ro(self.candles_db) as conn:
            if conn is not None:
                rows = conn.execute(
                    "SELECT open_time, open, high, low, close, volume FROM candles "
                    "WHERE symbol=? AND resolution=? ORDER BY open_time DESC LIMIT ?",
                    (symbol, resolution, limit + self.params.ema_slow),
                ).fetchall()[::-1]
        closes = [Decimal(r[4]) for r in rows]
        fast = ema(closes, self.params.ema_fast)
        slow = ema(closes, self.params.ema_slow)
        offset = max(0, len(rows) - limit)

        def line(series: list[Decimal | None]) -> list[dict[str, Any]]:
            return [
                {"time": rows[offset + i][0], "value": float(v)}
                for i, v in enumerate(series[offset:])
                if v is not None
            ]

        candles = [
            {
                "time": t,
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "volume": float(v),
            }
            for t, o, h, lo, c, v in rows[offset:]
        ]
        return {
            "symbol": symbol,
            "resolution": resolution,
            "candles": candles,
            "ema_fast": {"period": self.params.ema_fast, "data": line(fast)},
            "ema_slow": {"period": self.params.ema_slow, "data": line(slow)},
            "profile": self.profile(symbol),
            "markers": self.markers(symbol, resolution, candles[0]["time"] if candles else 0),
        }

    def profile(self, symbol: str) -> dict[str, Any] | None:
        with open_ro(self.candles_db) as conn:
            if conn is None:
                return None
            rows = conn.execute(
                "SELECT high, low, close, volume FROM candles WHERE symbol=? AND resolution='15' "
                "ORDER BY open_time DESC LIMIT 96",
                (symbol,),
            ).fetchall()
        if not rows:
            return None
        trades = [((Decimal(h) + Decimal(lo) + Decimal(c)) / 3, Decimal(v)) for h, lo, c, v in rows]
        prof = build_profile(
            trades,
            Decimal(rows[0][2]),
            self.params.profile_row_fraction,
            self.params.value_area_share,
        )
        if prof is None:
            return None
        return {
            "poc": float(prof.poc),
            "vah": float(prof.vah),
            "val": float(prof.val),
            "volume": float(prof.total_volume),
            "source": "15m candles, last 24h",
        }

    def markers(self, symbol: str, resolution: str, since_s: int) -> list[dict[str, Any]]:
        step = STEP[resolution]
        out: list[dict[str, Any]] = []
        with open_ro(self.paper_db) as conn:
            if conn is None:
                return out
            run = self.latest_run(conn)
            if run is None:
                return out
            rows = conn.execute(
                "SELECT at_ms, body FROM decisions WHERE run_id=? AND symbol=? AND at_ms>=? "
                "ORDER BY at_ms",
                (run, symbol, since_s * 1000),
            ).fetchall()
        for at_ms, body in rows:
            sig = json.loads(body).get("signal")
            if not sig:
                continue
            at = (at_ms - SIGNAL_LAG_MS) // 1000
            time_s = (at + TEHRAN_UTC_OFFSET) // step * step - TEHRAN_UTC_OFFSET
            out.append({"time": time_s, "type": sig.get("type", "?")})
        return out

    def paper(self, run_id: str | None) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "available": False,
            "kill_switch": self.kill_file.exists(),
            "halt_reason": None,
        }
        with open_ro(self.paper_db) as conn:
            if conn is None:
                return empty
            run = run_id or self.latest_run(conn)
            if run is None:
                return empty
            cfg = conn.execute("SELECT config FROM runs WHERE run_id=?", (run,)).fetchone()
            if cfg is None:
                return empty
            start = Decimal(json.loads(cfg[0])["starting_balance_rls"])
            equity = conn.execute(
                "SELECT at_ms, equity FROM equity WHERE run_id=? ORDER BY at_ms", (run,)
            ).fetchall()
            trades = conn.execute(
                "SELECT at_ms, symbol, side, kind, amount, price, fee, reason FROM trades "
                "WHERE run_id=? ORDER BY at_ms DESC LIMIT 50",
                (run,),
            ).fetchall()
            acct = conn.execute("SELECT body FROM accounts WHERE run_id=?", (run,)).fetchone()
            risk = conn.execute("SELECT body FROM risk_state WHERE run_id=?", (run,)).fetchone()
        last_equity = Decimal(equity[-1][1]) if equity else start
        riskbody = json.loads(risk[0]) if risk else {}
        account: dict[str, Any] = (
            json.loads(acct[0]) if acct else {"cash": str(start), "holdings": {}, "stops": {}}
        )
        return {
            "available": True,
            "run_id": run,
            "start_balance": float(start),
            "equity": float(last_equity),
            "change_pct": float((last_equity - start) / start * 100),
            "cash": float(Decimal(account["cash"])),
            "kill_switch": self.kill_file.exists(),
            "halt_reason": riskbody.get("halt_reason"),
            "high_water": riskbody.get("high_water"),
            "start_of_day": riskbody.get("start_of_day"),
            "risk_day": riskbody.get("day"),
            "curve": [{"time": t // 1000, "value": float(Decimal(e))} for t, e in equity],
            "positions": self.positions(account),
            "trades": [
                {
                    "at_ms": t,
                    "symbol": s,
                    "side": side,
                    "kind": k,
                    "amount": a,
                    "price": p,
                    "fee": f,
                    "reason": r,
                }
                for t, s, side, k, a, p, f, r in trades
            ],
        }

    def positions(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with open_ro(self.candles_db) as conn:
            for asset, qty in account.get("holdings", {}).items():
                amount = Decimal(qty)
                if amount <= 0:
                    continue
                symbol = f"{asset}IRT"
                mark: Decimal | None = None
                if conn is not None:
                    row = conn.execute(
                        "SELECT close FROM candles WHERE symbol=? AND resolution='15' "
                        "ORDER BY open_time DESC LIMIT 1",
                        (symbol,),
                    ).fetchone()
                    mark = Decimal(row[0]) if row else None
                stop = account.get("stops", {}).get(symbol, {}).get("stop")
                out.append(
                    {
                        "symbol": symbol,
                        "amount": str(amount),
                        "stop": stop,
                        "mark": None if mark is None else float(mark),
                        "value": None if mark is None else float(mark * amount),
                    }
                )
        return out

    def decisions(self, run_id: str | None, limit: int) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        with open_ro(self.paper_db) as conn:
            if conn is None:
                return {"available": False, "decisions": []}
            run = run_id or self.latest_run(conn)
            if run is None:
                return {"available": False, "decisions": []}
            rows = conn.execute(
                "SELECT at_ms, symbol, body FROM decisions WHERE run_id=? "
                "ORDER BY at_ms DESC LIMIT ?",
                (run, limit),
            ).fetchall()
        out = []
        for at_ms, symbol, body in rows:
            d = json.loads(body)
            out.append(
                {
                    "at_ms": at_ms,
                    "symbol": symbol,
                    "data_ok": d.get("data_ok"),
                    "signal": d.get("signal"),
                    "action": d.get("action"),
                    "proposal": d.get("proposal"),
                    "critic": d.get("critic"),
                }
            )
        return {"available": True, "run_id": run, "decisions": out}
