import pytest

from fsd.benchmark.measure import TrialCollector
from tests.benchmark.helpers import step_event


def test_correction_and_verification_attempts_are_counted_separately() -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=(("decision", "invalid"), ("decision", "completed"))))
  collector.observe(step_event(1, attempts=(("verification", "completed"),), outcome="done"))

  result = collector.measurements(duration_seconds=1.0)

  assert result.decision_attempts == 2
  assert result.verification_attempts == 1
  assert result.invalid_attempts == 1
  assert result.captured_steps == 2
  assert result.performed_actions == 0


@pytest.mark.parametrize(
  ("purpose", "expected_decisions", "expected_verifications"),
  [("decision", 1, 0), ("verification", 0, 1)],
)
@pytest.mark.parametrize(
  ("status", "expected_invalid"),
  [("pending", 0), ("error", 0), ("interrupted", 0), ("invalid", 1)],
)
def test_uncompleted_attempts_still_count_toward_their_purpose(
  purpose: str,
  expected_decisions: int,
  expected_verifications: int,
  status: str,
  expected_invalid: int,
) -> None:
  collector = TrialCollector()
  collector.observe(step_event(0, attempts=((purpose, status),), outcome="interrupted"))

  result = collector.measurements(duration_seconds=1.0)

  assert result.decision_attempts == expected_decisions
  assert result.verification_attempts == expected_verifications
  assert result.invalid_attempts == expected_invalid
