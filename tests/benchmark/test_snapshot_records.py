import json
from dataclasses import replace

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
