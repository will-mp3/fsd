"""A backend for tests and replay: serves recorded frames and records requested input."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterable

from fsd.platform.base import (
  MANDATORY_CAPABILITIES,
  MAX_HOLD_MS,
  AppInfo,
  Capability,
  CaptureError,
  Frame,
  MissingPermission,
  ScreenPoint,
  WindowInfo,
  parse_combo,
  topmost_owner,
)


class FakePlatform:
  def __init__(
    self,
    *,
    apps: Iterable[AppInfo] = (),
    windows: Iterable[WindowInfo] = (),
    frontmost: str | None = None,
    frames: Iterable[Frame] = (),
    capabilities: Collection[Capability] = MANDATORY_CAPABILITIES,
    missing_permissions: Iterable[MissingPermission] = (),
  ) -> None:
    self.capabilities = frozenset(capabilities)
    self.apps = list(apps)
    self.window_list = list(windows)
    self.frontmost = frontmost
    self.actions: list[tuple[object, ...]] = []
    self.capture_requests: list[frozenset[str]] = []
    self._frames = deque(frames)
    self._missing_permissions = list(missing_permissions)

  def check_permissions(self) -> list[MissingPermission]:
    return list(self._missing_permissions)

  def list_apps(self) -> list[AppInfo]:
    return list(self.apps)

  def frontmost_app(self) -> str | None:
    return self.frontmost

  def capture(self, bundle_ids: Collection[str]) -> Frame:
    self.capture_requests.append(frozenset(bundle_ids))
    if not self._frames:
      raise CaptureError("FakePlatform has no recorded frames left to replay.")
    return self._frames.popleft()

  def windows(self) -> list[WindowInfo]:
    return list(self.window_list)

  def window_owner_at(self, point: ScreenPoint) -> str | None:
    return topmost_owner(self.window_list, point)

  def click(self, point: ScreenPoint) -> None:
    self.actions.append(("click", point))

  def type_text(self, text: str) -> None:
    self.actions.append(("type_text", text))

  def type_text_checked(self, text: str, check: Callable[[], None]) -> None:
    for character in text:
      check()
      self.actions.append(("type_character", character))

  def hold_key(self, key: str, duration_ms: int, check: Callable[[], None]) -> None:
    parsed = parse_combo(key)
    if parsed.modifiers or type(duration_ms) is not int or not 0 < duration_ms <= MAX_HOLD_MS:
      raise ValueError("Invalid key hold")
    check()
    self.actions.append(("hold_key", parsed.key, duration_ms))
    check()

  def press_keys(self, combo: str) -> None:
    # Validate as a real backend would, so tests catch malformed combinations.
    parse_combo(combo)
    self.actions.append(("press_keys", combo))

  def scroll(self, point: ScreenPoint, dx: int, dy: int) -> None:
    self.actions.append(("scroll", point, dx, dy))
