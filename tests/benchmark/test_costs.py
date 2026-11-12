from dataclasses import replace

import pytest

from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.measure import TrialCollector
from fsd.operator.contracts import Event
from tests.benchmark.helpers import step_event


@pytest.mark.parametrize(
  "cost",
  [True, False, -0.01, "0.01", float("nan"), float("inf"), -float("inf"), {}, [], 10**400],
  ids=(
    "true",
    "false",
    "negative",
    "string",
    "nan",
    "positive-infinity",
    "negative-infinity",
    "mapping",
    "list",
    "overflow",
  ),
)
def test_invalid_reported_cost_does_not_change_collector_state(cost: object) -> None:
  collector = TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),))
  bad_event = replace(event, metrics={**(event.metrics or {}), "cost": cost})
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError, match="cost"):
    collector.observe(bad_event)

  assert collector.run_id is None
  assert collector.geometry is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
  collector.observe(event)
  assert collector.measurements(duration_seconds=1.0).captured_steps == 1


def test_partial_cost_sums_include_zero_and_track_unpriced_attempts() -> None:
  collector = TrialCollector()
  collector.observe(
    step_event(0, attempts=(("decision", "invalid"), ("decision", "completed")), cost=0.02)
  )
  collector.observe(step_event(1, attempts=(("verification", "completed"),), cost=0.03))
  collector.observe(step_event(2, attempts=(("decision", "completed"),), cost=0.0))
  collector.observe(step_event(3, attempts=(("decision", "error"),), outcome="interrupted"))

  result = collector.measurements(duration_seconds=1.0)

  assert result.reported_cost == pytest.approx(0.05)
  assert result.cost_measurements == 3
  assert result.attempts_without_cost == 2
  assert result.captured_steps == 4

  collector.observe(Event("metrics", "Totals", metrics={"run_id": "run", "cost": 99.0}))
  assert collector.measurements(duration_seconds=1.0) == result


@pytest.mark.parametrize("explicit_null", [False, True], ids=("absent", "null"))
@pytest.mark.parametrize(
  ("attempts", "expected_missing"),
  [
    ((), 0),
    ((("decision", "completed"),), 1),
    ((("decision", "invalid"), ("decision", "error")), 2),
  ],
  ids=("no-requests", "one-request", "two-requests"),
)
def test_without_cost_measurements_the_total_remains_unknown(
  explicit_null: bool,
  attempts: tuple[tuple[str, str], ...],
  expected_missing: int,
) -> None:
  collector = TrialCollector()
  event = step_event(0, attempts=attempts, outcome="interrupted")
  if explicit_null:
    event = replace(event, metrics={**(event.metrics or {}), "cost": None})
  collector.observe(event)

  result = collector.measurements(duration_seconds=1.0)

  assert result.reported_cost is None
  assert result.cost_measurements == 0
  assert result.attempts_without_cost == expected_missing


def test_reported_zero_is_preserved_as_a_cost_measurement() -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=(("decision", "completed"),), cost=0.0))

  result = collector.measurements(duration_seconds=1.0)

  assert result.reported_cost == 0.0
  assert result.cost_measurements == 1
  assert result.attempts_without_cost == 0


def test_duplicate_capture_does_not_add_its_cost_twice() -> None:
  collector = TrialCollector()
  event = step_event(0, attempts=(("decision", "completed"),), cost=0.25)
  collector.observe(event)
  before = collector.measurements(duration_seconds=1.0)

  with pytest.raises(BenchmarkError, match="[Dd]uplicate"):
    collector.observe(event)

  assert collector.measurements(duration_seconds=1.0) == before
  assert before.reported_cost == 0.25
  assert before.cost_measurements == 1


def test_cost_total_overflow_is_rejected_before_accepting_the_step() -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=(("decision", "completed"),), cost=1e308))
  before = collector.measurements(duration_seconds=1.0)

  with pytest.raises(BenchmarkError, match="cost"):
    collector.observe(step_event(1, attempts=(("decision", "completed"),), cost=1e308))

  assert collector.measurements(duration_seconds=1.0) == before
  collector.observe(step_event(1, attempts=(("decision", "completed"),), cost=0.0))
  result = collector.measurements(duration_seconds=2.0)
  assert result.reported_cost == 1e308
  assert result.cost_measurements == 2
  assert result.captured_steps == 2


@pytest.mark.parametrize("status", [None, "pending", "invalid", "error", "interrupted"])
def test_reported_cost_requires_a_completed_attempt(status: str | None) -> None:
  collector = TrialCollector()
  attempts = () if status is None else (("decision", status),)
  event = step_event(0, attempts=attempts, cost=0.0, outcome="interrupted")
  before = collector.measurements(duration_seconds=0.0)

  with pytest.raises(BenchmarkError, match="completed"):
    collector.observe(event)

  assert collector.run_id is None
  assert collector.geometry is None
  assert collector.termination is None
  assert collector.measurements(duration_seconds=0.0) == before
