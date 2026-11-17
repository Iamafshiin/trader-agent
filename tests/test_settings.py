from pathlib import Path

import pytest

from trader_agent.settings import SettingsError, load_settings


def test_requires_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADER_DATA_DIR", raising=False)
    with pytest.raises(SettingsError, match="trader_data_dir"):
        load_settings()


def test_rejects_relative_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SettingsError, match="trader_data_dir"):
        load_settings(trader_data_dir=Path("data"))


def test_rejects_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SettingsError, match="trader_mode"):
        load_settings(trader_data_dir=tmp_path, trader_mode="live")


def test_rejects_plain_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SettingsError, match="nobitex_base_url"):
        load_settings(trader_data_dir=tmp_path, nobitex_base_url="http://example.com")


def test_summary_hides_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings(trader_data_dir=tmp_path, nobitex_api_key="k-123")
    summary = settings.summary()
    assert summary["nobitex_credentials"] == "set"
    assert "k-123" not in str(summary)
    assert "k-123" not in repr(settings)


def test_data_path_creates_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings(trader_data_dir=tmp_path / "data")
    path = settings.data_path("candles")
    assert path.is_dir()
