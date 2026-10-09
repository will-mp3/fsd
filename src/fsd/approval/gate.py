"""The action gate: the only path from the harness to real input"""

from fsd.approval.store import ApprovalStore
from fsd.platform.base import Platform, ScreenPoint


class GateRefused(Exception):
  def __init__(self, action: str, owner: str | None) -> None:
    self.action = action
    self.owner = owner
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

  def _require_pointer_target(self, action: str, point: ScreenPoint) -> None:
    self._require_approved(action, self._platform.window_owner_at(point))

  def _require_keyboard_target(self, action: str) -> None:
    self._require_approved(action, self._platform.frontmost_app())

  def _require_approved(self, action: str, owner: str | None) -> None:
    if owner is None or not self._store.is_approved(owner):
      raise GateRefused(action, owner)
