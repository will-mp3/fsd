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
  monkeypatch.delenv("FSD_TRACE_DIR", raising=False)
  contents = iter(
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
      ).model_dump_json(),
      decision("done").model_dump_json(),
      json.dumps({"complete": True, "evidence": "private-evidence"}),
    ]
  )

  def handle(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
      200,
      json={
        "choices": [{"finish_reason": "stop", "message": {"content": next(contents)}}],
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
      assert len(path.read_text(encoding="utf-8").splitlines()) == 6
    return command

  monkeypatch.setattr("builtins.input", read)

  assert run_chat() == (0, "")
  text = path.read_text(encoding="utf-8")
  rows = [json.loads(line) for line in text.splitlines()]
  assert rows[0] == {"existing": True}
  assert rows[1]["status"] == "action"
  assert rows[1]["action"] == "type"
  assert rows[2]["outcome"] == "performed"
  assert rows[2]["input_tokens"] == 10
  assert rows[2]["cost"] == 0.0001
  assert rows[2]["previous_result"] == "none"
  assert rows[3]["outcome"] == "claimed_done"
  assert rows[3]["previous_result"] == "success"
  assert rows[4]["outcome"] == "done"
  assert rows[4]["decision"] == "verify"
  assert rows[5]["status"] == "done"
  assert "private-" not in text
  allowed = {
    "run_id",
    "step",
    "bundle_id",
    "frame_width",
    "frame_height",
    "frame_bytes",
    "images_sent",
    "capture_seconds",
    "encode_seconds",
    "request_seconds",
    "screenshot_to_decision_seconds",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost",
    "decision",
    "action",
    "outcome",
    "invalid_cause",
    "refusal",
    "visible_change",
    "stuck",
    "execution_seconds",
    "screenshot_to_action_seconds",
    "status",
    "previous_result",
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


@pytest.mark.parametrize("metrics_enabled", [False, True])
def test_trace_dir_archives_one_frame_per_step(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  run_chat: Callable[[], tuple[int, str]],
  metrics_enabled: bool,
) -> None:
  trace = tmp_path / "trace"
  monkeypatch.setenv("FSD_TRACE_DIR", str(trace))
  metrics = tmp_path / "metrics.jsonl"
  if metrics_enabled:
    monkeypatch.setenv("FSD_METRICS_PATH", str(metrics))

  assert run_chat() == (0, "")
  assert trace.is_dir()
  (run,) = trace.iterdir()
  assert sorted(p.name for p in run.iterdir()) == ["0.png", "1.png", "2.png"]
  assert [(run / name).read_bytes() for name in ("0.png", "1.png", "2.png")] == [
    b"frame-0",
    b"frame-1",
    b"frame-2",
  ]
  if metrics_enabled:
    rows = [json.loads(line) for line in metrics.read_text(encoding="utf-8").splitlines()]
    steps = [row for row in rows if "step" in row]
    assert [(row["run_id"], row["step"]) for row in steps] == [
      (run.name, 0),
      (run.name, 1),
      (run.name, 2),
    ]


def test_no_trace_dir_writes_no_frames(
  tmp_path: Path, run_chat: Callable[[], tuple[int, str]]
) -> None:
  assert run_chat() == (0, "")
  assert list(tmp_path.rglob("*.png")) == []


def test_unwritable_trace_dir_names_the_setting(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  run_chat: Callable[[], tuple[int, str]],
) -> None:
  blocker = tmp_path / "file"
  blocker.write_text("not a directory", encoding="utf-8")
  monkeypatch.setenv("FSD_TRACE_DIR", str(blocker / "trace"))
  status, err = run_chat()
  assert status == 2
  assert "FSD_TRACE_DIR" in err
  assert "FSD_METRICS_PATH" not in err
