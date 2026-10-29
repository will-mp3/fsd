import asyncio
import json
import os
import signal
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import partial
from pathlib import Path
from types import FrameType
from typing import TextIO

import httpx

from fsd.approval.store import ApprovalStore
from fsd.operator.client import OpenRouterClient
from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.contracts import Event, Reply, Snapshot
from fsd.operator.control import Control
from fsd.operator.engine import Engine
from fsd.platform.base import Platform


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
  archive: Callable[[Snapshot], None] | None = None,
) -> None:
  exit_requested = False
  display("fsd: enter a goal; /exit ends the session. Ctrl-C cancels the current task.", out)

  async def emit(event: Event) -> Reply | None:
    nonlocal exit_requested
    if archive is not None and event.snapshot is not None:
      archive(event.snapshot)
    if diagnostics is not None:
      metrics = dict(event.metrics or {})
      if event.kind in {"action", "help", "done", "failed", "cancelled"}:
        metrics["status"] = event.kind
      if metrics:
        diagnostics(metrics)

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


class DiagnosticsError(Exception):
  def __init__(self, setting: str) -> None:
    super().__init__(setting)
    self.setting = setting


def _diagnostic_io[T](operation: Callable[[], T], setting: str = "FSD_METRICS_PATH") -> T:
  try:
    return operation()
  except OSError:
    raise DiagnosticsError(setting) from None


def launch_chat(platform: Platform, store: ApprovalStore, out: TextIO, err: TextIO) -> int:
  key = os.environ.get("OPENROUTER_API_KEY", "").strip()
  if not key:
    print("fsd: set OPENROUTER_API_KEY before starting chat.", file=err)
    return 2
  settings = Settings()

  async def start() -> None:
    metrics_path = os.environ.get("FSD_METRICS_PATH")
    with ExitStack() as stack:
      stream = None
      if metrics_path:
        stream = _diagnostic_io(
          lambda: Path(metrics_path).open("a", encoding="utf-8")  # noqa: SIM115
        )
        stack.callback(_diagnostic_io, stream.close)

      def record(metrics: dict[str, object]) -> None:
        if stream is not None:
          line = json.dumps(metrics, allow_nan=False) + "\n"
          _diagnostic_io(partial(stream.write, line))
          _diagnostic_io(stream.flush)

      archive: Callable[[Snapshot], None] | None = None
      trace_dir = os.environ.get("FSD_TRACE_DIR")
      if trace_dir:
        root = Path(trace_dir)

        def save(snapshot: Snapshot) -> None:
          folder = root / snapshot.run_id
          _diagnostic_io(partial(folder.mkdir, parents=True, exist_ok=True), "FSD_TRACE_DIR")
          target = folder / f"{snapshot.step}.png"
          _diagnostic_io(partial(target.write_bytes, snapshot.png), "FSD_TRACE_DIR")

        archive = save

      async with httpx.AsyncClient() as http:
        client = OpenRouterClient(http, key, settings)
        engine = Engine(platform, store, client, settings)
        await conversation(engine, Session(settings), input, out, record, archive)

  try:
    asyncio.run(start())
  except DiagnosticsError as exc:
    print(f"fsd: could not write diagnostic records; check {exc.setting}.", file=err)
    return 2
  return 0
