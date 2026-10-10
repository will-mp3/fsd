"""Filtered frame capture with ScreenCaptureKit."""

import threading
from collections.abc import Callable
from typing import Any

from fsd.platform.base import CaptureError

_TIMEOUT_SECONDS = 10.0

Handler = Callable[[Any, Any], None]


def _wait_for(start: Callable[[Handler], None], what: str) -> Any:
  done = threading.Event()
  outcome: dict[str, Any] = {}

  def handler(result: Any, error: Any) -> None:
    outcome["result"] = result
    outcome["error"] = error
    # Publish the outcome before waking the waiting thread.
    done.set()

  start(handler)

  if not done.wait(_TIMEOUT_SECONDS):
    raise CaptureError(f"{what} did not respond within {_TIMEOUT_SECONDS:.0f} seconds.")

  if outcome["error"] is not None:
    raise CaptureError(
      f"{what} failed: {outcome['error'].localizedDescription()}. "
      "Run 'fsd doctor' to check Screen Recording permission."
    )

  return outcome["result"]
