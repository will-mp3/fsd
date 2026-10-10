"""Convert macOS window records into platform window information."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import Quartz

from fsd.platform.base import Rect, WindowInfo
from fsd.platform.macos.apps import bundle_id_for_pid


def window_from_entry(
  entry: Mapping[str, Any], lookup: Callable[[int], str | None]
) -> WindowInfo | None:
  if float(entry.get(Quartz.kCGWindowAlpha, 1.0)) <= 0.0:
    return None

  owner = lookup(int(entry[Quartz.kCGWindowOwnerPID]))
  if owner is None:
    # Keep unidentified owners visible to the gate so they require approval.
    owner = f"unidentified:{entry.get(Quartz.kCGWindowOwnerName, 'unknown')}"

  bounds = entry[Quartz.kCGWindowBounds]
  return WindowInfo(
    owner,
    Rect(
      float(bounds["X"]),
      float(bounds["Y"]),
      float(bounds["Width"]),
      float(bounds["Height"]),
    ),
    int(entry.get(Quartz.kCGWindowLayer, 0)),
  )


def list_windows() -> list[WindowInfo]:
  # Excluding desktop elements leaves bare-desktop clicks without an approved owner.
  entries = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
    Quartz.kCGNullWindowID,
  )
  windows = (window_from_entry(entry, bundle_id_for_pid) for entry in entries or [])
  return [window for window in windows if window is not None]
