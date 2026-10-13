from collections.abc import Callable

import pytest

from fsd.platform.base import MAX_HOLD_MS
from fsd.platform.held_input import ReleaseError, held_input


@pytest.fixture
def timer() -> tuple[Callable[[], float], Callable[[float], None]]:
  now = 0.0

  def clock() -> float:
    return now

  def sleep(seconds: float) -> None:
    nonlocal now
    assert 0 < seconds <= 0.02
    now += seconds

  return clock, sleep


def test_cancel_releases_and_propagates(
  timer: tuple[Callable[[], float], Callable[[float], None]],
) -> None:
  clock, sleep = timer
  calls: list[str] = []

  def check() -> None:
    if clock() >= 0.04:
      raise RuntimeError("cancelled")

  with pytest.raises(RuntimeError, match="cancelled"):
    held_input(
      lambda: calls.append("down"),
      lambda: calls.append("up"),
      100,
      check,
      clock=clock,
      sleep=sleep,
    )
  assert calls == ["down", "up"]
  assert clock() == pytest.approx(0.04)


def test_initial_refusal_does_not_press_or_release() -> None:
  calls: list[str] = []

  def refuse() -> None:
    raise RuntimeError("refused")

  with pytest.raises(RuntimeError, match="refused"):
    held_input(lambda: calls.append("down"), lambda: calls.append("up"), 100, refuse)
  assert calls == []


def test_release_is_attempted_if_press_raises() -> None:
  calls: list[str] = []

  def press() -> None:
    calls.append("down")
    raise RuntimeError("posting failed")

  with pytest.raises(RuntimeError, match="posting failed"):
    held_input(press, lambda: calls.append("up"), 100, lambda: None)
  assert calls == ["down", "up"]


@pytest.mark.parametrize("duration_ms", [1, 55, MAX_HOLD_MS])
def test_normal_hold_uses_deadline_and_releases(
  duration_ms: int,
  timer: tuple[Callable[[], float], Callable[[float], None]],
) -> None:
  clock, sleep = timer
  calls: list[str] = []
  held_input(
    lambda: calls.append("down"),
    lambda: calls.append("up"),
    duration_ms,
    lambda: None,
    clock=clock,
    sleep=sleep,
  )
  assert calls == ["down", "up"]
  assert clock() == pytest.approx(duration_ms / 1000)


@pytest.mark.parametrize("duration_ms", [0, -1, MAX_HOLD_MS + 1, True, 1.5, "100", None])
def test_invalid_duration_never_checks_or_posts(duration_ms: int) -> None:
  calls: list[str] = []
  with pytest.raises(ValueError, match="Hold duration"):
    held_input(
      lambda: calls.append("down"),
      lambda: calls.append("up"),
      duration_ms,
      lambda: calls.append("check"),
    )
  assert calls == []


@pytest.mark.parametrize("press_fails", [False, True])
def test_release_failure_is_reported_with_its_cause(
  press_fails: bool,
  timer: tuple[Callable[[], float], Callable[[float], None]],
) -> None:
  clock, sleep = timer
  calls: list[str] = []
  failure = RuntimeError("release failed")

  def press() -> None:
    calls.append("down")
    if press_fails:
      raise RuntimeError("press failed")

  def release() -> None:
    calls.append("up")
    raise failure

  with pytest.raises(ReleaseError, match="Could not release") as caught:
    held_input(press, release, 1, lambda: None, clock=clock, sleep=sleep)
  assert caught.value.__cause__ is failure
  assert calls == ["down", "up"]
