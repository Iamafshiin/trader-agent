import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

SYMBOLS = ("BTCIRT", "ETHIRT", "USDTIRT")
SERVICES = {
    "trader-streams.service": "ضبط داده زنده",
    "trader-paper.service": "معاملات کاغذی",
    "trader-candles.timer": "دریافت ساعتی کندل‌ها",
}
TEHRAN = timedelta(hours=3, minutes=30)
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
BOOK_STALE_S = 300
CANDLE_STALE_S = 1800
DISK_WARN = 0.80
BURNIN_DAYS = 7


def fa(value: object) -> str:
    return str(value).translate(FA_DIGITS)


def fa_num(value: int | float | Decimal) -> str:
    return fa(f"{value:,.0f}")


def tehran_clock(ms: int) -> str:
    return (datetime.fromtimestamp(ms / 1000, UTC) + TEHRAN).strftime("%Y-%m-%d %H:%M")


@dataclass
class Snapshot:
    now_ms: int
    streams: dict[str, Any] | None
    last_15m: dict[str, int | None]
    disk_total: int
    disk_used: int
    data_bytes: int
    services: dict[str, str]
    kill_switch: bool
    paper: dict[str, Any] | None
    burnin_start_ms: int | None


@dataclass
class Report:
    text: str
    state: dict[str, Any]
    problems: list[str] = field(default_factory=list)


def build_report(snap: Snapshot, prev: dict[str, Any]) -> Report:
    lines: list[str] = []
    problems: list[str] = []
    state: dict[str, Any] = {"at_ms": snap.now_ms, "burnin_notified": prev.get("burnin_notified")}
    span = ""
    if prev.get("at_ms"):
        minutes = max(1, round((snap.now_ms - prev["at_ms"]) / 60000))
        span = f" (در {fa(minutes)} دقیقه گذشته)"

    service_lines = []
    for unit, label in SERVICES.items():
        status = snap.services.get(unit, "unknown")
        if status == "active":
            service_lines.append(f"• {label}: ✅ فعال")
        elif unit == "trader-paper.service" and status in ("inactive", "unknown"):
            service_lines.append(f"• {label}: ⏸ هنوز شروع نشده")
        else:
            service_lines.append(f"• {label}: ❌ {status}")
            problems.append(f"سرویس «{label}» فعال نیست")
    if snap.services.get("trader-streams.service") != "active" and (
        snap.services.get("trader-paper.service") == "active"
    ):
        problems = [p for p in problems if "ضبط داده زنده" not in p]
        service_lines[0] = "• ضبط داده زنده: ✅ داخل سرویس معاملات کاغذی"

    data_lines = []
    channels: dict[str, Any] = (snap.streams or {}).get("channels", {})
    prev_counts: dict[str, Any] = prev.get("counts", {})
    counts: dict[str, Any] = {}
    gaps_now = lost_now = 0
    for ch, info in channels.items():
        counts[ch] = {"messages": info["messages"], "gaps": info["gaps"], "lost": info["lost"]}
    reconnects = (snap.streams or {}).get("reconnects", 0)
    reset = reconnects < prev.get("reconnects", 0)
    for sym in SYMBOLS:
        parts = []
        for kind, label in (("orderbook", "دفتر سفارش"), ("trades", "معامله")):
            ch = f"public:{kind}-{sym}"
            info = channels.get(ch)
            if info is None:
                parts.append(f"{label}: بدون داده")
                if kind == "orderbook":
                    problems.append(f"{sym}: داده دفتر سفارش نمی‌رسد")
                continue
            before = 0 if reset else prev_counts.get(ch, {}).get("messages", 0)
            delta = info["messages"] - before if info["messages"] >= before else info["messages"]
            parts.append(f"{label} {fa_num(delta)}")
            g = info["gaps"] - (0 if reset else prev_counts.get(ch, {}).get("gaps", 0))
            lo = info["lost"] - (0 if reset else prev_counts.get(ch, {}).get("lost", 0))
            gaps_now += max(g, 0)
            lost_now += max(lo, 0)
            last = info.get("last_recv_ms")
            if kind == "orderbook" and (last is None or snap.now_ms - last > BOOK_STALE_S * 1000):
                problems.append(f"{sym}: دفتر سفارش بیش از ۵ دقیقه به‌روز نشده")
        candle = snap.last_15m.get(sym)
        if candle is None:
            parts.append("کندل ۱۵ دقیقه: ندارد")
            problems.append(f"{sym}: کندل ۱۵ دقیقه‌ای ذخیره نشده")
        else:
            close_ms = (candle + 900) * 1000
            age_ok = snap.now_ms - close_ms <= CANDLE_STALE_S * 1000
            parts.append(
                f"آخرین کندل {fa(tehran_clock(candle * 1000)[11:])} {'✅' if age_ok else '⚠️'}"
            )
            if not age_ok:
                problems.append(f"{sym}: کندل‌ها عقب افتاده‌اند")
        data_lines.append(f"• {sym}: " + "، ".join(parts))
    state["counts"] = counts
    state["reconnects"] = reconnects
    new_reconnects = reconnects if reset else reconnects - prev.get("reconnects", 0)
    if gaps_now:
        problems.append(f"{fa(gaps_now)} گپ در استریم‌ها ({fa(lost_now)} پیام از دست رفته)")

    disk_ratio = snap.disk_used / snap.disk_total if snap.disk_total else 0.0
    if disk_ratio >= DISK_WARN:
        problems.append(f"دیسک {fa(round(disk_ratio * 100))}٪ پر شده")
    if snap.kill_switch:
        problems.append("کلید توقف اضطراری (kill switch) فعال است")

    header = f"📊 گزارش ساعتی ربات معامله‌گر — {fa(tehran_clock(snap.now_ms))} تهران"
    lines.append(header)
    if problems:
        lines.append(f"وضعیت کلی: ⚠️ {fa(len(problems))} مورد نیاز به توجه دارد")
        lines += [f"  - {p}" for p in problems]
    else:
        lines.append("وضعیت کلی: ✅ همه چیز عادی است")

    if snap.burnin_start_ms is not None:
        end_ms = snap.burnin_start_ms + BURNIN_DAYS * 86_400_000
        if snap.now_ms < end_ms:
            day = (snap.now_ms - snap.burnin_start_ms) // 86_400_000 + 1
            left_h = (end_ms - snap.now_ms) / 3_600_000
            lines.append(
                f"\n⏳ دوره ۷ روزه جمع‌آوری داده: روز {fa(day)} از ۷ "
                f"(حدود {fa(round(left_h))} ساعت مانده، پایان {fa(tehran_clock(end_ms))} تهران)"
            )
        else:
            lines.append("\n✅ دوره ۷ روزه جمع‌آوری داده تمام شده است.")
            if not prev.get("burnin_notified"):
                lines.append(
                    "🔔 یادآوری: حالا وقت شروع مطالعه ۳۰ روزه معاملات کاغذی است. "
                    "به Claude بگو گزارش‌ها را بررسی کند و trader-paper را روشن کند."
                )
                state["burnin_notified"] = snap.now_ms

    lines.append("\n🛠 سرویس‌ها:")
    lines += service_lines
    lines.append(f"\n📡 داده دریافتی{span}:")
    lines += data_lines
    lines.append(f"اتصال مجدد: {fa(max(new_reconnects, 0))} | گپ: {fa(gaps_now)}")

    if snap.paper is not None:
        p = snap.paper
        lines.append("\n💼 معاملات کاغذی (مطالعه):")
        lines.append(
            f"• ارزش حساب: {fa_num(p['equity'])} ریال "
            f"({'+' if p['change_pct'] >= 0 else ''}{fa(f'{p["change_pct"]:.2f}')}٪ از شروع)"
        )
        lines.append(f"• معاملات این ساعت: {fa(p['trades_recent'])} | کل: {fa(p['trades_total'])}")
        if p["positions"]:
            lines.append("• پوزیشن باز: " + "، ".join(p["positions"]))
        else:
            lines.append("• پوزیشن باز: ندارد")
        if p.get("halt"):
            lines.append(f"• ⛔ توقف ریسک: {p['halt']}")
        for t in p.get("recent", []):
            lines.append(f"  - {t}")

    used_gb = fa(f"{snap.disk_used / 1e9:.1f}")
    total_gb = fa(f"{snap.disk_total / 1e9:.1f}")
    data_mb = fa(f"{snap.data_bytes / 1e6:.0f}")
    lines.append(
        f"\n💾 دیسک: {used_gb} از {total_gb} گیگ "
        f"({fa(round(disk_ratio * 100))}٪) | حجم داده‌ها: {data_mb} مگ"
    )
    return Report("\n".join(lines), state, problems)


def _service_states() -> dict[str, str]:
    out: dict[str, str] = {}
    for unit in SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
            )
            out[unit] = r.stdout.strip() or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            out[unit] = "unknown"
    return out


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def _paper(db: Path, run_id: str, now_ms: int, since_ms: int) -> dict[str, Any] | None:
    if not db.exists():
        return None
    conn = sqlite3.connect(db)
    try:
        run = conn.execute("SELECT config FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            return None
        start = Decimal(json.loads(run[0])["starting_balance_rls"])
        eq = conn.execute(
            "SELECT equity FROM equity WHERE run_id=? ORDER BY at_ms DESC LIMIT 1", (run_id,)
        ).fetchone()
        equity = Decimal(eq[0]) if eq else start
        trades = conn.execute(
            "SELECT at_ms, symbol, side, amount, price, reason FROM trades WHERE run_id=? "
            "ORDER BY at_ms",
            (run_id,),
        ).fetchall()
        recent = [t for t in trades if t[0] > since_ms]
        acct = conn.execute("SELECT body FROM accounts WHERE run_id=?", (run_id,)).fetchone()
        positions: list[str] = []
        if acct:
            body = json.loads(acct[0])
            for asset, qty in body["holdings"].items():
                if Decimal(qty) > 0:
                    stop = body["stops"].get(f"{asset}IRT", {}).get("stop")
                    positions.append(
                        f"{asset} {qty}" + (f" (حد ضرر {fa_num(Decimal(stop))})" if stop else "")
                    )
        risk = conn.execute("SELECT body FROM risk_state WHERE run_id=?", (run_id,)).fetchone()
        halt = json.loads(risk[0]).get("halt_reason") if risk else None
        side_fa = {"buy": "خرید", "sell": "فروش"}
        return {
            "equity": equity,
            "change_pct": float((equity - start) / start * 100),
            "trades_recent": len(recent),
            "trades_total": len(trades),
            "positions": positions,
            "halt": halt,
            "recent": [
                f"{side_fa.get(s, s)} {sym} {amt} به قیمت {fa_num(Decimal(px))} ({reason})"
                for _, sym, s, amt, px, reason in recent[-5:]
            ],
        }
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def gather(root: Path, now_ms: int, prev: dict[str, Any], burnin_start_ms: int | None) -> Snapshot:
    streams_path = root / "state" / "streams.json"
    streams = json.loads(streams_path.read_text("utf-8")) if streams_path.exists() else None
    last_15m: dict[str, int | None] = {s: None for s in SYMBOLS}
    candles = root / "db" / "candles.sqlite3"
    if candles.exists():
        conn = sqlite3.connect(candles)
        for s in SYMBOLS:
            row = conn.execute(
                "SELECT MAX(open_time) FROM candles WHERE symbol=? AND resolution='15'", (s,)
            ).fetchone()
            last_15m[s] = row[0] if row else None
        conn.close()
    usage = shutil.disk_usage(root)
    since = prev.get("at_ms") or now_ms - 3_600_000
    return Snapshot(
        now_ms=now_ms,
        streams=streams,
        last_15m=last_15m,
        disk_total=usage.total,
        disk_used=usage.used,
        data_bytes=_dir_size(root),
        services=_service_states(),
        kill_switch=(root / "HALT").exists(),
        paper=_paper(root / "db" / "paper.sqlite3", "study", now_ms, since),
        burnin_start_ms=burnin_start_ms,
    )


def load_state(path: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)
