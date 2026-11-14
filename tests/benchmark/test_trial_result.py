import json
from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from fsd.benchmark import contracts


def result_payload() -> dict[str, object]:
  return {
    "trial_id": "0123456789abcdef",
    "engine_run_id": "engine-run",
    "termination": "done",
    "score": {"result": "pass", "evidence": "Expected file contents matched."},
    "infrastructure": "ok",
    "measurements": {"duration_seconds": 1.5},
    "ended_at": "2026-11-13T12:00:00Z",
  }


def test_trial_result_round_trips_without_persisting_derived_success() -> None:
  result = contracts.TrialResult.model_validate_json(json.dumps(result_payload()))

  restored = contracts.TrialResult.model_validate_json(result.model_dump_json())

  assert restored == result
  assert restored.unassisted_success is True
  assert restored.engine_run_id == "engine-run"
  assert restored.measurements.duration_seconds == 1.5
  assert restored.ended_at == datetime(2026, 11, 13, 12, tzinfo=UTC)
  assert "unassisted_success" not in result.model_dump()
  assert "unassisted_success" not in json.loads(result.model_dump_json())


@pytest.mark.parametrize("termination", get_args(contracts.Termination))
@pytest.mark.parametrize("score", ["pass", "fail"])
@pytest.mark.parametrize("infrastructure", ["ok", "error"])
def test_success_requires_done_passing_artifact_and_healthy_infrastructure(
  termination: str,
  score: str,
  infrastructure: str,
) -> None:
  payload = result_payload()
  payload.update(
    termination=termination,
    score={"result": score, "evidence": "Checked fixture."},
    infrastructure=infrastructure,
    error_category="recording" if infrastructure == "error" else None,
  )

  result = contracts.TrialResult.model_validate_json(json.dumps(payload))

  expected = termination == "done" and score == "pass" and infrastructure == "ok"
  assert result.unassisted_success is expected


@pytest.mark.parametrize(
  ("infrastructure", "category", "score"),
  [
    ("ok", "recording", "pass"),
    ("ok", "scoring", "error"),
    ("ok", "execution", "fail"),
    ("ok", None, "error"),
    ("error", None, "pass"),
    ("error", None, "error"),
    ("error", "scoring", "pass"),
    ("error", "scoring", "fail"),
  ],
)
def test_trial_result_rejects_contradictory_infrastructure_fields(
  infrastructure: str,
  category: str | None,
  score: str,
) -> None:
  payload = result_payload()
  payload.update(
    infrastructure=infrastructure,
    error_category=category,
    score={"result": score, "evidence": "Scoring evidence."},
  )

  with pytest.raises(ValidationError):
    contracts.TrialResult.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("category", ["scoring", "recording", "execution"])
def test_scoring_failure_allows_the_original_infrastructure_error_category(category: str) -> None:
  payload = result_payload()
  payload.update(
    engine_run_id=None,
    termination="failed",
    infrastructure="error",
    error_category=category,
    score={"result": "error", "evidence": "Could not read workspace."},
  )

  result = contracts.TrialResult.model_validate_json(json.dumps(payload))

  assert result.error_category == category
  assert result.engine_run_id is None
  assert result.unassisted_success is False


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("schema_version", True),
    ("schema_version", 2),
    ("trial_id", "0123456789abcdeF"),
    ("trial_id", "short"),
    ("ended_at", "2026-11-13T12:00:00"),
    ("termination", "unknown"),
    ("infrastructure", "unknown"),
    ("error_category", "unknown"),
    ("unassisted_success", True),
  ],
)
def test_trial_result_rejects_invalid_or_independently_editable_metadata(
  field: str,
  value: object,
) -> None:
  payload = result_payload()
  payload[field] = value

  with pytest.raises(ValidationError):
    contracts.TrialResult.model_validate_json(json.dumps(payload))


def test_trial_result_normalizes_aware_end_timestamps_to_utc() -> None:
  payload = result_payload()
  payload["ended_at"] = "2026-11-13T07:00:00-05:00"

  result = contracts.TrialResult.model_validate_json(json.dumps(payload))

  assert result.ended_at == datetime(2026, 11, 13, 12, tzinfo=UTC)
  assert result.ended_at.tzinfo == UTC
