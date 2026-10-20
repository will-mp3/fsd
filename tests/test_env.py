import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from fsd import cli
from fsd.platform.fake import FakePlatform


@pytest.fixture(autouse=True)
def isolated_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  monkeypatch.setattr(os, "environ", os.environ.copy())
  for name in ("OPENROUTER_API_KEY", "FSD_METRICS_PATH", "PYTHON_DOTENV_DISABLED"):
    monkeypatch.delenv(name, raising=False)
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path / "config"))
  monkeypatch.setattr("builtins.input", lambda prompt: "/exit")
  original_run = cli.run

  def run(argv: Sequence[str] | None) -> int:
    return original_run(argv, backend_factory=FakePlatform)

  monkeypatch.setattr(cli, "run", run)
  monkeypatch.setattr(sys, "argv", ["fsd", "chat"])


@pytest.mark.parametrize("exported_key", [None, "exported-test-key"])
def test_startup_loads_local_env_without_overriding_exported_key(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
  exported_key: str | None,
) -> None:
  (tmp_path / ".env").write_text(
    "OPENROUTER_API_KEY=local-test-key\nFSD_METRICS_PATH=./metrics.jsonl\n",
    encoding="utf-8",
  )
  if exported_key is not None:
    monkeypatch.setenv("OPENROUTER_API_KEY", exported_key)

  with pytest.raises(SystemExit) as exc:
    cli.main()

  assert exc.value.code == 0
  assert os.environ["OPENROUTER_API_KEY"] == (exported_key or "local-test-key")
  assert (tmp_path / "metrics.jsonl").is_file()
  output = capsys.readouterr()
  assert output.err == ""
  assert "enter a goal" in output.out
  assert "test-key" not in output.out


def test_missing_local_env_uses_shell_without_searching_parent_directories(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
  (tmp_path / ".env").write_text("FSD_METRICS_PATH=./unexpected.jsonl\n", encoding="utf-8")
  child = tmp_path / "child"
  child.mkdir()
  monkeypatch.chdir(child)
  monkeypatch.setenv("OPENROUTER_API_KEY", "exported-test-key")

  with pytest.raises(SystemExit) as exc:
    cli.main()

  assert exc.value.code == 0
  assert "FSD_METRICS_PATH" not in os.environ
  assert not (child / "unexpected.jsonl").exists()
  assert capsys.readouterr().err == ""


@pytest.mark.parametrize("problem", ["directory", "invalid_encoding"])
def test_unreadable_env_reports_error_without_starting_chat_or_exposing_content(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
  problem: str,
) -> None:
  path = tmp_path / ".env"
  if problem == "directory":
    path.mkdir()
  else:
    path.write_bytes(b"OPENROUTER_API_KEY=private-value\xff\n")
  monkeypatch.setenv("OPENROUTER_API_KEY", "exported-test-key")

  with pytest.raises(SystemExit) as exc:
    cli.main()

  assert exc.value.code == 2
  output = capsys.readouterr()
  assert output.out == ""
  assert ".env" in output.err
  assert "private-value" not in output.err
  assert "Traceback" not in output.err
