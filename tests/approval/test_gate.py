from pathlib import Path

import pytest

from fsd.approval.gate import ActionGate, GateRefused
from fsd.approval.store import ApprovalStore
from fsd.platform.base import Rect, ScreenPoint, WindowInfo
from fsd.platform.fake import FakePlatform

APPROVED = "com.example.approved"
UNAPPROVED = "com.example.unapproved"


@pytest.fixture
def store(tmp_path: Path) -> ApprovalStore:
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve(APPROVED)
  return store


def test_click_on_an_approved_window_is_performed(store: ApprovalStore) -> None:
  fake = FakePlatform(windows=[WindowInfo(APPROVED, Rect(0, 0, 500, 500), 0)])
  ActionGate(fake, store).click(ScreenPoint(10, 10))
  assert fake.actions == [("click", ScreenPoint(10, 10))]


def test_click_is_refused_when_an_unapproved_window_occludes_an_approved_one(
  store: ApprovalStore,
) -> None:
  # The filtered frame would show the approved window here, but a real click
  # would land on the window above it.
  fake = FakePlatform(
    windows=[
      WindowInfo(UNAPPROVED, Rect(0, 0, 100, 100), 0),
      WindowInfo(APPROVED, Rect(0, 0, 500, 500), 0),
    ]
  )
  gate = ActionGate(fake, store)
  with pytest.raises(GateRefused) as refusal:
    gate.click(ScreenPoint(50, 50))
  assert refusal.value.owner == UNAPPROVED
  assert refusal.value.action == "click"
  assert fake.actions == []

  gate.click(ScreenPoint(300, 300))
  assert fake.actions == [("click", ScreenPoint(300, 300))]


def test_click_where_no_window_exists_is_refused(store: ApprovalStore) -> None:
  fake = FakePlatform(windows=[WindowInfo(APPROVED, Rect(0, 0, 100, 100), 0)])
  with pytest.raises(GateRefused) as refusal:
    ActionGate(fake, store).click(ScreenPoint(900, 900))
  assert refusal.value.owner is None
  assert fake.actions == []


def test_scroll_is_gated_by_the_window_under_the_point(store: ApprovalStore) -> None:
  fake = FakePlatform(
    windows=[
      WindowInfo(UNAPPROVED, Rect(0, 0, 100, 100), 0),
      WindowInfo(APPROVED, Rect(0, 0, 500, 500), 0),
    ]
  )
  gate = ActionGate(fake, store)
  with pytest.raises(GateRefused):
    gate.scroll(ScreenPoint(50, 50), 0, -3)
  gate.scroll(ScreenPoint(300, 300), 0, -3)
  assert fake.actions == [("scroll", ScreenPoint(300, 300), 0, -3)]


def test_keystrokes_are_gated_by_the_frontmost_app(store: ApprovalStore) -> None:
  fake = FakePlatform(frontmost=UNAPPROVED)
  gate = ActionGate(fake, store)
  with pytest.raises(GateRefused) as refusal:
    gate.type_text("secret")
  assert refusal.value.owner == UNAPPROVED
  with pytest.raises(GateRefused):
    gate.press_keys("cmd+q")
  assert fake.actions == []

  fake.frontmost = APPROVED
  gate.type_text("hello")
  gate.press_keys("cmd+s")
  assert fake.actions == [("type_text", "hello"), ("press_keys", "cmd+s")]


def test_keystrokes_are_refused_when_no_app_is_frontmost(store: ApprovalStore) -> None:
  fake = FakePlatform(frontmost=None)
  with pytest.raises(GateRefused):
    ActionGate(fake, store).type_text("hello")
  assert fake.actions == []


def test_gate_sees_approval_changes_made_after_it_was_created(store: ApprovalStore) -> None:
  fake = FakePlatform(frontmost=UNAPPROVED)
  gate = ActionGate(fake, store)
  store.approve(UNAPPROVED)
  gate.type_text("now allowed")
  store.block(UNAPPROVED)
  with pytest.raises(GateRefused):
    gate.type_text("blocked again")
  assert fake.actions == [("type_text", "now allowed")]


def test_refusal_message_names_the_owner() -> None:
  assert UNAPPROVED in str(GateRefused("click", UNAPPROVED))
  assert "no identifiable app" in str(GateRefused("click", None))
