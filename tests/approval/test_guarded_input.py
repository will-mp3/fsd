from collections.abc import Callable
from pathlib import Path

import pytest

from fsd.approval.gate import ActionGate, GateRefused
from fsd.approval.store import ApprovalStore
from fsd.platform.fake import FakePlatform


def test_hold_stops_on_focus_change_even_to_approved_app(tmp_path: Path) -> None:
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve("one")
  store.approve("two")

  class Switching(FakePlatform):
    def hold_key(self, key: str, duration_ms: int, check: Callable[[], None]) -> None:
      check()
      self.frontmost = "two"
      check()

  fake = Switching(frontmost="one")
  with pytest.raises(GateRefused):
    ActionGate(fake, store).hold_key("right", 100)


def test_checked_typing_stops_after_revocation(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  store.approve("one")
  fake = FakePlatform(frontmost="one")
  checks = 0

  def change_approval() -> None:
    nonlocal checks
    checks += 1
    if checks == 3:
      ApprovalStore(path).block("one")

  with pytest.raises(GateRefused):
    ActionGate(fake, store).type_text_checked("secret", change_approval)
  assert fake.actions == [("type_character", "s")]


def test_refresh_observes_external_approval(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  ApprovalStore(path).approve("one")
  store.refresh()
  assert store.is_approved("one")
