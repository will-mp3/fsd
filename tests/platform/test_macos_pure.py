import pytest

pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")

from fsd.platform.base import AppInfo  # noqa: E402
from fsd.platform.macos.apps import merge_apps  # noqa: E402


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
