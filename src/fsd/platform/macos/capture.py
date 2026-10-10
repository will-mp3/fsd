"""Filtered frame capture with ScreenCaptureKit."""

import threading
from collections.abc import Callable, Collection
from typing import Any

import AppKit
import Quartz
import ScreenCaptureKit

from fsd.platform.base import CaptureError, Frame, Rect

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


def _frame_from_image(image: Any, screen_rect: Rect) -> Frame:
  if image is None:
    raise CaptureError("Capture returned no image.")

  representation = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(image)
  if representation is None:
    raise CaptureError("The captured image could not be prepared for PNG encoding.")

  png = representation.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
  if png is None:
    raise CaptureError("The captured frame could not be encoded as PNG.")

  return Frame(
    png=bytes(png),
    width=int(Quartz.CGImageGetWidth(image)),
    height=int(Quartz.CGImageGetHeight(image)),
    screen_rect=screen_rect,
  )
