import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")

from fsd.platform import select_backend  # noqa: E402
from fsd.platform.base import Platform, Rect, ScreenPoint, WindowInfo  # noqa: E402
from fsd.platform.macos import windows  # noqa: E402


@pytest.fixture
def desktop(monkeypatch: pytest.MonkeyPatch) -> list[WindowInfo]:
  window_list: list[WindowInfo] = []
  monkeypatch.setattr(Quartz, "CGMainDisplayID", lambda: 42)

  def bounds(display_id: int) -> object:
    assert display_id == 42
    return Quartz.CGRectMake(0, 0, 1000, 800)

  monkeypatch.setattr(Quartz, "CGDisplayBounds", bounds)
  monkeypatch.setattr(windows, "list_windows", lambda: list(window_list))
  return window_list


@pytest.fixture
def backend(desktop: list[WindowInfo]) -> Platform:
  return select_backend()


def test_select_backend_constructs_the_macos_implementation(backend: Platform) -> None:
  from fsd.platform.macos.backend import MacOSPlatform

  assert isinstance(backend, MacOSPlatform)


def test_window_owner_uses_the_frontmost_window_at_the_point(
  backend: Platform, desktop: list[WindowInfo]
) -> None:
  desktop.extend(
    [
      WindowInfo("com.example.covering", Rect(0, 0, 50, 50), 0),
      WindowInfo("com.example.behind", Rect(0, 0, 500, 500), 0),
    ]
  )

  assert backend.window_owner_at(ScreenPoint(25, 25)) == "com.example.covering"
  assert backend.window_owner_at(ScreenPoint(100, 100)) == "com.example.behind"


def test_window_owner_is_none_where_no_window_exists(
  backend: Platform, desktop: list[WindowInfo]
) -> None:
  desktop.append(WindowInfo("com.example.app", Rect(0, 0, 50, 50), 0))

  assert backend.window_owner_at(ScreenPoint(900, 700)) is None


@pytest.mark.parametrize(
  "point",
  [ScreenPoint(-1, 20), ScreenPoint(1000, 20), ScreenPoint(20, -1), ScreenPoint(20, 800)],
  ids=["left", "right", "above", "below"],
)
def test_window_owner_is_none_outside_main_display_even_if_a_window_contains_the_point(
  backend: Platform, desktop: list[WindowInfo], point: ScreenPoint
) -> None:
  desktop.append(WindowInfo("com.example.spanning", Rect(-100, -100, 2000, 2000), 0))

  assert backend.window_owner_at(point) is None


def test_window_owner_lookup_observes_changes_between_calls(
  backend: Platform, desktop: list[WindowInfo]
) -> None:
  desktop.append(WindowInfo("com.example.first", Rect(0, 0, 500, 500), 0))
  point = ScreenPoint(10, 10)
  assert backend.window_owner_at(point) == "com.example.first"

  desktop.insert(0, WindowInfo("com.example.new-frontmost", Rect(0, 0, 500, 500), 0))

  assert backend.window_owner_at(point) == "com.example.new-frontmost"
