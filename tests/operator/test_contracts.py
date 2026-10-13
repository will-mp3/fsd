import json

import pytest
from pydantic import ValidationError

from fsd.operator.contracts import Decision


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


@pytest.mark.parametrize(
  "action",
  [
    {"kind": "click", "x": 1.1, "y": 0.2},
    {"kind": "click", "x": float("nan"), "y": 0.2},
    {"kind": "hold", "key": "left", "duration_ms": -1},
    {"kind": "hold", "key": "left", "duration_ms": 1001},
    {"kind": "hold", "key": "a+b", "duration_ms": 100},
    {"kind": "hold", "key": "shift+a", "duration_ms": 100},
    {"kind": "hold", "key": "banana", "duration_ms": 100},
    {"kind": "key", "combo": "banana"},
    {"kind": "wait", "duration_ms": "100"},
    {"kind": "wait", "duration_ms": True},
    {"kind": "wait", "duration_ms": 0},
    {"kind": "wait", "duration_ms": 5001},
    {"kind": "click", "x": 0.5, "y": 0.5, "button": "right"},
    {"kind": "shell", "command": "anything"},
  ],
)
def test_bad_actions_are_rejected(action: dict[str, object]) -> None:
  with pytest.raises(ValidationError):
    Decision.model_validate_json(payload(action))


@pytest.mark.parametrize("kind", ["done", "help"])
def test_non_action_decision_cannot_smuggle_an_action(kind: str) -> None:
  data = json.loads(payload({"kind": "key", "combo": "return"}))
  data["kind"] = kind
  with pytest.raises(ValidationError):
    Decision.model_validate(data)


def test_schema_forbids_unknown_response_fields() -> None:
  assert Decision.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
  "action",
  [
    {"kind": "click", "x": 0.0, "y": 1.0},
    {"kind": "scroll", "x": 0.5, "y": 0.5, "dx": -100, "dy": 100},
    {"kind": "type", "text": "Hello"},
    {"kind": "key", "combo": "cmd+shift+a"},
    {"kind": "hold", "key": "left", "duration_ms": 1000},
    {"kind": "wait", "duration_ms": 5000},
  ],
)
def test_supported_actions_are_accepted(action: dict[str, object]) -> None:
  decision = Decision.model_validate_json(payload(action))
  assert decision.kind == "act"
  assert decision.action is not None
  assert decision.action.model_dump() == action


@pytest.mark.parametrize("kind", ["done", "help"])
def test_non_action_decision_accepts_no_action(kind: str) -> None:
  data = json.loads(payload(None))
  data["kind"] = kind
  decision = Decision.model_validate(data)
  assert decision.kind == kind
  assert decision.action is None


def test_act_requires_an_action() -> None:
  data = json.loads(payload(None))
  data["kind"] = "act"
  with pytest.raises(ValidationError):
    Decision.model_validate(data)


@pytest.mark.parametrize("field", ["message", "expected"])
def test_action_requires_meaningful_status_and_expectation(field: str) -> None:
  data = json.loads(payload({"kind": "key", "combo": "return"}))
  data[field] = "   "
  with pytest.raises(ValidationError):
    Decision.model_validate(data)


def test_unknown_response_fields_are_rejected() -> None:
  data = json.loads(payload(None))
  data["command"] = "anything"
  with pytest.raises(ValidationError):
    Decision.model_validate(data)
