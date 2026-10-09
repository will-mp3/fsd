import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

AppKit = pytest.importorskip("AppKit", reason="macOS backend needs pyobjc")

from fsd.platform.base import AppInfo  # noqa: E402
from fsd.platform.macos import apps as macos_apps  # noqa: E402


def _write_app_bundle(directory: Path, name: str, bundle_id: str | None) -> None:
  contents = directory / name / "Contents"
  contents.mkdir(parents=True)
  metadata = {"CFBundlePackageType": "APPL", "CFBundleName": Path(name).stem}
  if bundle_id is not None:
    metadata["CFBundleIdentifier"] = bundle_id
  with (contents / "Info.plist").open("wb") as file:
    plistlib.dump(metadata, file)


def _running_app(policy: int, bundle_id: str | None, name: str | None) -> SimpleNamespace:
  return SimpleNamespace(
    activationPolicy=lambda: policy,
    bundleIdentifier=lambda: bundle_id,
    localizedName=lambda: name,
  )


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
  monkeypatch.setattr(AppKit, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))
  assert macos_apps.frontmost_app() == bundle_id


def test_installed_reads_app_bundles_and_skips_missing_identifiers(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  applications = tmp_path / "Applications"
  utilities = applications / "Utilities"
  _write_app_bundle(applications, "Bravo.app", "com.example.bravo")
  _write_app_bundle(applications, "NoIdentifier.app", None)
  _write_app_bundle(applications, "NotAnApp.bundle", "com.example.other")
  _write_app_bundle(utilities, "Utility.app", "com.example.utility")
  (applications / "Invalid.app").write_text("not a bundle", encoding="utf-8")
  monkeypatch.setattr(
    macos_apps,
    "_APP_DIRECTORIES",
    (applications, utilities, tmp_path / "Missing"),
    raising=False,
  )

  assert macos_apps._installed() == [
    ("com.example.bravo", "Bravo"),
    ("com.example.utility", "Utility"),
  ]


def test_list_apps_combines_discovery_and_excludes_unidentified_or_background_processes(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  _write_app_bundle(tmp_path, "Bravo.app", "com.example.bravo")
  _write_app_bundle(tmp_path, "Installed.app", "com.example.installed")
  monkeypatch.setattr(macos_apps, "_APP_DIRECTORIES", (tmp_path,), raising=False)
  monkeypatch.setattr(macos_apps, "SYSTEM_SURFACES", {"com.apple.dock": "Dock"})
  running = [
    _running_app(0, "com.example.alpha", "alpha"),
    _running_app(0, "com.example.bravo", "Bravo Running"),
    _running_app(0, "com.example.unnamed", None),
    _running_app(0, None, "Unidentified"),
    _running_app(1, "com.example.accessory", "Accessory"),
    _running_app(2, "com.example.agent", "Agent"),
    _running_app(1, "com.apple.dock", "Dock"),
  ]
  workspace = SimpleNamespace(runningApplications=lambda: running)
  monkeypatch.setattr(AppKit, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))

  assert macos_apps.list_apps() == [
    AppInfo("com.example.alpha", "alpha", running=True),
    AppInfo("com.example.bravo", "Bravo Running", running=True),
    AppInfo("com.example.unnamed", "com.example.unnamed", running=True),
    AppInfo("com.example.installed", "Installed", running=False),
    AppInfo("com.apple.dock", "Dock", running=True, system_surface=True),
  ]
