import asyncio
from collections.abc import Awaitable
from threading import Event


class RunCancelled(Exception):
  pass


class Control:
  def __init__(self) -> None:
    self._cancelled = Event()

  def cancel(self) -> None:
    self._cancelled.set()

  def check(self) -> None:
    if self._cancelled.is_set():
      raise RunCancelled("Run cancelled")


def _consume_result[T](task: asyncio.Future[T]) -> None:
  if not task.cancelled():
    task.exception()


async def controlled[T](work: Awaitable[T], control: Control, timeout: float) -> T:
  task = asyncio.ensure_future(work)
  deadline = asyncio.get_running_loop().time() + timeout
  try:
    while True:
      control.check()
      remaining = deadline - asyncio.get_running_loop().time()
      if remaining <= 0:
        raise TimeoutError("Operation exceeded its deadline")

      done, _ = await asyncio.wait({task}, timeout=min(0.02, remaining))

      control.check()
      if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError("Operation exceeded its deadline")
      if done:
        return task.result()
  finally:
    if not task.done():
      task.cancel()
    task.add_done_callback(_consume_result)
