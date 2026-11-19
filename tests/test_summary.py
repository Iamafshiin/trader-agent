from decimal import Decimal
from pathlib import Path
from typing import Any

from trader_agent.ops.summary import Snapshot, build_report, fa, load_state, save_state

NOW = 1_795_000_000_000
START = NOW - 2 * 86_400_000 - 3_600_000
ACTIVE = {
    "trader-streams.service": "active",
    "trader-paper.service": "inactive",
    "trader-candles.timer": "active",
}


def streams(
    messages: int, gaps: int = 0, last_ms: int = NOW, reconnects: int = 0
) -> dict[str, Any]:
    channels = {}
    for sym in ("BTCIRT", "ETHIRT", "USDTIRT"):
        for kind in ("orderbook", "trades"):
            channels[f"public:{kind}-{sym}"] = {
                "messages": messages,
                "gaps": gaps,
                "lost": gaps * 2,
                "last_recv_ms": last_ms,
            }
    return {"reconnects": reconnects, "channels": channels}


def snap(**over: Any) -> Snapshot:
    base: dict[str, Any] = {
        "now_ms": NOW,
        "streams": streams(500),
        "last_15m": {s: NOW // 1000 // 900 * 900 - 900 for s in ("BTCIRT", "ETHIRT", "USDTIRT")},
        "disk_total": 18_000_000_000,
        "disk_used": 4_000_000_000,
        "data_bytes": 50_000_000,
        "services": dict(ACTIVE),
        "kill_switch": False,
        "paper": None,
        "burnin_start_ms": START,
    }
    base.update(over)
    return Snapshot(**base)


def lagged(minutes: int) -> dict[str, int]:
    close = NOW // 1000 - minutes * 60
    return {s: close - 900 for s in ("BTCIRT", "ETHIRT", "USDTIRT")}


def test_hourly_candle_fetch_lag_is_not_a_problem() -> None:
    assert build_report(snap(last_15m=lagged(75)), {}).problems == []


def test_candles_older_than_one_missed_fetch_are_flagged() -> None:
    problems = build_report(snap(last_15m=lagged(95)), {}).problems
    assert len([p for p in problems if "کندل‌ها عقب افتاده‌اند" in p]) == 3


def test_persian_digits() -> None:
    assert fa("2026-11-19 12:30") == "۲۰۲۶-۱۱-۱۹ ۱۲:۳۰"


def test_healthy_report_shows_burnin_day_and_deltas() -> None:
    prev = {"at_ms": NOW - 3_600_000, "counts": streams(200)["channels"], "reconnects": 0}
    r = build_report(snap(), prev)
    assert r.problems == []
    assert "همه چیز عادی" in r.text
    assert "روز ۳ از ۷" in r.text
    assert "دفتر سفارش ۳۰۰" in r.text
    assert "در ۶۰ دقیقه گذشته" in r.text
    assert "هنوز شروع نشده" in r.text


def test_problems_are_listed() -> None:
    r = build_report(
        snap(
            streams=streams(500, gaps=1, last_ms=NOW - 600_000),
            services={**ACTIVE, "trader-streams.service": "failed"},
            disk_used=16_000_000_000,
            kill_switch=True,
            last_15m={"BTCIRT": None, "ETHIRT": None, "USDTIRT": None},
        ),
        {},
    )
    text = "\n".join(r.problems)
    assert "ضبط داده زنده" in text
    assert "دفتر سفارش بیش از ۵ دقیقه" in text
    assert "گپ" in text
    assert "دیسک" in text
    assert "kill switch" in text
    assert "کندل ۱۵ دقیقه‌ای ذخیره نشده" in text
    assert "نیاز به توجه" in r.text


def test_burnin_reminder_sent_once() -> None:
    late = START + 7 * 86_400_000 + 1
    first = build_report(snap(now_ms=late), {})
    assert "یادآوری" in first.text
    assert first.state["burnin_notified"] == late
    second = build_report(snap(now_ms=late + 3_600_000), first.state)
    assert "یادآوری" not in second.text
    assert "تمام شده" in second.text


def test_paper_section() -> None:
    paper = {
        "equity": Decimal("1002000000"),
        "change_pct": 0.2,
        "trades_recent": 1,
        "trades_total": 3,
        "positions": ["BTC 0.0005"],
        "halt": None,
        "recent": ["خرید BTCIRT 0.0005 به قیمت ۱"],
    }
    services = {**ACTIVE, "trader-streams.service": "inactive", "trader-paper.service": "active"}
    r = build_report(snap(paper=paper, services=services), {})
    assert r.problems == []
    assert "+۰.۲۰٪" in r.text
    assert "BTC 0.0005" in r.text
    assert "داخل سرویس معاملات کاغذی" in r.text


def test_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "s" / "summary.json"
    assert load_state(path) == {}
    save_state(path, {"at_ms": 1})
    assert load_state(path) == {"at_ms": 1}
