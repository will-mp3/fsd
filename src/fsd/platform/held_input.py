import time
from collections.abc import Callable

from fsd.platform.base import MAX_HOLD_MS, PlatformError


class ReleaseError(PlatformError):
  """Input state may be uncertain; end execution and tell the user."""


def held_input(
  press: Callable[[], None],
  release: Callable[[], None],
  duration_ms: int,
  check: Callable[[], None],
  *,
  clock: Callable[[], float] = time.monotonic,
  sleep: Callable[[float], None] = time.sleep,
) -> None:
  if type(duration_ms) is not int or not 0 < duration_ms <= MAX_HOLD_MS:
    raise ValueError(f"Hold duration must be 1 to {MAX_HOLD_MS} milliseconds")

  check()
  try:
    press()
    deadline = clock() + duration_ms / 1000
    while True:
      check()
      remaining = deadline - clock()
      if remaining <= 0:
        break
      sleep(min(0.02, remaining))
  finally:
    try:
      release()
    except Exception as exc:
      raise ReleaseError("Could not release a held key; stop and check keyboard state.") from exc
