import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import TextIO

from fsd.operator.context import Session
from fsd.operator.contracts import Event, Reply
from fsd.operator.control import Control
from fsd.operator.engine import Engine


@contextmanager
def interrupt_handler(cancel: Callable[[], None] | None) -> Iterator[None]:
  def handler(signum: int, frame: FrameType | None) -> None:
    if cancel is not None:
      cancel()

  previous = signal.signal(
    signal.SIGINT,
    handler if cancel is not None else signal.default_int_handler,
  )
  try:
    yield
  finally:
    signal.signal(signal.SIGINT, previous)


def display(text: str, out: TextIO) -> None:
  safe = "".join(character for character in text if character.isprintable() or character == "\n")
  print(safe, file=out, flush=True)


async def conversation(
  engine: Engine,
  session: Session,
  read: Callable[[str], str],
  out: TextIO,
  diagnostics: Callable[[dict[str, object]], None] | None = None,
) -> None:
  exit_requested = False
  display("fsd: enter a goal; /exit ends the session. Ctrl-C cancels the current task.", out)

  async def emit(event: Event) -> Reply | None:
    nonlocal exit_requested
    if event.metrics is not None and diagnostics is not None:
      diagnostics(event.metrics)
    if event.kind == "metrics":
      return None

    display(f"fsd: {event.message}", out)
    if event.kind != "help":
      return None

    hint = "Use /extend or /cancel." if event.limit else "Give guidance, /continue, or /cancel."
    display(hint, out)
    try:
      with interrupt_handler(None):
        answer = read("guidance> ").strip()
    except KeyboardInterrupt:
      return Reply(cancel=True)
    except EOFError:
      exit_requested = True
      return Reply(cancel=True)

    if answer == "/exit":
      exit_requested = True
      return Reply(cancel=True)
    if answer == "/cancel":
      return Reply(cancel=True)
    if answer == "/extend":
      return Reply(extend=True)
    return Reply(text="Continue after manual intervention" if answer == "/continue" else answer)

  while not exit_requested:
    try:
      with interrupt_handler(None):
        goal = read("you> ").strip()
    except KeyboardInterrupt:
      display("fsd: no task running; use /exit to close the session.", out)
      continue
    except EOFError:
      return

    if goal == "/exit":
      return
    if not goal:
      continue
    if goal.startswith("/"):
      display("fsd: enter a goal or use /exit.", out)
      continue

    control = Control()
    with interrupt_handler(control.cancel):
      await engine.run(goal, session, control, emit)
