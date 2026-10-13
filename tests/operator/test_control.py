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


def test_completed_response_after_deadline_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
  async def scenario() -> None:
    now = 0.0

    async def complete_after_deadline() -> str:
      nonlocal now
      now = 2.0
      return "late response"

    with monkeypatch.context() as patch:
      patch.setattr(asyncio.get_running_loop(), "time", lambda: now)
      with pytest.raises(TimeoutError):
        await controlled(complete_after_deadline(), Control(), 1)

  asyncio.run(scenario())


def test_completed_response_is_discarded_when_cancelled() -> None:
  async def scenario() -> None:
    control = Control()

    async def complete_and_cancel() -> str:
      control.cancel()
      return "late response"

    with pytest.raises(RunCancelled):
      await controlled(complete_and_cancel(), control, 1)

  asyncio.run(scenario())


def test_successful_response_reaches_the_caller() -> None:
  async def scenario() -> None:
    result = await controlled(asyncio.sleep(0, result="response"), Control(), 1)
    assert result == "response"

  asyncio.run(scenario())


def test_operation_error_reaches_the_caller() -> None:
  async def scenario() -> None:
    async def fail() -> None:
      raise ValueError("Invalid response")

    with pytest.raises(ValueError, match="Invalid response"):
      await controlled(fail(), Control(), 1)

  asyncio.run(scenario())
