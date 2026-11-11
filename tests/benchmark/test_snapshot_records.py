import json

from fsd.benchmark import measure
from fsd.operator.records import StepRecord
from fsd.platform.base import Frame, Rect
from tests.operator.helpers import decision, png


def test_step_view_reads_measurement_fields_from_a_full_engine_record() -> None:
  record = StepRecord(
    "run",
    3,
    Frame(png(0), 100, 100, Rect(0.0, 0.0, 50.0, 50.0)),
    frozenset({"app"}),
  )
  record.attempt("decision", "").complete(decision("done"))
  record.attempt("verification", "")
  record.interruption = "RunCancelled"
  snapshot = record.snapshot("interrupted", "Previous feedback", "")

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
