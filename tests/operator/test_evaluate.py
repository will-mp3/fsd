import asyncio
import base64
import json

import pytest

from fsd.operator.client import InferenceError, InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.contracts import Decision
from fsd.operator.evaluate import Case, evaluate
from fsd.platform.base import Frame, Rect
from tests.operator.helpers import ScriptedClient, decision


def example_case(name: str = "one") -> Case:
  return Case(name, "private-task", Frame(b"private-pixels", 100, 100, Rect(0, 0, 100, 100)))


def test_valid_decision_can_be_assessed_as_incorrect() -> None:
  case = example_case()
  choice = decision()
  assessed: list[tuple[Case, Decision]] = []

  def assess(case: Case, choice: Decision) -> bool:
    assessed.append((case, choice))
    return False

  rows = asyncio.run(evaluate([case], ScriptedClient([choice]), Settings(), assess))

  assert len(rows) == 1
  assert rows[0]["valid"] is True
  assert rows[0]["correct"] is False
  assert rows[0]["input_tokens"] == 10
  assert rows[0]["output_tokens"] == 5
  assert rows[0]["cost"] == 0.0001
  assert assessed == [(case, choice)]


@pytest.mark.parametrize("failure", [InvalidDecision("schema"), InferenceError("private-error")])
def test_inference_failure_is_recorded_and_later_cases_continue(failure: InferenceError) -> None:
  assessed: list[str] = []

  def assess(case: Case, choice: Decision) -> bool:
    assessed.append(case.name)
    return True

  rows = asyncio.run(
    evaluate(
      [example_case("failed"), example_case("next")],
      ScriptedClient([failure, decision()]),
      Settings(),
      assess,
    )
  )

  assert [row["case"] for row in rows] == ["failed", "next"]
  assert rows[0]["valid"] is False
  assert rows[0]["correct"] is None
  assert rows[0]["cost"] is None
  assert rows[0]["error"] == type(failure).__name__
  assert rows[1]["valid"] is True
  assert rows[1]["correct"] is True
  assert assessed == ["next"]
  assert "private-error" not in json.dumps(rows)


def test_unassessed_completion_is_not_assumed_correct() -> None:
  rows = asyncio.run(evaluate([example_case()], ScriptedClient([decision("done")]), Settings()))

  assert rows[0]["valid"] is True
  assert rows[0]["decision"] == "done"
  assert rows[0]["action"] is None
  assert rows[0]["correct"] is None


def test_result_rows_exclude_private_content() -> None:
  choice = Decision.model_validate(
    {
      "kind": "act",
      "action": {"kind": "type", "text": "private-typed-text"},
      "message": "private-message",
      "expected": "private-expected",
      "notes": "private-notes",
      "previous_result": "none",
    }
  )
  rows = asyncio.run(evaluate([example_case()], ScriptedClient([choice]), Settings()))
  serialized = json.dumps(rows, allow_nan=False)

  assert rows[0]["decision"] == "act"
  assert rows[0]["action"] == "type"
  assert "private-" not in serialized
  assert base64.b64encode(b"private-pixels").decode("ascii") not in serialized
