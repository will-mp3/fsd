import json
from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from fsd.benchmark import measure
from fsd.benchmark.contracts import BenchmarkError
from fsd.platform.base import Rect
from tests.benchmark.helpers import step_event


def test_step_view_reads_measurement_fields_from_a_full_engine_record() -> None:
  event = step_event(
    3,
    attempts=(("decision", "completed"), ("verification", "pending")),
    outcome="interrupted",
  )
  snapshot = event.snapshot
  assert snapshot is not None

  view = measure.StepView.model_validate_json(json.dumps(snapshot.record))

  assert view.schema_version == 1
  assert view.run_id == "run"
  assert view.step == 3
  assert view.outcome == "interrupted"
  assert view.frame.filename == "3.png"
  assert view.frame.width == 100
  assert view.frame.height == 100
  assert view.frame.screen_rect == Rect(0.0, 0.0, 50.0, 50.0)
  assert [(attempt.purpose, attempt.status) for attempt in view.attempts] == [
    ("decision", "completed"),
    ("verification", "pending"),
  ]
  assert view.refusal is None


def test_unsupported_snapshot_schema_does_not_bind_collector_identity() -> None:
  collector = measure.TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  assert event.snapshot is not None
  bad_snapshot = replace(event.snapshot, record={**event.snapshot.record, "schema_version": 2})
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError):
    collector.observe(replace(event, snapshot=bad_snapshot))

  assert collector.run_id is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
  assert collector.observe(event) is None
  assert collector.run_id == "run"


@pytest.mark.parametrize(
  ("layer", "field", "value"),
  [
    ("snapshot", "step", 1),
    ("record", "step", 1),
    ("metrics", "step", 1),
    ("metrics", "outcome", "done"),
    ("metrics", "frame_width", 200),
    ("metrics", "frame_height", 200),
    ("frame", "filename", "1.png"),
    ("snapshot", "step", False),
    ("snapshot", "step", 0.0),
    ("metrics", "step", False),
    ("metrics", "step", 0.0),
    ("metrics", "frame_width", 100.0),
    ("metrics", "frame_height", 100.0),
    ("metrics", "step", None),
  ],
)
def test_inconsistent_step_metadata_does_not_change_collector_state(
  layer: str,
  field: str,
  value: object,
) -> None:
  collector = measure.TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  snapshot = event.snapshot
  assert snapshot is not None
  if layer == "snapshot":
    assert field == "step"
    # Bypass the annotation deliberately to exercise malformed runtime values.
    bad_event = replace(event, snapshot=replace(snapshot, step=cast(int, value)))
  elif layer == "metrics":
    bad_event = replace(event, metrics={**(event.metrics or {}), field: value})
  else:
    record = dict(snapshot.record)
    if layer == "frame":
      frame = record["frame"]
      assert isinstance(frame, dict)
      record["frame"] = {**frame, field: value}
    else:
      record[field] = value
    bad_event = replace(event, snapshot=replace(snapshot, record=record))
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError):
    collector.observe(bad_event)

  assert collector.run_id is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
  assert collector.observe(event) is None
  assert collector.run_id == "run"


@pytest.mark.parametrize(
  ("layer", "field", "value"),
  [
    ("record", "schema_version", True),
    ("record", "run_id", None),
    ("record", "step", -1),
    ("record", "step", False),
    ("record", "step", 0.0),
    ("record", "attempts", None),
    ("frame", "width", 0),
    ("frame", "height", 0),
    ("frame", "width", True),
    ("frame", "height", 100.0),
    ("attempt", "purpose", "planner"),
    ("attempt", "status", "retrying"),
    ("attempt", "status", None),
  ],
)
def test_malformed_record_fields_are_rejected_without_changing_state(
  layer: str,
  field: str,
  value: object,
) -> None:
  collector = measure.TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  snapshot = event.snapshot
  assert snapshot is not None
  record = deepcopy(snapshot.record)
  target: object = record
  if layer == "frame":
    target = record["frame"]
  elif layer == "attempt":
    attempts = record["attempts"]
    assert isinstance(attempts, list)
    target = attempts[0]
  assert isinstance(target, dict)
  target[field] = value
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError, match="Invalid benchmark step record"):
    collector.observe(replace(event, snapshot=replace(snapshot, record=record)))

  assert collector.run_id is None
  assert collector.geometry is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
  collector.observe(event)
  assert collector.measurements(duration_seconds=1.0).captured_steps == 1


@pytest.mark.parametrize("layer", ["snapshot", "record", "metrics"])
def test_conflicting_snapshot_run_ids_do_not_change_collector_state(layer: str) -> None:
  collector = measure.TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  snapshot = event.snapshot
  assert snapshot is not None
  if layer == "snapshot":
    bad_event = replace(event, snapshot=replace(snapshot, run_id="other"))
  elif layer == "record":
    bad_event = replace(
      event,
      snapshot=replace(snapshot, record={**snapshot.record, "run_id": "other"}),
    )
  else:
    bad_event = replace(event, metrics={**(event.metrics or {}), "run_id": "other"})
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError, match="run ID"):
    collector.observe(bad_event)

  assert collector.run_id is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
