"""The macOS implementation of the platform contract."""

from collections.abc import Collection

import Quartz

from fsd.platform.base import (
  AppInfo,
  Capability,
  Frame,
  MissingPermission,
  Rect,
  ScreenPoint,
  WindowInfo,
  topmost_owner,
)
from fsd.platform.macos import apps, capture, input, permissions, windows


class MacOSPlatform:
  capabilities = frozenset(
    {
      Capability.FILTERED_CAPTURE,
      Capability.WINDOW_OWNER_LOOKUP,
    }
  )

  def check_permissions(self) -> list[MissingPermission]:
    return permissions.check_permissions()

  def list_apps(self) -> list[AppInfo]:
    return apps.list_apps()

  def frontmost_app(self) -> str | None:
    return apps.frontmost_app()

  def capture(self, bundle_ids: Collection[str]) -> Frame:
    return capture.capture(bundle_ids)

  def windows(self) -> list[WindowInfo]:
    return windows.list_windows()

  def window_owner_at(self, point: ScreenPoint) -> str | None:
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    screen_rect = Rect(
      float(bounds.origin.x),
      float(bounds.origin.y),
      float(bounds.size.width),
      float(bounds.size.height),
    )
    if not screen_rect.contains(point):
      return None
    return topmost_owner(self.windows(), point)

  def click(self, point: ScreenPoint) -> None:
    input.click(point)

  def type_test(self, text: str) -> None:
    input.type_text(text)

  def press_keys(self, combo: str) -> None:
    input.press_keys(combo)

  def scroll(self, point: ScreenPoint, dx: int, dy: int) -> None:
    input.scroll(point, dx, dy)
