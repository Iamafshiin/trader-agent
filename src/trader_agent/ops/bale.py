import asyncio
from typing import Any

import httpx

BALE_API = "https://tapi.bale.ai"


class Alerter:
    def __init__(self, token: str | None, chat_id: str | None, client: httpx.AsyncClient) -> None:
        self._token = token
        self._chat_id = chat_id
        self._client = client
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def post(self, text: str) -> None:
        print(f"ALERT {text}", flush=True)
        if self.enabled:
            try:
                self._queue.put_nowait(text)
            except asyncio.QueueFull:
                print("ALERT queue full, dropping", flush=True)

    async def send_now(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = await self._client.post(
                f"{BALE_API}/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
            )
            return r.status_code == 200 and bool(r.json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    async def run(self) -> None:
        while True:
            text = await self._queue.get()
            for attempt in range(3):
                if await self.send_now(text):
                    break
                await asyncio.sleep(2**attempt)
            else:
                print("ALERT delivery failed", flush=True)


async def find_chat_ids(token: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    r = await client.get(f"{BALE_API}/bot{token}/getUpdates")
    r.raise_for_status()
    seen: dict[str, dict[str, Any]] = {}
    for update in r.json().get("result", []):
        chat = (update.get("message") or {}).get("chat") or {}
        if "id" in chat:
            seen[str(chat["id"])] = {
                "id": chat["id"],
                "type": chat.get("type"),
                "name": chat.get("username") or chat.get("first_name"),
            }
    return list(seen.values())
