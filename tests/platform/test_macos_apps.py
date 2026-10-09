from types import SimpleNamespace

import pytest

AppKit = pytest.importorskip("AppKit", reason="macOS backend needs pyobjc")

from fsd.platform.macos import apps as macos_apps  # noqa: E402


@pytest.mark.parametrize(
  ("present", "bundle_id"),
  [(True, "com.example.app"), (True, None), (False, None)],
  ids=["identified", "no-bundle-id", "no-app"],
)
def test_bundle_id_for_pid_handles_unidentified_apps(
  monkeypatch: pytest.MonkeyPatch, present: bool, bundle_id: str | None
) -> None:
  app = SimpleNamespace(bundleIdentifier=lambda: bundle_id) if present else None
  monkeypatch.setattr(
    AppKit,
    "NSRunningApplication",
    SimpleNamespace(
      runningApplicationWithProcessIdentifier_=lambda pid: app if pid == 42 else None
    ),
  )
  assert macos_apps.bundle_id_for_pid(42) == bundle_id


@pytest.mark.parametrize(
  ("present", "bundle_id"),
  [(True, "com.example.frontmost"), (True, None), (False, None)],
  ids=["identified", "no-bundle-id", "no-app"],
)
def test_frontmost_app_handles_unidentified_apps(
  monkeypatch: pytest.MonkeyPatch, present: bool, bundle_id: str | None
) -> None:
  app = SimpleNamespace(bundleIdentifier=lambda: bundle_id) if present else None
  workspace = SimpleNamespace(frontmostApplication=lambda: app)
  monkeypatch.setattr(
    AppKit, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace)
  )
  assert macos_apps.frontmost_app() == bundle_id
