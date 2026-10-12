import asyncio

import pytest
from fsd.operator.control import Control, RunCancelled, controlled


def test_cancelled_response_cannot_be_consumed() -> None:
  async def scenario() -> None:
    control = Control()
    started = asyncio.Event()
    consumed: list[str] = []

    async def delayed() -> str:
      started.set()
      await asyncio.sleep(30)
      return "late"

    async def consume() -> None:
      consumed.append(await controlled(delayed(), control, 60))

    task = asyncio.create_task(consume())
    await started.wait()
    control.cancel()
    with pytest.raises(RunCancelled):
      await task
    assert consumed == []

  asyncio.run(scenario())


def test_request_has_a_total_deadline() -> None:
  async def scenario() -> None:
    with pytest.raises(TimeoutError):
      await controlled(asyncio.sleep(30), Control(), 0.01)

  asyncio.run(scenario())
