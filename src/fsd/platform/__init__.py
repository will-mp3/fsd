"""Backend selection. This module holds the only OS check in the application."""

from __future__ import annotations

import sys

from fsd.platform.base import MANDATORY_CAPABILITIES, Platform, UnsupportedPlatformError


def require_mandatory(backend: Platform) -> Platform:
  missing = MANDATORY_CAPABILITIES - backend.capabilities
  if missing:
    names = ", ".join(sorted(capability.value for capability in missing))
    raise UnsupportedPlatformError(
      f"This system cannot enforce per-app approval (missing: {names}). "
      "fsd refuses to run without it."
    )
  return backend


def select_backend() -> Platform:
  if sys.platform != "darwin":
    raise UnsupportedPlatformError(
      f"fsd has no backend for '{sys.platform}'. Only macOS is supported at this time"
    )

  # Imported here so the package stays importable where pyobjc is not installed
  from fsd.platform.macos.backend import MacOSPlatform  # type: ignore[import-untyped]

  return require_mandatory(MacOSPlatform())
