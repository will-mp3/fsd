from dataclasses import replace

import pytest

from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.measure import TrialCollector
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
