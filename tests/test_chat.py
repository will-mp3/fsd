import asyncio
import io
import signal
from pathlib import Path

import pytest

from fsd.chat import conversation, display, interrupt_handler
from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.control import Control, RunCancelled
from fsd.operator.engine import Engine
from tests.operator.helpers import ScriptedClient, decision, desktop


def test_sigint_cancels_active_control_without_raising_keyboard_interrupt() -> None:
  control = Control()
  previous = signal.getsignal(signal.SIGINT)

  with interrupt_handler(control.cancel):
    signal.raise_signal(signal.SIGINT)
    with pytest.raises(RunCancelled):
      control.check()

  assert signal.getsignal(signal.SIGINT) == previous


def test_prompt_interrupt_restores_active_run_handler() -> None:
  control = Control()
  previous = signal.getsignal(signal.SIGINT)

  with interrupt_handler(control.cancel):
    with pytest.raises(KeyboardInterrupt), interrupt_handler(None):
      signal.raise_signal(signal.SIGINT)

    control.check()
    signal.raise_signal(signal.SIGINT)
    with pytest.raises(RunCancelled):
      control.check()

  assert signal.getsignal(signal.SIGINT) == previous


def test_interrupt_handler_restores_previous_handler_after_error() -> None:
  previous = signal.getsignal(signal.SIGINT)

  with pytest.raises(ValueError, match="reader failed"), interrupt_handler(Control().cancel):
    raise ValueError("reader failed")

  assert signal.getsignal(signal.SIGINT) == previous


def test_display_removes_terminal_controls_and_preserves_readable_text() -> None:
  output = io.StringIO()

  display("Progress\x1b[2J\r\x00\x07\b\t\x9b\u202e\nCafé ready", output)

  assert output.getvalue() == "Progress[2J\nCafé ready\n"


def test_session_accepts_followup_without_restarting(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done"), decision("done")])
  commands = iter(["Open the document", "Now scroll it", "/exit"])
  output = io.StringIO()
  settings = Settings()

  asyncio.run(
    conversation(
      Engine(platform, store, client, settings),
      Session(settings),
      lambda prompt: next(commands),
      output,
    )
  )

  assert len(client.observations) == 2
  assert "Open the document" in client.observations[1].text
  assert "Now scroll it" in client.observations[1].text
  assert client.observations[1].previous is None
  assert output.getvalue().count("Task complete") == 2


@pytest.mark.parametrize(
  ("guidance", "expected"),
  [
    ("I selected the correct window; continue", "correct window"),
    ("/continue", "Continue after manual intervention"),
  ],
)
def test_help_continues_same_goal_with_fresh_observation(
  tmp_path: Path, guidance: str, expected: str
) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("help"), decision("done")])
  commands = iter(["Open it", guidance, "/exit"])
  settings = Settings()
  session = Session(settings)

  asyncio.run(
    conversation(
      Engine(platform, store, client, settings),
      session,
      lambda prompt: next(commands),
      io.StringIO(),
    )
  )

  assert len(client.observations) == 2
  assert client.observations[1].previous is None
  assert expected in client.observations[1].text
  assert list(session.goals) == ["Open it"]


@pytest.mark.parametrize("reply", ["/cancel", KeyboardInterrupt(), "/exit", EOFError()])
def test_help_cancellation_and_exit_have_distinct_session_lifetimes(
  tmp_path: Path, reply: str | BaseException
) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("help"), decision("done")])
  commands = iter(["First goal", reply, "Second goal", "/exit"])
  prompts: list[str] = []
  settings = Settings()
  output = io.StringIO()

  def read(prompt: str) -> str:
    prompts.append(prompt)
    item = next(commands)
    if isinstance(item, BaseException):
      raise item
    return item

  asyncio.run(
    conversation(Engine(platform, store, client, settings), Session(settings), read, output)
  )

  exiting = reply == "/exit" or isinstance(reply, EOFError)
  assert prompts == (
    ["you> ", "guidance> "] if exiting else ["you> ", "guidance> ", "you> ", "you> "]
  )
  assert len(client.observations) == (1 if exiting else 2)
  assert "Task cancelled" in output.getvalue()
  if not exiting:
    assert "Second goal" in client.observations[1].text


def test_idle_interrupt_and_invalid_commands_do_not_start_runs(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done")])
  commands = iter([KeyboardInterrupt(), "  ", "/unknown", "Actual goal", EOFError()])
  settings = Settings()

  def read(prompt: str) -> str:
    item = next(commands)
    if isinstance(item, BaseException):
      raise item
    return item

  asyncio.run(
    conversation(Engine(platform, store, client, settings), Session(settings), read, io.StringIO())
  )

  assert len(client.observations) == 1
  assert "Actual goal" in client.observations[0].text


def test_limit_requires_explicit_extension_before_inference_resumes(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision("done")])
  commands = iter(["Open it", "/continue", "/extend", "/exit"])
  prompts: list[str] = []
  settings = Settings(action_limit=1)

  def read(prompt: str) -> str:
    prompts.append(prompt)
    if prompt == "guidance> ":
      assert len(client.observations) == 1
    return next(commands)

  asyncio.run(
    conversation(Engine(platform, store, client, settings), Session(settings), read, io.StringIO())
  )

  assert prompts == ["you> ", "guidance> ", "guidance> ", "you> "]
  assert len(client.observations) == 2


def test_diagnostics_receive_metrics_while_terminal_shows_progress(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision("done")])
  commands = iter(["Open it", "/exit"])
  settings = Settings()
  metrics: list[dict[str, object]] = []
  output = io.StringIO()

  asyncio.run(
    conversation(
      Engine(platform, store, client, settings),
      Session(settings),
      lambda prompt: next(commands),
      output,
      diagnostics=metrics.append,
    )
  )

  assert len(metrics) == 3
  assert metrics[1]["action"] == "key"
  assert "Continue" in output.getvalue()
  assert "Performed key" in output.getvalue()
  assert "Task complete" in output.getvalue()
  assert "input_tokens" not in output.getvalue()
