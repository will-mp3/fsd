import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")

from fsd.platform.base import SUPPORTED_KEYS, ScreenPoint  # noqa: E402
from fsd.platform.macos import input as macos_input  # noqa: E402


@pytest.fixture
def posted_events(monkeypatch: pytest.MonkeyPatch) -> list[object]:
  posted: list[object] = []

  def record(tap: int, event: object) -> None:
    assert tap == Quartz.kCGHIDEventTap
    posted.append(event)

  monkeypatch.setattr(Quartz, "CGEventPost", record)
  return posted


@pytest.mark.parametrize("point", [ScreenPoint(0, 0), ScreenPoint(123.5, 234.25)])
def test_click_moves_presses_and_releases_at_the_requested_point(
  posted_events: list[object], point: ScreenPoint
) -> None:
  macos_input.click(point)

  assert [Quartz.CGEventGetType(event) for event in posted_events] == [
    Quartz.kCGEventMouseMoved,
    Quartz.kCGEventLeftMouseDown,
    Quartz.kCGEventLeftMouseUp,
  ]
  for event in posted_events:
    assert tuple(Quartz.CGEventGetLocation(event)) == (point.x, point.y)
    assert Quartz.CGEventGetFlags(event) == 0
  for event in posted_events[1:]:
    assert Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventClickState) == 1


@pytest.mark.parametrize(("dx", "dy"), [(0, 3), (2, 0), (-2, -3)])
def test_scroll_moves_to_target_and_preserves_line_deltas(
  posted_events: list[object], dx: int, dy: int
) -> None:
  point = ScreenPoint(123.5, 234.25)
  macos_input.scroll(point, dx, dy)

  assert [Quartz.CGEventGetType(event) for event in posted_events] == [
    Quartz.kCGEventMouseMoved,
    Quartz.kCGEventScrollWheel,
  ]
  for event in posted_events:
    assert tuple(Quartz.CGEventGetLocation(event)) == (point.x, point.y)
    assert Quartz.CGEventGetFlags(event) == 0
  scroll = posted_events[1]
  assert Quartz.CGEventGetIntegerValueField(scroll, Quartz.kCGScrollWheelEventDeltaAxis1) == dy
  assert Quartz.CGEventGetIntegerValueField(scroll, Quartz.kCGScrollWheelEventDeltaAxis2) == dx
  assert Quartz.CGEventGetIntegerValueField(scroll, Quartz.kCGScrollWheelEventIsContinuous) == 0


@pytest.mark.parametrize(
  "failed_type",
  [Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp],
  ids=["move-fails", "down-fails", "up-fails"],
)
def test_click_creation_failure_posts_nothing(
  monkeypatch: pytest.MonkeyPatch, posted_events: list[object], failed_type: int
) -> None:
  create_event = Quartz.CGEventCreateMouseEvent

  def create(source: object, event_type: int, point: object, button: int) -> object | None:
    if event_type == failed_type:
      return None
    event: object = create_event(source, event_type, point, button)
    return event

  monkeypatch.setattr(Quartz, "CGEventCreateMouseEvent", create)

  with pytest.raises(RuntimeError, match="Could not create mouse event"):
    macos_input.click(ScreenPoint(10, 20))

  assert posted_events == []


@pytest.mark.parametrize(
  ("constructor", "message"),
  [
    ("CGEventCreateMouseEvent", "Could not create mouse event"),
    ("CGEventCreateScrollWheelEvent", "Could not create scroll event"),
  ],
  ids=["move-fails", "scroll-fails"],
)
def test_scroll_creation_failure_posts_nothing(
  monkeypatch: pytest.MonkeyPatch,
  posted_events: list[object],
  constructor: str,
  message: str,
) -> None:
  monkeypatch.setattr(Quartz, constructor, lambda *args: None)

  with pytest.raises(RuntimeError, match=message):
    macos_input.scroll(ScreenPoint(10, 20), 1, -2)

  assert posted_events == []


@pytest.mark.parametrize("operation", ["click", "scroll"])
def test_pointer_actions_clear_inherited_modifiers(
  monkeypatch: pytest.MonkeyPatch, posted_events: list[object], operation: str
) -> None:
  def add_modifiers(constructor: str) -> None:
    create_event = getattr(Quartz, constructor)

    def create(*args: object) -> object:
      event: object = create_event(*args)
      Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskControl)
      return event

    monkeypatch.setattr(Quartz, constructor, create)

  add_modifiers("CGEventCreateMouseEvent")
  add_modifiers("CGEventCreateScrollWheelEvent")

  point = ScreenPoint(10, 20)
  if operation == "click":
    macos_input.click(point)
  else:
    macos_input.scroll(point, 1, -2)

  assert posted_events
  assert all(Quartz.CGEventGetFlags(event) == 0 for event in posted_events)


def test_hold_posts_matching_key_events_and_releases_on_failure(
  posted_events: list[object],
) -> None:
  checks = 0

  def check() -> None:
    nonlocal checks
    checks += 1
    if checks == 2:
      raise RuntimeError("cancel")

  with pytest.raises(RuntimeError, match="cancel"):
    macos_input.hold_key("right", 100, check)

  assert [Quartz.CGEventGetType(event) for event in posted_events] == [
    Quartz.kCGEventKeyDown,
    Quartz.kCGEventKeyUp,
  ]
  assert all(
    Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode) == 124
    for event in posted_events
  )
  assert all(Quartz.CGEventGetFlags(event) == 0 for event in posted_events)


def test_native_key_vocabulary_matches_portable_contract() -> None:
  assert set(macos_input.KEYCODES) == SUPPORTED_KEYS


@pytest.mark.parametrize(
  ("key", "message"),
  [("banana", "Unknown key"), ("cmd+a", "ordinary key")],
)
def test_unsupported_hold_never_posts_input(
  posted_events: list[object], key: str, message: str
) -> None:
  with pytest.raises(ValueError, match=message):
    macos_input.hold_key(key, 100, lambda: None)
  assert posted_events == []


def test_checked_typing_releases_current_character_and_stops_on_cancellation(
  posted_events: list[object],
) -> None:
  def check() -> None:
    if posted_events:
      raise RuntimeError("cancel")

  with pytest.raises(RuntimeError, match="cancel"):
    macos_input.type_text_checked("ab", check)

  assert [Quartz.CGEventGetType(event) for event in posted_events] == [
    Quartz.kCGEventKeyDown,
    Quartz.kCGEventKeyUp,
  ]
  assert all(Quartz.CGEventGetFlags(event) == 0 for event in posted_events)
