import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import TextIO


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
