from typing import Any, Protocol

import httpx


class ModelError(RuntimeError):
    pass


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OpenAICompatibleModel:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 120,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("LLM base URL must use https")
        self.name = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        body: dict[str, Any] = {
            "model": self.name,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            r = self._client.post("/chat/completions", json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from None
        if not isinstance(content, str):
            raise ModelError("model returned no text content")
        return content

    def close(self) -> None:
        self._client.close()
