import io
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fsd import chat
from fsd.operator.contracts import Decision
from tests.operator.helpers import decision, desktop


@pytest.fixture
def run_chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], tuple[int, str]]:
  monkeypatch.setenv("OPENROUTER_API_KEY", "private-api-key")
  monkeypatch.delenv("FSD_METRICS_PATH", raising=False)
  choices = iter(
    [
      Decision.model_validate(
        {
          "kind": "act",
          "action": {"kind": "type", "text": "private-typed-text"},
          "message": "private-message",
          "expected": "private-expected",
          "notes": "private-notes",
          "previous_result": "none",
        }
      ),
      decision("done"),
    ]
  )

  def handle(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
      200,
      json={
        "choices": [
          {"finish_reason": "stop", "message": {"content": next(choices).model_dump_json()}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
      },
    )

  http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
  monkeypatch.setattr(chat, "httpx", SimpleNamespace(AsyncClient=lambda: http))
  commands = iter(["private-goal", "/exit"])
  monkeypatch.setattr("builtins.input", lambda prompt: next(commands))
  platform, store = desktop(tmp_path)

  def run() -> tuple[int, str]:
    err = io.StringIO()
    status = chat.launch_chat(platform, store, io.StringIO(), err)
    return status, err.getvalue()

  return run


def test_metrics_append_and_flush_without_private_content(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  run_chat: Callable[[], tuple[int, str]],
) -> None:
  path = tmp_path / "metrics.jsonl"
  path.write_text('{"existing": true}\n', encoding="utf-8")
  monkeypatch.setenv("FSD_METRICS_PATH", str(path))
  commands = iter(["private-goal", "/exit"])

  def read(prompt: str) -> str:
    command = next(commands)
    if command == "/exit":
      assert len(path.read_text(encoding="utf-8").splitlines()) == 4
    return command

  monkeypatch.setattr("builtins.input", read)

  assert run_chat() == (0, "")
  text = path.read_text(encoding="utf-8")
  rows = [json.loads(line) for line in text.splitlines()]
  assert rows[0] == {"existing": True}
  assert rows[1]["input_tokens"] == 10
  assert rows[1]["cost"] == 0.0001
  assert rows[2]["action"] == "type"
  assert "execution_seconds" in rows[2]
  assert rows[3]["output_tokens"] == 5
  assert "private-" not in text
  allowed = {
    "capture_seconds",
    "request_seconds",
    "screenshot_to_decision_seconds",
    "input_tokens",
    "output_tokens",
    "cost",
    "action",
    "execution_seconds",
    "screenshot_to_action_seconds",
  }
  assert all(set(row) <= allowed for row in rows[1:])


def test_unopenable_metrics_path_reports_failure_before_reading_a_goal(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  run_chat: Callable[[], tuple[int, str]],
) -> None:
  monkeypatch.setenv("FSD_METRICS_PATH", str(tmp_path))

  def unexpected_input(prompt: str) -> str:
    pytest.fail("An unusable metrics file must be reported before reading a goal")

  monkeypatch.setattr("builtins.input", unexpected_input)
  status, error = run_chat()
  assert status == 2
  assert "FSD_METRICS_PATH" in error


@pytest.mark.parametrize("operation", ["write", "flush", "close"])
def test_metrics_io_failure_is_visible_and_stream_is_closed(
  monkeypatch: pytest.MonkeyPatch,
  run_chat: Callable[[], tuple[int, str]],
  operation: str,
) -> None:
  class BrokenStream(io.StringIO):
    def write(self, text: str) -> int:
      if operation == "write":
        raise OSError("private-write-error")
      return super().write(text)

    def flush(self) -> None:
      if operation == "flush":
        raise OSError("private-flush-error")
      super().flush()

    def close(self) -> None:
      if self.closed:
        return
      super().close()
      if operation == "close":
        raise OSError("private-close-error")

  stream = BrokenStream()
  monkeypatch.setenv("FSD_METRICS_PATH", "metrics.jsonl")
  monkeypatch.setattr(
    chat,
    "Path",
    lambda path: SimpleNamespace(open=lambda *args, **kwargs: stream),
    raising=False,
  )

  try:
    status, error = run_chat()
    assert status == 2
    assert "FSD_METRICS_PATH" in error
    assert "private-" not in error
    assert stream.closed
  finally:
    io.StringIO.close(stream)
