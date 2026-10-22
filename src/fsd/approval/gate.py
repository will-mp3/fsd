"""The action gate: the only path from the harness to real input"""

from collections.abc import Callable
from typing import Literal

from fsd.approval.store import ApprovalStore
from fsd.platform.base import Platform, ScreenPoint

RefusalReason = Literal["pointer_target", "keyboard_focus", "focus_changed"]


class GateRefused(Exception):
  def __init__(self, action: str, owner: str | None, reason: RefusalReason) -> None:
    self.action = action
    self.owner = owner
    self.reason = reason
    target = owner if owner is not None else "no identifiable app"
    super().__init__(f"Refused {action}: it would reach {target}, which is not approved.")


class ActionGate:
  """Check current ownership before allowing input.

  Filtered capture can show an approved window even when an unapproved
  window covers it on the real desktop.
  """

  def __init__(self, platform: Platform, store: ApprovalStore) -> None:
    self._platform = platform
    self._store = store

  def click(self, point: ScreenPoint) -> None:
    self._require_pointer_target("click", point)
    self._platform.click(point)

  def scroll(self, point: ScreenPoint, dx: int, dy: int) -> None:
    self._require_pointer_target("scroll", point)
    self._platform.scroll(point, dx, dy)

  def type_text(self, text: str) -> None:
    self._require_keyboard_target("type")
    self._platform.type_text(text)

  def press_keys(self, combo: str) -> None:
    self._require_keyboard_target("key press")
    self._platform.press_keys(combo)

  def type_text_checked(self, text: str, check: Callable[[], None] | None = None) -> None:
    self._platform.type_text_checked(text, self._keyboard_guard("type", check))

  def hold_key(self, key: str, duration_ms: int, check: Callable[[], None] | None = None) -> None:
    self._platform.hold_key(key, duration_ms, self._keyboard_guard("hold", check))

  def _keyboard_guard(self, action: str, check: Callable[[], None] | None) -> Callable[[], None]:
    if check is not None:
      check()
    self._store.refresh()
    owner = self._platform.frontmost_app()
    self._require_approved(action, owner, "keyboard_focus")

    def guard() -> None:
      if check is not None:
        check()
      self._store.refresh()
      current = self._platform.frontmost_app()
      if current != owner:
        raise GateRefused(action, current, "focus_changed")
      self._require_approved(action, current, "keyboard_focus")

    return guard

  def _require_pointer_target(self, action: str, point: ScreenPoint) -> None:
    self._require_approved(action, self._platform.window_owner_at(point), "pointer_target")

  def _require_keyboard_target(self, action: str) -> None:
    self._require_approved(action, self._platform.frontmost_app(), "keyboard_focus")

  def _require_approved(self, action: str, owner: str | None, reason: RefusalReason) -> None:
    if owner is None or not self._store.is_approved(owner):
      raise GateRefused(action, owner, reason)
