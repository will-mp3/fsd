"""Application discovery and app-list merging for macOS"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from fsd.platform.base import AppInfo

# System UI needs explicit approval just like ordinary applications.
SYSTEM_SURFACES: dict[str, str] = {
  "com.apple.dock": "Dock",
  "unidentified:Window Server": "Menu bar (Window Server)",
  "com.apple.systemuiserver": "Menu bar extras (SystemUIServer)",
  "com.apple.Spotlight": "Spotlight",
  "com.apple.controlcenter": "Control Center",
  "com.apple.notificationcenterui": "Notification Center",
  "com.apple.UserNotificationCenter": "System dialogs (UserNotificationCenter)",
  "com.apple.coreservices.uiagent": "System dialogs (CoreServicesUIAgent)",
  "com.apple.SecurityAgent": "System dialogs (SecurityAgent)",
}


def merge_apps(
  installed: Iterable[tuple[str, str]],
  running: Iterable[tuple[str, str]],
  surfaces: Mapping[str, str],
) -> list[AppInfo]:
  """Combine installed and running apps, then append system surfaces."""
  running_pairs = dict(running)
  names = {**dict(installed), **running_pairs}

  apps = [
    AppInfo(bundle_id, name, running=bundle_id in running_pairs)
    for bundle_id, name in names.items()
    if bundle_id not in surfaces
  ]
  apps.sort(key=lambda app: (app.name.casefold(), app.bundle_id))

  apps.extend(
    AppInfo(bundle_id, name, running=True, system_surface=True)
    for bundle_id, name in surfaces.items()
  )
  return apps
