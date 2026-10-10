import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")

from fsd.platform.base import AppInfo, Rect, WindowInfo  # noqa: E402
from fsd.platform.macos import apps as macos_apps  # noqa: E402
from fsd.platform.macos import input as macos_input  # noqa: E402
from fsd.platform.macos import windows as macos_windows  # noqa: E402
from fsd.platform.macos.apps import merge_apps  # noqa: E402
from fsd.platform.macos.windows import window_from_entry  # noqa: E402


def _entry(pid: int, *, alpha: float = 1.0, layer: int = 0, name: str = "App") -> dict[str, object]:
  return {
    "kCGWindowOwnerPID": pid,
    "kCGWindowOwnerName": name,
    "kCGWindowLayer": layer,
    "kCGWindowAlpha": alpha,
    "kCGWindowBounds": {"X": 10, "Y": 20, "Width": 300, "Height": 200},
  }


def _lookup(pid: int) -> str | None:
  return {1: "com.example.app"}.get(pid)


def _stub_window_query(
  monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, object]] | None
) -> None:
  def query(options: int, relative_to: int) -> list[dict[str, object]] | None:
    assert options == (
      Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    )
    assert relative_to == Quartz.kCGNullWindowID
    return entries

  monkeypatch.setattr(Quartz, "CGWindowListCopyWindowInfo", query)
  monkeypatch.setattr(macos_windows, "bundle_id_for_pid", _lookup, raising=False)


def test_merge_marks_running_apps_and_lists_system_surfaces_last() -> None:
  apps = merge_apps(
    installed=[("com.b", "Bravo"), ("com.a", "alpha")],
    running=[("com.b", "Bravo"), ("com.c", "Charlie")],
    surfaces={"com.apple.dock": "Dock"},
  )
  assert apps == [
    AppInfo("com.a", "alpha", running=False),
    AppInfo("com.b", "Bravo", running=True),
    AppInfo("com.c", "Charlie", running=True),
    AppInfo("com.apple.dock", "Dock", running=True, system_surface=True),
  ]


def test_merge_does_not_list_a_system_surface_twice() -> None:
  apps = merge_apps(
    installed=[],
    running=[("com.apple.dock", "Dock")],
    surfaces={"com.apple.dock": "Dock"},
  )
  assert apps == [AppInfo("com.apple.dock", "Dock", running=True, system_surface=True)]


def test_spec_system_surfaces_are_listed_without_ordinary_apps() -> None:
  apps = merge_apps(installed=[], running=[], surfaces=macos_apps.SYSTEM_SURFACES)
  names = " ".join(app.name for app in apps)
  for surface in ("Dock", "Menu bar", "Spotlight", "Control Center", "System dialogs"):
    assert surface in names
  assert all(app.system_surface for app in apps)


def test_window_entry_becomes_window_info() -> None:
  assert window_from_entry(_entry(1, layer=25), _lookup) == WindowInfo(
    "com.example.app", Rect(10.0, 20.0, 300.0, 200.0), 25
  )


def test_fully_transparent_window_is_ignored() -> None:
  assert window_from_entry(_entry(1, alpha=0.0), _lookup) is None


def test_owner_without_bundle_identifier_gets_an_unidentified_owner() -> None:
  window = window_from_entry(_entry(99, name="Window Server"), _lookup)
  assert window is not None
  assert window.owner == "unidentified:Window Server"


def test_list_windows_preserves_front_to_back_order_and_unidentified_owners(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  _stub_window_query(
    monkeypatch,
    [_entry(1, alpha=0.0), _entry(99, name="Unknown App"), _entry(1)],
  )
  assert macos_windows.list_windows() == [
    WindowInfo("unidentified:Unknown App", Rect(10.0, 20.0, 300.0, 200.0), 0),
    WindowInfo("com.example.app", Rect(10.0, 20.0, 300.0, 200.0), 0),
  ]


@pytest.mark.parametrize("entries", [[], None], ids=["no-windows", "no-window-server"])
def test_list_windows_handles_empty_native_results(
  monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, object]] | None
) -> None:
  _stub_window_query(monkeypatch, entries)
  assert macos_windows.list_windows() == []


@pytest.mark.parametrize(
  ("text", "expected"),
  [
    ("", 0),
    ("abc", 3),
    ("\u00e9", 1),
    ("e\u0301", 2),
    ("\U0001d11e", 2),
    ("a\U0001d11eb", 4),
  ],
  ids=["empty", "ascii", "accented", "combining", "surrogate-pair", "mixed"],
)
def test_utf16_length_counts_code_units(text: str, expected: int) -> None:
  from fsd.platform.macos.input import utf16_length

  assert utf16_length(text) == expected


@pytest.fixture
def posted_keyboard_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int, int, int]]:
  posted: list[tuple[int, int, int, int]] = []

  def record(tap: int, event: object) -> None:
    posted.append(
      (
        tap,
        int(Quartz.CGEventGetType(event)),
        int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)),
        int(Quartz.CGEventGetFlags(event)),
      )
    )

  monkeypatch.setattr(Quartz, "CGEventPost", record)
  return posted


@pytest.mark.parametrize(
  ("combo", "keycode", "flags"),
  [
    ("Cmd+Shift+A", 0, Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift),
    ("ctrl+alt+left", 123, Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate),
    ("z", 6, 0),
    ("0", 29, 0),
    ("9", 25, 0),
    ("return", 36, 0),
    ("tab", 48, 0),
    ("space", 49, 0),
    ("escape", 53, 0),
    ("delete", 51, 0),
    ("right", 124, 0),
    ("up", 126, 0),
    ("down", 125, 0),
  ],
)
def test_press_keys_posts_matching_down_and_up_events(
  posted_keyboard_events: list[tuple[int, int, int, int]],
  combo: str,
  keycode: int,
  flags: int,
) -> None:
  macos_input.press_keys(combo)

  assert posted_keyboard_events == [
    (Quartz.kCGHIDEventTap, Quartz.kCGEventKeyDown, keycode, flags),
    (Quartz.kCGHIDEventTap, Quartz.kCGEventKeyUp, keycode, flags),
  ]


@pytest.mark.parametrize("combo", ["cmd+nosuchkey", "hyper+a", "cmd+", "cmd", ""])
def test_press_keys_rejects_invalid_combinations_without_posting(
  posted_keyboard_events: list[tuple[int, int, int, int]], combo: str
) -> None:
  with pytest.raises(ValueError):
    macos_input.press_keys(combo)

  assert posted_keyboard_events == []


@pytest.mark.parametrize("failed_key_down", [True, False], ids=["down-fails", "up-fails"])
def test_press_keys_rejects_event_creation_failure_before_posting(
  monkeypatch: pytest.MonkeyPatch,
  posted_keyboard_events: list[tuple[int, int, int, int]],
  failed_key_down: bool,
) -> None:
  create_event = Quartz.CGEventCreateKeyboardEvent

  def create(source: object, keycode: int, key_down: bool) -> object | None:
    if key_down == failed_key_down:
      return None
    event: object = create_event(source, keycode, key_down)
    return event

  monkeypatch.setattr(Quartz, "CGEventCreateKeyboardEvent", create)

  with pytest.raises(RuntimeError, match="Could not create keyboard event"):
    macos_input.press_keys("cmd+a")

  assert posted_keyboard_events == []
