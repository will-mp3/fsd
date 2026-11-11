import pytest

from fsd.benchmark.measure import TrialCollector
from fsd.operator.contracts import Event
from tests.benchmark.helpers import step_event


@pytest.mark.parametrize("owner", ["blocked.app", None], ids=("known-owner", "unknown-owner"))
def test_refused_input_counts_separately_from_performed_actions(owner: str | None) -> None:
  collector = TrialCollector()
  collector.observe(Event("action", "Performed key", metrics={"run_id": "run"}))
  collector.observe(step_event(0, attempts=(("decision", "completed"),)))
  collector.observe(
    step_event(
      1,
      attempts=(("decision", "completed"),),
      outcome="refused",
      refusal={"reason": "keyboard_focus", "owner": owner},
    )
  )

  result = collector.measurements(duration_seconds=1.0)

  assert result.refusals == 1
  assert result.performed_actions == 1
  assert result.captured_steps == 2
  assert result.decision_attempts == 2
  assert result.invalid_attempts == 0
  assert result.help_events == 0
  assert collector.termination is None


def test_rejected_completion_is_counted_without_ending_the_trial() -> None:
  collector = TrialCollector()
  collector.observe(
    step_event(0, attempts=(("verification", "completed"),), outcome="rejected_done")
  )
  rejected = collector.measurements(duration_seconds=1.0)

  assert rejected.completion_rejections == 1
  assert rejected.invalid_attempts == 0
  assert rejected.help_events == 0
  assert collector.termination is None

  collector.observe(step_event(1, attempts=(("verification", "completed"),), outcome="done"))
  collector.observe(Event("done", "Complete", metrics={"run_id": "run"}))
  final = collector.measurements(duration_seconds=2.0)

  assert final.completion_rejections == 1
  assert final.verification_attempts == 2
  assert final.invalid_attempts == 0
  assert final.performed_actions == 0
  assert collector.termination == "done"
