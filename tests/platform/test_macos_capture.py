import struct
import threading
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

Foundation = pytest.importorskip("Foundation", reason="macOS backend needs pyobjc")
AppKit = pytest.importorskip("AppKit", reason="macOS backend needs pyobjc")
Quartz = pytest.importorskip("Quartz", reason="macOS backend needs pyobjc")
ScreenCaptureKit = pytest.importorskip("ScreenCaptureKit", reason="macOS backend needs pyobjc")

from fsd.platform.base import CaptureError, Rect, ScreenPoint  # noqa: E402


@pytest.fixture
def capture_module() -> ModuleType:
  from fsd.platform.macos import capture

  return capture


def test_wait_for_returns_a_result_even_if_callback_runs_immediately(
  capture_module: ModuleType,
) -> None:
  expected = object()

  def start(handler: Callable[[object, object], None]) -> None:
    handler(expected, None)

  assert capture_module._wait_for(start, "Test capture") is expected


def test_wait_for_waits_for_a_callback_on_another_thread(capture_module: ModuleType) -> None:
  expected = object()
  workers: list[threading.Timer] = []

  def start(handler: Callable[[object, object], None]) -> None:
    worker = threading.Timer(0.01, handler, args=(expected, None))
    workers.append(worker)
    worker.start()

  try:
    assert capture_module._wait_for(start, "Test capture") is expected
  finally:
    for worker in workers:
      worker.join()


def test_wait_for_converts_native_errors_to_capture_errors(capture_module: ModuleType) -> None:
  error = Foundation.NSError.errorWithDomain_code_userInfo_(
    "fsd.test", 1, {Foundation.NSLocalizedDescriptionKey: "Capture was denied"}
  )

  def start(handler: Callable[[object, object], None]) -> None:
    handler(None, error)

  with pytest.raises(CaptureError, match="Test capture failed: Capture was denied"):
    capture_module._wait_for(start, "Test capture")


def test_wait_for_times_out_if_callback_never_arrives(
  monkeypatch: pytest.MonkeyPatch, capture_module: ModuleType
) -> None:
  monkeypatch.setattr(capture_module, "_TIMEOUT_SECONDS", 0.01)

  def start(handler: Callable[[object, object], None]) -> None:
    pass

  with pytest.raises(CaptureError, match="Test capture did not respond"):
    capture_module._wait_for(start, "Test capture")


@pytest.fixture
def capture_selection(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
  main = SimpleNamespace(displayID=lambda: 42)
  secondary = SimpleNamespace(displayID=lambda: 99)
  approved = SimpleNamespace(bundleIdentifier=lambda: "com.example.approved")
  blocked = SimpleNamespace(bundleIdentifier=lambda: "com.example.blocked")
  unknown = SimpleNamespace(bundleIdentifier=lambda: None)
  state = SimpleNamespace(
    displays=[secondary, main],
    applications=[blocked, approved, unknown],
    main=main,
    approved=approved,
    calls=[],
    result=object(),
  )

  class FilterBuilder:
    def initWithDisplay_includingApplications_exceptingWindows_(
      self, display: object, applications: list[Any], exceptions: list[Any]
    ) -> object | None:
      state.calls.append((display, applications, exceptions))
      result: object | None = state.result
      return result

  monkeypatch.setattr(Quartz, "CGMainDisplayID", lambda: 42)
  monkeypatch.setattr(ScreenCaptureKit, "SCContentFilter", SimpleNamespace(alloc=FilterBuilder))
  state.content = SimpleNamespace(
    displays=lambda: state.displays,
    applications=lambda: state.applications,
  )
  return state


def test_content_filter_selects_main_display_and_only_approved_apps(
  capture_module: ModuleType, capture_selection: SimpleNamespace
) -> None:
  state = capture_selection

  content_filter, display_id = capture_module._content_filter(
    state.content, {"com.example.approved"}
  )

  assert content_filter is state.result
  assert display_id == 42
  assert state.calls == [(state.main, [state.approved], [])]


@pytest.mark.parametrize(
  "approved_ids",
  [set(), {"com.example.not-running"}, {"unidentified:Window Server"}],
  ids=["none-approved", "approved-app-absent", "unidentified-owner"],
)
def test_content_filter_does_not_broaden_an_empty_application_selection(
  capture_module: ModuleType, capture_selection: SimpleNamespace, approved_ids: set[str]
) -> None:
  state = capture_selection

  capture_module._content_filter(state.content, approved_ids)

  assert state.calls == [(state.main, [], [])]


def test_content_filter_refuses_to_substitute_another_display(
  capture_module: ModuleType, capture_selection: SimpleNamespace
) -> None:
  state = capture_selection
  state.displays = [state.displays[0]]

  with pytest.raises(CaptureError, match="main display is not available"):
    capture_module._content_filter(state.content, {"com.example.approved"})

  assert state.calls == []


def test_content_filter_reports_native_initialization_failure(
  capture_module: ModuleType, capture_selection: SimpleNamespace
) -> None:
  state = capture_selection
  state.result = None

  with pytest.raises(CaptureError, match="Could not create the capture filter"):
    capture_module._content_filter(state.content, {"com.example.approved"})


@pytest.fixture
def native_image() -> object:
  pixels = bytes([255, 0, 0, 255] * 8)
  provider = Quartz.CGDataProviderCreateWithData(None, pixels, len(pixels), None)
  image: object = Quartz.CGImageCreate(
    4,
    2,
    8,
    32,
    16,
    Quartz.CGColorSpaceCreateDeviceRGB(),
    Quartz.kCGImageAlphaPremultipliedLast,
    provider,
    None,
    False,
    Quartz.kCGRenderingIntentDefault,
  )
  assert image is not None
  return image


def test_frame_from_image_encodes_png_and_preserves_pixel_and_screen_dimensions(
  capture_module: ModuleType, native_image: object
) -> None:
  bounds = Rect(10, 20, 2, 1)

  frame = capture_module._frame_from_image(native_image, bounds)

  assert isinstance(frame.png, bytes)
  assert frame.png[:8] == b"\x89PNG\r\n\x1a\n"
  assert struct.unpack(">II", frame.png[16:24]) == (4, 2)
  assert (frame.width, frame.height) == (4, 2)
  assert frame.screen_rect == bounds
  assert frame.to_screen(0.5, 0.5) == ScreenPoint(11, 20.5)


def test_frame_from_image_rejects_missing_image(capture_module: ModuleType) -> None:
  with pytest.raises(CaptureError, match="Capture returned no image"):
    capture_module._frame_from_image(None, Rect(0, 0, 2, 1))


@pytest.mark.parametrize(
  ("stage", "message"),
  [
    ("representation", "could not be prepared for PNG encoding"),
    ("png", "could not be encoded as PNG"),
  ],
)
def test_frame_from_image_reports_encoding_failures(
  monkeypatch: pytest.MonkeyPatch,
  capture_module: ModuleType,
  native_image: object,
  stage: str,
  message: str,
) -> None:
  representation = (
    None
    if stage == "representation"
    else SimpleNamespace(representationUsingType_properties_=lambda *args: None)
  )
  builder = SimpleNamespace(initWithCGImage_=lambda image: representation)
  monkeypatch.setattr(AppKit, "NSBitmapImageRep", SimpleNamespace(alloc=lambda: builder))

  with pytest.raises(CaptureError, match=message):
    capture_module._frame_from_image(native_image, Rect(0, 0, 2, 1))
