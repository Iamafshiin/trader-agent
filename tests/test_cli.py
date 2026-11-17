import subprocess
import sys
from pathlib import Path

import pytest

from trader_agent.cli.main import main


def test_module_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "trader_agent", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "check-config" in result.stdout


def test_check_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADER_DATA_DIR", raising=False)
    assert main(["check-config"]) == 2
    assert "trader_data_dir" in capsys.readouterr().err


def test_check_config_prints_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOBITEX_API_KEY", "k-secret")
    assert main(["check-config"]) == 0
    out = capsys.readouterr().out
    assert "mode: paper" in out
    assert "k-secret" not in out
