import json

import pytest
from fsd.operator.config import Settings
from fsd.operator.contracts import Decision
from pydantic import ValidationError


def payload(action: dict[str, object] | None) -> str:
  return json.dumps(
    {
      "kind": "act" if action else "done",
      "action": action,
      "message": "Proceed",
      "expected": "Visible progress",
      "notes": "",
      "previous_result": "none",
    }
  )


def test_default_model_does_not_require_cli_input() -> None:
  assert Settings().model == "google/gemini-3.1-flash-lite"


@pytest.mark.parametrize(
  "action",
  [
    {"kind": "click", "x": 1.1, "y": 0.2},
    {"kind": "click", "x": float("nan"), "y": 0.2},
    {"kind": "hold", "key": "left", "duration_ms": -1},
    {"kind": "hold", "key": "a+b", "duration_ms": 100},
    {"kind": "hold", "key": "shift+a", "duration_ms": 100},
    {"kind": "hold", "key": "banana", "duration_ms": 100},
    {"kind": "key", "combo": "banana"},
    {"kind": "wait", "duration_ms": "100"},
    {"kind": "shell", "command": "anything"},
  ],
)
def test_bad_actions_are_rejected(action: dict[str, object]) -> None:
  with pytest.raises(ValidationError):
    Decision.model_validate_json(payload(action))


def test_completion_cannot_smuggle_an_action() -> None:
  data = json.loads(payload({"kind": "key", "combo": "return"}))
  data["kind"] = "done"
  with pytest.raises(ValidationError):
    Decision.model_validate(data)


def test_schema_forbids_unknown_response_fields() -> None:
  assert Decision.model_json_schema()["additionalProperties"] is False
