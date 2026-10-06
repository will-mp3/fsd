"""The platform contract: the boundary between the harness and an operating system."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Capability(Enum):
    FILTERED_CAPTURE = "filtered_capture"
    WINDOW_OWNER_LOOKUP = "window_owner_lookup"
    OCR = "ocr"


# Without these two, per-app approval cannot be enforced
MANDATORY_CAPABILITIES = frozenset({Capability.FILTERED_CAPTURE, Capability.WINDOW_OWNER_LOOKUP})

MODIFIERS = frozenset({"cmd", "shift", "alt", "ctrl"})


class PlatformError(Exception):
    """A platform operation failed; the message is safe to show to the user."""


class UnsupportedPlatformError(PlatformError):
    """No backend exists for this system, or the backend lacks a mandatory capability."""


class CaptureError(PlatformError):
    """A frame could not be captured"""


@dataclass(frozen=True)
class ScreenPoint:
    """A point in input coordinates: the space in which clicks land."""

    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def contains(self, point: ScreenPoint) -> bool:
        return self.x <= point.x < self.x + self.width and self.y <= point.y < self.y + self.height


@dataclass(frozen=True)
class AppInfo:
    bundle_id: str
    name: str
    running: bool
    system_surface: bool = False


@dataclass(frozen=True)
class WindowInfo:
    owner: str
    bounds: Rect
    layer: int


@dataclass(frozen=True)
class Frame:
    """A captured image plus the screen region it covers.

    The backend supplies screen_rect so callers can use normalised coordinates
    without knowing the display scaling.
    """

    png: bytes
    width: int
    height: int
    screen_rect: Rect

    def to_screen(self, nx: float, ny: float) -> ScreenPoint:
        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            raise ValueError(f"Normalised point ({nx}, {ny}) is outside the frame.")
        return ScreenPoint(
            self.screen_rect.x + nx * self.screen_rect.width,
            self.screen_rect.y + ny * self.screen_rect.height,
        )


@dataclass(frozen=True)
class MissingPermission:
    name: str
    how_to_grant: str


@dataclass(frozen=True)
class KeyCombo:
    modifiers: frozenset[str]
    key: str


def parse_combo(combo: str) -> KeyCombo:
    """Parse 'cmd+shift+a' into modifiers and exactly one non-modifier key."""
    parts = [part.strip().lower() for part in combo.split("+")]
    if not all(parts):
        raise ValueError(f"Malformed key combination: {combo!r}.")

    *modifiers, key = parts
    unknown = set(modifiers) - MODIFIERS
    if unknown:
        raise ValueError(
            f"Unknown modifier in {combo!r}: {', '.join(sorted(unknown))}. "
            f"Use {', '.join(sorted(MODIFIERS))}."
        )
    if key in MODIFIERS:
        raise ValueError(f"Key combination {combo!r} has no non-modifier key.")

    return KeyCombo(frozenset(modifiers), key)


def topmost_owner(windows: Sequence[WindowInfo], point: ScreenPoint) -> str | None:
    """Owner of the first window containing the point; windows are ordered front to back."""
    for window in windows:
        if window.bounds.contains(point):
            return window.owner
    return None


class Platform(Protocol):
    """Synchronous OS operations; callers preserve the backend's main-thread requirements."""

    capabilities: frozenset[Capability]

    def check_permissions(self) -> list[MissingPermission]: ...

    def list_apps(self) -> list[AppInfo]: ...

    def frontmost_app(self) -> str | None: ...

    def capture(self, bundle_ids: Collection[str]) -> Frame: ...

    def windows(self) -> list[WindowInfo]: ...

    def window_owner_at(self, point: ScreenPoint) -> str | None: ...

    def click(self, point: ScreenPoint) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press_keys(self, combo: str) -> None: ...

    def scroll(self, point: ScreenPoint, dx: int, dy: int) -> None: ...
