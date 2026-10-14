import pytest

from fsd.platform.base import MAX_HOLD_MS, CaptureError, Frame, Rect, ScreenPoint, WindowInfo
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


def test_checked_typing_records_each_character() -> None:
  fake = FakePlatform()
  fake.type_text_checked("ab", lambda: None)
  assert fake.actions == [("type_character", "a"), ("type_character", "b")]


def test_checked_typing_stops_before_next_character_when_guard_refuses() -> None:
  fake = FakePlatform()

  def check() -> None:
    if fake.actions:
      raise RuntimeError("cancelled")

  with pytest.raises(RuntimeError, match="cancelled"):
    fake.type_text_checked("ab", check)
  assert fake.actions == [("type_character", "a")]


@pytest.mark.parametrize("operation", ["type_text_checked", "hold_key"])
def test_checked_input_initial_refusal_records_nothing(operation: str) -> None:
  fake = FakePlatform()

  def refuse() -> None:
    raise RuntimeError("refused")

  with pytest.raises(RuntimeError, match="refused"):
    if operation == "type_text_checked":
      fake.type_text_checked("ab", refuse)
    else:
      fake.hold_key("right", 100, refuse)
  assert fake.actions == []


@pytest.mark.parametrize("duration_ms", [1, MAX_HOLD_MS])
def test_hold_records_normalized_key_and_duration(duration_ms: int) -> None:
  fake = FakePlatform()
  fake.hold_key("RIGHT", duration_ms, lambda: None)
  assert fake.actions == [("hold_key", "right", duration_ms)]


def test_hold_propagates_refusal_after_recording() -> None:
  fake = FakePlatform()

  def check() -> None:
    if fake.actions:
      raise RuntimeError("cancelled")

  with pytest.raises(RuntimeError, match="cancelled"):
    fake.hold_key("right", 100, check)
  assert fake.actions == [("hold_key", "right", 100)]


@pytest.mark.parametrize(
  ("key", "duration_ms"),
  [
    ("banana", 100),
    ("cmd+a", 100),
    ("right", 0),
    ("right", -1),
    ("right", MAX_HOLD_MS + 1),
    ("right", True),
    ("right", 1.5),
  ],
)
def test_invalid_hold_never_checks_or_records(key: str, duration_ms: int) -> None:
  fake = FakePlatform()

  def unexpected_check() -> None:
    pytest.fail("Invalid input should be rejected before consulting the guard")

  with pytest.raises(ValueError):
    fake.hold_key(key, duration_ms, unexpected_check)
  assert fake.actions == []
