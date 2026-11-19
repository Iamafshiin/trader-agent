import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from trader_agent.ops.bale import BALE_API
from trader_agent.ops.summary import _paper, fa, fa_num

HELP = "دستورها:\n/status — وضعیت\n/pause — توقف معاملات\n/resume — ادامه معاملات"
UNKNOWN = "دستور ناشناخته است.\n" + HELP


class BaleClient(Protocol):
    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]: ...

    async def send_message(self, chat_id: str, text: str) -> bool: ...


class HttpBaleClient:
    def __init__(self, token: str, client: httpx.AsyncClient) -> None:
        self._token = token
        self._client = client

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": 20}
        if offset is not None:
            params["offset"] = offset
        r = await self._client.get(
            f"{BALE_API}/bot{self._token}/getUpdates", params=params, timeout=40
        )
        r.raise_for_status()
        result: list[dict[str, Any]] = r.json().get("result", [])
        return result

    async def send_message(self, chat_id: str, text: str) -> bool:
        try:
            r = await self._client.post(
                f"{BALE_API}/bot{self._token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            return r.status_code == 200 and bool(r.json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False


class CommandHandler:
    def __init__(self, root: Path, run_id: str, db: Path) -> None:
        self.flag = root / "HALT"
        self.run_id = run_id
        self.db = db

    def handle(self, text: str) -> str:
        command = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
        if command == "/status":
            return self.status()
        if command == "/pause":
            return self.pause()
        if command == "/resume":
            return self.resume()
        return UNKNOWN

    def pause(self) -> str:
        if self.flag.exists():
            return "⏸ معاملات از قبل متوقف است."
        self.flag.parent.mkdir(parents=True, exist_ok=True)
        self.flag.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        return "⏸ معاملات متوقف شد. پوزیشن‌های باز و حد ضرر همچنان مدیریت می‌شوند."

    def resume(self) -> str:
        was_engaged = self.flag.exists()
        self.flag.unlink(missing_ok=True)
        halt = self._risk_halt()
        lines = ["▶️ کلید توقف برداشته شد." if was_engaged else "▶️ کلید توقف فعال نبود."]
        if halt:
            lines.append(f"⛔ توقف ریسک همچنان فعال است و با این دستور برداشته نمی‌شود: {halt}")
        return "\n".join(lines)

    def status(self) -> str:
        now_ms = int(time.time() * 1000)
        paper = _paper(self.db, self.run_id, now_ms, now_ms - 3_600_000)
        lines = ["📊 وضعیت ربات"]
        lines.append(
            "• کلید توقف: ⏸ فعال (معاملات جدید متوقف)"
            if self.flag.exists()
            else "• کلید توقف: ▶️ خاموش"
        )
        if paper is None:
            lines.append("• معاملات کاغذی: داده‌ای نیست")
            return "\n".join(lines)
        sign = "+" if paper["change_pct"] >= 0 else ""
        lines.append(
            f"• ارزش حساب: {fa_num(paper['equity'])} ریال "
            f"({sign}{fa(f'{paper["change_pct"]:.2f}')}٪ از شروع)"
        )
        lines.append(f"• معاملات: {fa(paper['trades_total'])}")
        lines.append(
            "• پوزیشن باز: " + ("، ".join(paper["positions"]) if paper["positions"] else "ندارد")
        )
        lines.append(f"• توقف ریسک: {paper['halt'] or 'ندارد'}")
        return "\n".join(lines)

    def _risk_halt(self) -> str | None:
        paper = _paper(self.db, self.run_id, 0, 0)
        halt: str | None = paper["halt"] if paper else None
        return halt


class CommandPoller:
    def __init__(self, client: BaleClient, chat_id: str, handler: CommandHandler) -> None:
        self._client = client
        self._chat_id = str(chat_id)
        self._handler = handler
        self._offset: int | None = None
        self._primed = False

    async def poll_once(self) -> int:
        updates = await self._client.get_updates(self._offset)
        execute = self._primed
        self._primed = True
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = update_id + 1
            if not execute:
                continue
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            text = message.get("text")
            if chat_id != self._chat_id or not isinstance(text, str):
                continue
            await self._client.send_message(self._chat_id, self._handler.handle(text))
        return len(updates)

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(5)
