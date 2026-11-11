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


@pytest.mark.parametrize(
  ("limited", "expected_help", "expected_limit"),
  [(False, 1, 0), (True, 0, 1)],
  ids=("help", "limit"),
)
def test_stop_counts_distinguish_help_from_limits_without_counting_cancellation(
  limited: bool,
  expected_help: int,
  expected_limit: int,
) -> None:
  collector = measure.TrialCollector()
  before = collector.measurements(duration_seconds=0.0)

  collector.observe(Event("help", "Stop", limit=limited, metrics={"run_id": "run"}))
  stopped = collector.measurements(duration_seconds=1.5)
  collector.observe(Event("cancelled", "Stopped", metrics={"run_id": "run"}))
  confirmed = collector.measurements(duration_seconds=2.0)

  assert before.help_events == 0
  assert before.limit_events == 0
  assert stopped.help_events == expected_help
  assert stopped.limit_events == expected_limit
  assert stopped.duration_seconds == 1.5
  assert confirmed.help_events == expected_help
  assert confirmed.limit_events == expected_limit
  assert confirmed.duration_seconds == 2.0


def test_only_accepted_action_events_increment_performed_actions() -> None:
  collector = measure.TrialCollector()
  collector.observe(Event("action", "First action", metrics={"run_id": "run"}))
  first = collector.measurements(duration_seconds=1.0)

  collector.observe(Event("progress", "Continuing"))
  collector.observe(Event("action", "Second action", metrics={"run_id": "run"}))
  collector.observe(Event("metrics", "Totals", metrics={"run_id": "run"}))
  collector.observe(Event("done", "Complete", metrics={"run_id": "run"}))
  final = collector.measurements(duration_seconds=2.0)

  assert first.performed_actions == 1
  assert final.performed_actions == 2


@pytest.mark.parametrize("after_stop", [False, True], ids=("wrong-run", "after-stop"))
def test_rejected_action_does_not_change_measurements(after_stop: bool) -> None:
  collector = measure.TrialCollector()
  collector.observe(Event("action", "Accepted", metrics={"run_id": "run"}))
  if after_stop:
    collector.observe(Event("done", "Complete", metrics={"run_id": "run"}))
  before = collector.measurements(duration_seconds=1.0)

  with pytest.raises(BenchmarkError, match="stopped" if after_stop else "different run"):
    collector.observe(
      Event("action", "Rejected", metrics={"run_id": "run" if after_stop else "other"})
    )

  assert collector.measurements(duration_seconds=1.0) == before


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
