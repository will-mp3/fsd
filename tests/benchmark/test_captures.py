import io
from copy import deepcopy

import pytest
from PIL import Image

from fsd.benchmark.contracts import BenchmarkError, FrameGeometry
from fsd.benchmark.measure import TrialCollector
from fsd.platform.base import Frame, Rect
from tests.benchmark.helpers import step_event


def test_distinct_captures_count_even_when_pixels_are_identical() -> None:
  collector = TrialCollector()
  first = step_event(0, attempts=(("decision", "completed"),))
  second = step_event(1, attempts=(), outcome="interrupted")
  original = deepcopy(first)

  collector.observe(first)
  first_summary = collector.measurements(duration_seconds=1.0)
  assert first_summary.captured_steps == 1
  assert collector.geometry == FrameGeometry(
    width=100, height=100, screen_rect=Rect(0.0, 0.0, 50.0, 50.0)
  )

  collector.observe(second)

  assert collector.measurements(duration_seconds=2.0).captured_steps == 2
  assert collector.measurements(duration_seconds=2.0).performed_actions == 0
  assert first_summary.captured_steps == 1
  assert first == original


def test_duplicate_capture_is_rejected_without_changing_measurements() -> None:
  collector = TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  collector.observe(event)
  before = collector.measurements(duration_seconds=1.0)

  with pytest.raises(BenchmarkError, match="[Dd]uplicate"):
    collector.observe(event)

  assert collector.measurements(duration_seconds=1.0) == before
  assert collector.termination is None
  collector.observe(step_event(1, attempts=(), outcome="interrupted"))
  assert collector.measurements(duration_seconds=2.0).captured_steps == 2


@pytest.mark.parametrize(
  ("width", "height", "screen_rect"),
  [
    (100, 100, Rect(1.0, 0.0, 50.0, 50.0)),
    (100, 100, Rect(0.0, 1.0, 50.0, 50.0)),
    (100, 100, Rect(0.0, 0.0, 100.0, 50.0)),
    (100, 100, Rect(0.0, 0.0, 50.0, 100.0)),
    (200, 100, Rect(0.0, 0.0, 50.0, 50.0)),
    (100, 200, Rect(0.0, 0.0, 50.0, 50.0)),
  ],
  ids=("origin-x", "origin-y", "width", "height", "pixel-width", "pixel-height"),
)
def test_geometry_change_does_not_consume_the_step(
  width: int,
  height: int,
  screen_rect: Rect,
) -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=(("decision", "completed"),)))
  before = collector.measurements(duration_seconds=1.0)
  buffer = io.BytesIO()
  Image.new("L", (width, height)).save(buffer, format="PNG")
  changed = step_event(1, attempts=(), frame=Frame(buffer.getvalue(), width, height, screen_rect))

  with pytest.raises(BenchmarkError, match="[Gg]eometry"):
    collector.observe(changed)

  assert collector.measurements(duration_seconds=1.0) == before
  assert collector.geometry == FrameGeometry(
    width=100, height=100, screen_rect=Rect(0.0, 0.0, 50.0, 50.0)
  )
  assert collector.run_id == "run"
  assert collector.termination is None
  collector.observe(step_event(1, attempts=(), outcome="interrupted"))
  assert collector.measurements(duration_seconds=2.0).captured_steps == 2
