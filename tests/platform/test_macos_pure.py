import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")

from fsd.platform.base import AppInfo, Rect, WindowInfo  # noqa: E402
from fsd.platform.macos import apps as macos_apps  # noqa: E402
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
