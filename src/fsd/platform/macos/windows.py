"""Convert macOS window records into platform window information."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import Quartz

from fsd.platform.base import Rect, WindowInfo


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
