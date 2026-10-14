from collections.abc import Callable
from pathlib import Path

import pytest

from fsd.approval.gate import ActionGate, GateRefused
from fsd.approval.store import ApprovalStore, ApprovalStoreError
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


def _run_checked(gate: ActionGate, operation: str, check: Callable[[], None] | None = None) -> None:
  if operation == "type":
    gate.type_text_checked("ab", check)
  else:
    gate.hold_key("right", 100, check)


@pytest.mark.parametrize("operation", ["type", "hold"])
def test_checked_action_accepts_external_approval(tmp_path: Path, operation: str) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  fake = FakePlatform(frontmost="one")
  ApprovalStore(path).approve("one")

  _run_checked(ActionGate(fake, store), operation)

  expected = (
    [("type_character", "a"), ("type_character", "b")]
    if operation == "type"
    else [("hold_key", "right", 100)]
  )
  assert fake.actions == expected


@pytest.mark.parametrize("operation", ["type", "hold"])
@pytest.mark.parametrize("owner", [None, "unapproved"])
def test_checked_action_refuses_unapproved_target_without_input(
  tmp_path: Path, operation: str, owner: str | None
) -> None:
  store = ApprovalStore(tmp_path / "approvals.json")
  fake = FakePlatform(frontmost=owner)

  with pytest.raises(GateRefused):
    _run_checked(ActionGate(fake, store), operation)

  assert fake.actions == []


@pytest.mark.parametrize("operation", ["type", "hold"])
def test_checked_action_honors_initial_cancellation(tmp_path: Path, operation: str) -> None:
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve("one")
  fake = FakePlatform(frontmost="one")
  cancellation = RuntimeError("cancelled")

  def cancel() -> None:
    raise cancellation

  with pytest.raises(RuntimeError, match="cancelled") as caught:
    _run_checked(ActionGate(fake, store), operation, cancel)

  assert caught.value is cancellation
  assert fake.actions == []


@pytest.mark.parametrize("operation", ["type", "hold"])
@pytest.mark.parametrize("change", ["focus", "revoke", "corrupt", "cancel"])
def test_checked_action_rechecks_during_execution(
  tmp_path: Path, operation: str, change: str
) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  store.approve("one")
  store.approve("two")
  fake = FakePlatform(frontmost="one")

  def change_state() -> None:
    if not fake.actions:
      return
    if change == "focus":
      fake.frontmost = "two"
    elif change == "revoke":
      ApprovalStore(path).block("one")
    elif change == "corrupt":
      path.write_text("invalid json", encoding="utf-8")
    else:
      raise RuntimeError("cancelled")

  expected_error = {
    "focus": GateRefused,
    "revoke": GateRefused,
    "corrupt": ApprovalStoreError,
    "cancel": RuntimeError,
  }[change]
  with pytest.raises(expected_error):
    _run_checked(ActionGate(fake, store), operation, change_state)

  expected = [("type_character", "a")] if operation == "type" else [("hold_key", "right", 100)]
  assert fake.actions == expected
