from typing import Literal

import pytest

from fsd.benchmark import measure
from fsd.benchmark.contracts import BenchmarkError
from fsd.operator.contracts import Event, Reply


@pytest.mark.parametrize("limited,reason", [(False, "help"), (True, "limit")])
def test_help_reason_survives_engine_cancellation(limited: bool, reason: str) -> None:
  collector = measure.TrialCollector()

  reply = collector.observe(Event("help", "Stop", limit=limited, metrics={"run_id": "run"}))

  assert reply == Reply(cancel=True)
  assert collector.termination == reason
  assert collector.observe(Event("cancelled", "Stopped", metrics={"run_id": "run"})) is None
  assert collector.termination == reason


@pytest.mark.parametrize("kind", ["done", "failed", "cancelled"])
def test_direct_terminal_event_records_its_reason(
  kind: Literal["done", "failed", "cancelled"],
) -> None:
  collector = measure.TrialCollector()

  assert collector.observe(Event(kind, "Stopped", metrics={"run_id": "run"})) is None
  assert collector.termination == kind


def test_progress_does_not_end_a_trial() -> None:
  collector = measure.TrialCollector()

  assert collector.termination is None
  assert collector.observe(Event("progress", "Starting", metrics={"run_id": "run"})) is None
  assert collector.termination is None


@pytest.mark.parametrize(
  ("first", "second"),
  [("done", "failed"), ("help", "done"), ("help", "help"), ("cancelled", "cancelled")],
)
def test_incompatible_events_after_stopping_are_rejected(
  first: Literal["done", "help", "cancelled"],
  second: Literal["failed", "done", "help", "cancelled"],
) -> None:
  collector = measure.TrialCollector()
  collector.observe(Event(first, "First", metrics={"run_id": "run"}))
  original_reason = collector.termination

  with pytest.raises(BenchmarkError, match="stopped"):
    collector.observe(Event(second, "Second", metrics={"run_id": "run"}))

  assert collector.termination == original_reason


def test_help_allows_only_one_following_cancellation() -> None:
  collector = measure.TrialCollector()
  collector.observe(Event("help", "Stop", metrics={"run_id": "run"}))
  collector.observe(Event("cancelled", "Stopped", metrics={"run_id": "run"}))

  with pytest.raises(BenchmarkError, match="stopped"):
    collector.observe(Event("cancelled", "Repeated", metrics={"run_id": "run"}))

  assert collector.termination == "help"
