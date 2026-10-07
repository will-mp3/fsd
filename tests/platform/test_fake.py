import pytest

from fsd.platform.base import CaptureError, Frame, Rect, ScreenPoint, WindowInfo
from fsd.platform.fake import FakePlatform


def _frame(tag: bytes) -> Frame:
  return Frame(png=tag, width=10, height=10, screen_rect=Rect(0, 0, 10, 10))


def test_capture_replays_frames_in_order_and_records_the_filter() -> None:
  fake = FakePlatform(frames=[_frame(b"one"), _frame(b"two")])
  assert fake.capture({"com.example.a"}).png == b"one"
  assert fake.capture({"com.example.a", "com.example.b"}).png == b"two"
  assert fake.capture_requests == [
    frozenset({"com.example.a"}),
    frozenset({"com.example.a", "com.example.b"}),
  ]


def test_capture_fails_clearly_when_frames_run_out() -> None:
  with pytest.raises(CaptureError, match="no recorded frames"):
    FakePlatform().capture({"com.example.a"})


def test_input_is_recorded_not_performed() -> None:
  fake = FakePlatform()
  fake.click(ScreenPoint(1, 2))
  fake.type_text("hello")
  fake.press_keys("cmd+s")
  fake.scroll(ScreenPoint(3, 4), 0, -5)
  assert fake.actions == [
    ("click", ScreenPoint(1, 2)),
    ("type_text", "hello"),
    ("press_keys", "cmd+s"),
    ("scroll", ScreenPoint(3, 4), 0, -5),
  ]


def test_press_keys_rejects_malformed_combinations_like_a_real_backend() -> None:
  fake = FakePlatform()
  with pytest.raises(ValueError):
    fake.press_keys("cmd+")
  assert fake.actions == []


def test_window_owner_uses_front_to_back_order() -> None:
  fake = FakePlatform(
    windows=[
      WindowInfo("com.example.top", Rect(0, 0, 100, 100), 0),
      WindowInfo("com.example.under", Rect(0, 0, 500, 500), 0),
    ]
  )
  assert fake.window_owner_at(ScreenPoint(50, 50)) == "com.example.top"
  assert fake.window_owner_at(ScreenPoint(300, 300)) == "com.example.under"
