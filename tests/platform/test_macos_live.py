"""Opt-in desktop checks. Finder is activated briefly, then the original app is restored."""

import struct
import subprocess
import time

import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")
AppKit = pytest.importorskip("AppKit", reason="macOS backend needs pyobjc")

from fsd.platform import select_backend  # noqa: E402
from fsd.platform.base import Platform, Rect, ScreenPoint  # noqa: E402

pytestmark = pytest.mark.live

FINDER = "com.apple.finder"


@pytest.fixture
def live_platform() -> Platform:
  platform = select_backend()
  missing = platform.check_permissions()
  if missing:
    details = "\n".join(f"{permission.name}: {permission.how_to_grant}" for permission in missing)
    pytest.fail(f"Desktop tests need OS permissions:\n{details}", pytrace=False)
  return platform


def test_permissions_are_granted(live_platform: Platform) -> None:
  assert live_platform.check_permissions() == []


def test_capture_returns_a_png_at_display_pixel_size(live_platform: Platform) -> None:
  display = Quartz.CGMainDisplayID()
  mode = Quartz.CGDisplayCopyDisplayMode(display)
  assert mode is not None
  bounds = Quartz.CGDisplayBounds(display)

  frame = live_platform.capture({FINDER})

  assert frame.png[:8] == b"\x89PNG\r\n\x1a\n"
  assert struct.unpack(">II", frame.png[16:24]) == (frame.width, frame.height)
  assert (frame.width, frame.height) == (
    Quartz.CGDisplayModeGetPixelWidth(mode),
    Quartz.CGDisplayModeGetPixelHeight(mode),
  )
  assert frame.screen_rect == Rect(
    float(bounds.origin.x),
    float(bounds.origin.y),
    float(bounds.size.width),
    float(bounds.size.height),
  )


def test_empty_approval_capture_is_opaque_black(live_platform: Platform) -> None:
  frame = live_platform.capture(set())
  bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(frame.png)
  assert bitmap is not None
  assert bitmap.bitsPerSample() == 8
  assert not bitmap.isPlanar()
  samples = int(bitmap.samplesPerPixel())
  assert samples in (1, 2, 3, 4)

  pixel = bytearray(samples)
  if bitmap.hasAlpha():
    alpha_first = bool(bitmap.bitmapFormat() & AppKit.NSAlphaFirstBitmapFormat)
    pixel[0 if alpha_first else -1] = 255

  width = int(bitmap.pixelsWide())
  height = int(bitmap.pixelsHigh())
  stride = int(bitmap.bytesPerRow())
  raw = memoryview(bitmap.bitmapData()).cast("B")
  assert len(raw) >= stride * height
  expected_row = bytes(pixel) * width
  for row in range(height):
    start = row * stride
    if raw[start : start + width * samples] != expected_row:
      pytest.fail(f"Empty-approval capture has nonblack or nonopaque pixels in row {row}.")


def test_frontmost_app_tracks_a_real_app_switch(live_platform: Platform) -> None:
  original = live_platform.frontmost_app()
  assert original is not None
  if original == FINDER:
    pytest.skip("Start the test with your terminal frontmost so an app switch can be verified.")

  try:
    subprocess.run(["open", "-b", FINDER], check=True, timeout=10)
    time.sleep(1.0)
    assert live_platform.frontmost_app() == FINDER
  finally:
    subprocess.run(["open", "-b", original], check=True, timeout=10)
    time.sleep(1.0)
  assert live_platform.frontmost_app() == original


def test_window_owner_lookup_agrees_with_the_window_list(live_platform: Platform) -> None:
  bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
  left = float(bounds.origin.x)
  top = float(bounds.origin.y)
  right = left + float(bounds.size.width)
  bottom = top + float(bounds.size.height)

  # The global window list may start with a window on another display.
  for window in live_platform.windows():
    x1 = max(left, window.bounds.x)
    y1 = max(top, window.bounds.y)
    x2 = min(right, window.bounds.x + window.bounds.width)
    y2 = min(bottom, window.bounds.y + window.bounds.height)
    if x1 < x2 and y1 < y2:
      centre = ScreenPoint((x1 + x2) / 2, (y1 + y2) / 2)
      assert live_platform.window_owner_at(centre) == window.owner
      return

  pytest.fail("No visible window intersects the main display.")
