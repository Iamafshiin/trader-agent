import asyncio
import json
from pathlib import Path
from typing import Any

from trader_agent.ops.commands import CommandHandler, CommandPoller
from trader_agent.paper.engine import PaperStore
from trader_agent.risk.gate import RiskState

CHAT = "111"


class FakeBale:
    def __init__(self) -> None:
        self.queue: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str]] = []
        self.offsets: list[int | None] = []

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        out = [u for u in self.queue if offset is None or u["update_id"] >= offset]
        self.queue = []
        return out

    async def send_message(self, chat_id: str, text: str) -> bool:
        self.sent.append((chat_id, text))
        return True

    def say(self, update_id: int, chat: str, text: str) -> None:
        self.queue.append(
            {"update_id": update_id, "message": {"chat": {"id": int(chat)}, "text": text}}
        )


def make(tmp_path: Path) -> tuple[FakeBale, CommandPoller, Path]:
    fake = FakeBale()
    handler = CommandHandler(tmp_path, "t", tmp_path / "db" / "paper.sqlite3")
    poller = CommandPoller(fake, CHAT, handler)
    asyncio.run(poller.poll_once())
    return fake, poller, tmp_path / "HALT"


def poll(poller: CommandPoller) -> None:
    asyncio.run(poller.poll_once())


def seed_paper(tmp_path: Path, halt: str | None) -> None:
    db = tmp_path / "db" / "paper.sqlite3"
    store = PaperStore(db)
    store.conn.execute(
        "INSERT INTO runs (run_id, version, config_hash, started_ms, config) VALUES (?,?,?,?,?)",
        ("t", "v", "h", 0, json.dumps({"starting_balance_rls": "1000000"})),
    )
    store.conn.commit()
    state = RiskState(db, "t")
    state.halt_reason = halt
    state.save()


def test_pause_and_resume_toggle_kill_switch(tmp_path: Path) -> None:
    fake, poller, flag = make(tmp_path)
    fake.say(1, CHAT, "/pause")
    poll(poller)
    assert flag.exists()
    assert "متوقف شد" in fake.sent[-1][1]
    fake.say(2, CHAT, "/resume")
    poll(poller)
    assert not flag.exists()
    assert "برداشته شد" in fake.sent[-1][1]


def test_other_chat_is_ignored(tmp_path: Path) -> None:
    fake, poller, flag = make(tmp_path)
    fake.say(1, "999", "/pause")
    poll(poller)
    assert not flag.exists()
    assert fake.sent == []


def test_backlog_is_not_executed_on_start(tmp_path: Path) -> None:
    fake = FakeBale()
    fake.say(1, CHAT, "/pause")
    poller = CommandPoller(fake, CHAT, CommandHandler(tmp_path, "t", tmp_path / "p.sqlite3"))
    poll(poller)
    assert not (tmp_path / "HALT").exists()
    assert fake.sent == []
    poll(poller)
    assert fake.offsets[-1] == 2


def test_status_and_unknown_reply_in_persian(tmp_path: Path) -> None:
    fake, poller, _ = make(tmp_path)
    fake.say(1, CHAT, "/status")
    fake.say(2, CHAT, "/bogus")
    poll(poller)
    assert "وضعیت ربات" in fake.sent[0][1]
    assert "دستور ناشناخته" in fake.sent[1][1]
    assert all(chat == CHAT for chat, _ in fake.sent)


def test_status_reports_risk_halt_and_kill_switch(tmp_path: Path) -> None:
    seed_paper(tmp_path, "max drawdown limit hit")
    fake, poller, _ = make(tmp_path)
    fake.say(1, CHAT, "/pause")
    fake.say(2, CHAT, "/status")
    poll(poller)
    assert "max drawdown limit hit" in fake.sent[-1][1]
    assert "فعال" in fake.sent[-1][1]


def test_resume_never_clears_risk_halt(tmp_path: Path) -> None:
    seed_paper(tmp_path, "max drawdown limit hit")
    fake, poller, flag = make(tmp_path)
    flag.write_text("x", encoding="utf-8")
    fake.say(1, CHAT, "/resume")
    poll(poller)
    assert not flag.exists()
    assert "همچنان فعال" in fake.sent[-1][1]
    assert RiskState(tmp_path / "db" / "paper.sqlite3", "t").halt_reason == "max drawdown limit hit"


def test_flatten_requires_confirmation_then_runs(tmp_path: Path) -> None:
    calls: list[int] = []

    def flatten(now_ms: int) -> list[tuple[str, str, str]]:
        calls.append(now_ms)
        return [("BTCIRT", "sold", "0.001 @ 1300000")]

    fake = FakeBale()
    handler = CommandHandler(tmp_path, "t", tmp_path / "p.sqlite3", flatten)
    poller = CommandPoller(fake, CHAT, handler)
    poll(poller)
    fake.say(1, CHAT, "/flatten")
    poll(poller)
    assert calls == []
    assert "/flatten confirm" in fake.sent[-1][1]
    fake.say(2, CHAT, "/flatten confirm")
    poll(poller)
    assert len(calls) == 1
    assert "BTCIRT" in fake.sent[-1][1]
    assert "۱۳۰۰۰۰۰" in fake.sent[-1][1]


def test_flatten_from_other_chat_is_ignored(tmp_path: Path) -> None:
    calls: list[int] = []
    fake = FakeBale()
    handler = CommandHandler(
        tmp_path, "t", tmp_path / "p.sqlite3", lambda ms: calls.append(ms) or []
    )
    poller = CommandPoller(fake, CHAT, handler)
    poll(poller)
    fake.say(1, "999", "/flatten confirm")
    poll(poller)
    assert calls == []
    assert fake.sent == []
