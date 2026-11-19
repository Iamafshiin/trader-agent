from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    trader_mode: Literal["paper"] = "paper"
    trader_data_dir: Path
    nobitex_base_url: str = "https://apiv2.nobitex.ir"
    nobitex_user_agent: str = "TraderBot/trader-agent-0.1"
    nobitex_api_key: SecretStr | None = None
    nobitex_secret_key: SecretStr | None = None
    bale_bot_token: SecretStr | None = None
    bale_chat_id: str | None = None
    burnin_start: datetime | None = None
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    @field_validator("llm_base_url")
    @classmethod
    def _https_llm_url(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("LLM_BASE_URL must use https")
        return value.rstrip("/") if value else None

    @field_validator("trader_data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("TRADER_DATA_DIR must be an absolute path")
        return value

    @field_validator("nobitex_base_url")
    @classmethod
    def _https_base_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("NOBITEX_BASE_URL must use https")
        return value.rstrip("/")

    def data_path(self, *parts: str) -> Path:
        path = self.trader_data_dir.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def summary(self) -> dict[str, str]:
        return {
            "mode": self.trader_mode,
            "data_dir": str(self.trader_data_dir),
            "nobitex_base_url": self.nobitex_base_url,
            "nobitex_credentials": "set" if self.nobitex_api_key else "absent",
            "bale_alerts": "set" if self.bale_bot_token and self.bale_chat_id else "absent",
            "llm": self.llm_model if self.llm_model and self.llm_ready() else "absent",
        }

    def llm_ready(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


def load_settings(**overrides: object) -> Settings:
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) or "?" for e in exc.errors())
        raise SettingsError(f"invalid settings: {fields}") from None
