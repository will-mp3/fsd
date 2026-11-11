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


@pytest.mark.parametrize("run_id", ["run", "0123456789abcdef", "run_1-test"])
def test_collector_records_the_first_run_id(run_id: str) -> None:
  collector = measure.TrialCollector()

  assert collector.run_id is None
  collector.observe(Event("done", "Complete", metrics={"run_id": run_id}))

  assert collector.run_id == run_id
  assert collector.termination == "done"


@pytest.mark.parametrize("metrics", [None, {}], ids=("none", "empty"))
def test_terminal_event_rejects_missing_run_id(metrics: dict[str, object] | None) -> None:
  collector = measure.TrialCollector()

  with pytest.raises(BenchmarkError, match="run ID"):
    collector.observe(Event("done", "Complete", metrics=metrics))

  assert collector.run_id is None
  assert collector.termination is None


@pytest.mark.parametrize(
  "run_id",
  [None, True, 12, "", " ", ".", "..", "../outside", "run/other", "run\\other", "run\n", "x" * 65],
  ids=(
    "null",
    "boolean",
    "number",
    "empty",
    "space",
    "dot",
    "parent",
    "traversal",
    "slash",
    "backslash",
    "newline",
    "too-long",
  ),
)
def test_invalid_run_id_cannot_change_collector_state(run_id: object) -> None:
  collector = measure.TrialCollector()

  with pytest.raises(BenchmarkError, match="run ID"):
    collector.observe(Event("help", "Stop", metrics={"run_id": run_id}))

  assert collector.run_id is None
  assert collector.termination is None


@pytest.mark.parametrize("metrics", [None, {}], ids=("none", "empty"))
def test_informational_progress_does_not_assign_or_clear_run_id(
  metrics: dict[str, object] | None,
) -> None:
  collector = measure.TrialCollector()

  collector.observe(Event("progress", "Starting", metrics=metrics))
  assert collector.run_id is None
  collector.observe(Event("progress", "Identified", metrics={"run_id": "run"}))
  collector.observe(Event("progress", "Continuing", metrics=metrics))

  assert collector.run_id == "run"
  assert collector.termination is None


def test_another_run_cannot_change_the_stopping_reason() -> None:
  collector = measure.TrialCollector()
  collector.observe(Event("progress", "Starting", metrics={"run_id": "first"}))

  with pytest.raises(BenchmarkError, match="different run"):
    collector.observe(Event("help", "Stop", metrics={"run_id": "second"}))

  assert collector.run_id == "first"
  assert collector.termination is None
  assert collector.observe(Event("help", "Stop", metrics={"run_id": "first"})) == Reply(cancel=True)


def test_rejected_cancellation_does_not_consume_the_expected_confirmation() -> None:
  collector = measure.TrialCollector()
  collector.observe(Event("help", "Stop", metrics={"run_id": "first"}))

  with pytest.raises(BenchmarkError, match="different run"):
    collector.observe(Event("cancelled", "Wrong run", metrics={"run_id": "second"}))

  assert collector.observe(Event("cancelled", "Stopped", metrics={"run_id": "first"})) is None
  assert collector.run_id == "first"
  assert collector.termination == "help"
