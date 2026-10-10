import threading
from collections.abc import Callable
from types import ModuleType

import pytest

Foundation = pytest.importorskip("Foundation", reason="macOS backend needs pyobjc")

from fsd.platform.base import CaptureError  # noqa: E402


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
