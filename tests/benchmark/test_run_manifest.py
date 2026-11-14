import json
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fsd.benchmark import contracts
from fsd.benchmark.tasks import task_for, task_manifest
from fsd.operator.config import Settings


def run_payload() -> dict[str, object]:
  return {
    "trial_id": "0123456789abcdef",
    "task": task_manifest(task_for("finder-rename")).model_dump(mode="json"),
    "settings": asdict(Settings()),
    "approved_apps": ["com.apple.finder"],
    "started_at": "2026-11-13T12:00:00Z",
  }


def test_run_manifest_round_trips_resolved_settings_and_task_identity() -> None:
  run = contracts.RunManifest.model_validate_json(json.dumps(run_payload()))

  restored = contracts.RunManifest.model_validate_json(run.model_dump_json())

  assert restored == run
  assert restored.settings == Settings()
  assert restored.task == task_manifest(task_for("finder-rename"))
  assert restored.approved_apps == ("com.apple.finder",)
  assert restored.started_at == datetime(2026, 11, 13, 12, tzinfo=UTC)
  assert restored.memory_mode == "off"
  assert restored.geometry is None
  assert restored.revision is None


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("trial_id", "0123456789abcde"),
    ("trial_id", "0123456789abcdef0"),
    ("trial_id", "0123456789abcdeF"),
    ("trial_id", "0123456789abcdeg"),
    ("schema_version", True),
    ("schema_version", 2),
    ("memory_mode", "on"),
    ("started_at", "2026-11-13T12:00:00"),
    ("approved_apps", ["com.apple.finder", "com.apple.finder"]),
    ("approved_apps", ["com.apple.finder", "com.apple.TextEdit"]),
    ("approved_apps", [""]),
    ("approved_apps", [" com.apple.finder"]),
    ("revision", "x" * 201),
    ("unexpected", "value"),
  ],
)
def test_run_manifest_rejects_invalid_stored_metadata(field: str, value: object) -> None:
  payload = run_payload()
  payload[field] = value

  with pytest.raises(ValidationError):
    contracts.RunManifest.model_validate_json(json.dumps(payload))


def test_run_manifest_normalizes_aware_timestamps_to_utc() -> None:
  payload = run_payload()
  payload["started_at"] = "2026-11-13T07:00:00-05:00"

  run = contracts.RunManifest.model_validate_json(json.dumps(payload))

  assert run.started_at == datetime(2026, 11, 13, 12, tzinfo=UTC)
  assert run.started_at.tzinfo == UTC


@pytest.mark.parametrize(
  "field",
  [definition.name for definition in fields(Settings) if definition.type in (int, float)],
)
def test_run_manifest_rejects_negative_execution_settings(field: str) -> None:
  payload = run_payload()
  payload["settings"] = {**asdict(Settings()), field: -1}

  with pytest.raises(ValidationError):
    contracts.RunManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
  "field",
  [
    definition.name
    for definition in fields(Settings)
    if definition.type in (int, float) and definition.name not in {"retries", "verify_settle_ms"}
  ],
)
def test_run_manifest_rejects_zero_execution_limits(field: str) -> None:
  payload = run_payload()
  payload["settings"] = {**asdict(Settings()), field: 0}

  with pytest.raises(ValidationError):
    contracts.RunManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), True, "60"])
def test_run_manifest_rejects_nonfinite_or_coerced_time_limits(value: object) -> None:
  payload = run_payload()
  payload["settings"] = {**asdict(Settings()), "request_seconds": value}

  with pytest.raises(ValidationError):
    contracts.RunManifest.model_validate_json(json.dumps(payload))


def test_run_manifest_allows_no_retries_and_no_verification_delay() -> None:
  payload = run_payload()
  settings = replace(Settings(), retries=0, verify_settle_ms=0)
  payload["settings"] = asdict(settings)

  run = contracts.RunManifest.model_validate_json(json.dumps(payload))

  assert run.settings == settings


def test_run_manifest_checks_an_existing_settings_instance() -> None:
  with pytest.raises(ValidationError):
    contracts.RunManifest(
      trial_id="0123456789abcdef",
      task=task_manifest(task_for("finder-rename")),
      settings=replace(Settings(), action_limit=-1),
      approved_apps=("com.apple.finder",),
      started_at=datetime(2026, 11, 13, 12, tzinfo=UTC),
    )
