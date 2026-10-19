import io
import signal

import pytest

from fsd.chat import display, interrupt_handler
from fsd.operator.control import Control, RunCancelled


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
