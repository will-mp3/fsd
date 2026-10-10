"""Filtered frame capture with ScreenCaptureKit."""

import threading
from collections.abc import Callable, Collection
from typing import Any

import Quartz
import ScreenCaptureKit

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


def _content_filter(content: Any, bundle_ids: Collection[str]) -> tuple[Any, int]:
  main_display = int(Quartz.CGMainDisplayID())
  display = next(
    (display for display in content.displays() if display.displayID() == main_display),
    None,
  )
  if display is None:
    raise CaptureError("The main display is not available for capture.")

  wanted = set(bundle_ids)
  applications = [app for app in content.applications() if app.bundleIdentifier() in wanted]

  builder = ScreenCaptureKit.SCContentFilter.alloc()
  content_filter = builder.initWithDisplay_includingApplications_exceptingWindows_(
    display, applications, []
  )
  if content_filter is None:
    raise CaptureError("Could not create the capture filter.")

  return content_filter, main_display
