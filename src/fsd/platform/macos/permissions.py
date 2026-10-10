"""Checks for the two OS permissions the harness needs."""

from __future__ import annotations

import ApplicationServices
import Quartz

from fsd.platform.base import MissingPermission

_RESTART_NOTE = (
  "Enable it for the terminal application that launches fsd, then quit and reopen that terminal."
)


def check_permissions() -> list[MissingPermission]:
  missing: list[MissingPermission] = []

  # Preflight checks report permission state without requesting access.
  if not Quartz.CGPreflightScreenCaptureAccess():
    missing.append(
      MissingPermission(
        "Screen Recording",
        "System Settings > Privacy & Security > Screen & System Audio Recording. " + _RESTART_NOTE,
      )
    )

  if not ApplicationServices.AXIsProcessTrusted():
    missing.append(
      MissingPermission(
        "Accessibility",
        "System Settings > Privacy & Security > Accessibility. " + _RESTART_NOTE,
      )
    )

  return missing
