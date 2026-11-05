import json
from copy import deepcopy
from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from fsd.operator.contracts import Decision, Verdict
from tests.operator.helpers import decision


def feedback_for_text(text: str) -> str:
  from fsd.operator.wire import validation_feedback

  with pytest.raises(ValidationError) as error:
    Decision.model_validate_json(text)
  return validation_feedback(error.value, text)


def feedback_for(action: dict[str, object]) -> str:
  data = decision().model_dump()
  data["action"] = action
  return feedback_for_text(json.dumps(data))


def test_unknown_tag_lists_valid_tags_only() -> None:
  text = feedback_for({"kind": "combo", "combo": "command+space"})
  assert text == "- action.kind: must be one of click, scroll, type, key, hold, wait"


def test_known_tag_reports_only_its_branch() -> None:
  text = feedback_for({"kind": "key", "combo": "command+space"})
  assert text.startswith("- action.combo:")
  assert "Use alt, cmd, ctrl, shift" in text
  assert len(text.splitlines()) == 1


def test_wrong_fields_for_a_tag_are_named() -> None:
  text = feedback_for({"kind": "key", "key": "space", "duration_ms": 100})
  paths = {line.split(":", 1)[0] for line in text.splitlines()}
  assert paths == {"- action.combo", "- action.key", "- action.duration_ms"}


def test_feedback_is_bounded_and_omits_extra_field_values() -> None:
  from fsd.operator.wire import FEEDBACK_LIMIT

  action: dict[str, object] = {"kind": "key", "combo": "return"}
  action.update({f"unexpected_{index}": "private-value" for index in range(100)})
  text = feedback_for(action)
  assert 0 < len(text) <= FEEDBACK_LIMIT == 1500
  assert "private-value" not in text


@pytest.mark.parametrize("text", ["[]", "null", "{"])
def test_feedback_handles_non_object_and_malformed_json(text: str) -> None:
  assert feedback_for_text(text)


def test_all_action_tags_become_single_value_enums() -> None:
  from fsd.operator.wire import wire_schema

  definitions = wire_schema(Decision)["$defs"]
  for name, tag in (
    ("Click", "click"),
    ("Scroll", "scroll"),
    ("TypeText", "type"),
    ("Key", "key"),
    ("Hold", "hold"),
    ("Wait", "wait"),
  ):
    kind = definitions[name]["properties"]["kind"]
    assert "const" not in kind
    assert kind["enum"] == [tag]


def test_wire_schema_preserves_the_rest_of_the_contract() -> None:
  from fsd.operator.wire import wire_schema

  original = Decision.model_json_schema()
  expected = deepcopy(original)
  for name in ("Click", "Scroll", "TypeText", "Key", "Hold", "Wait"):
    kind = expected["$defs"][name]["properties"]["kind"]
    kind["enum"] = [kind.pop("const")]

  assert wire_schema(Decision) == expected
  assert Decision.model_json_schema() == original


def test_property_named_const_is_preserved() -> None:
  from fsd.operator.wire import wire_schema

  class Odd(BaseModel):
    const: Literal["x"]

  properties = wire_schema(Odd)["properties"]
  assert properties["const"]["enum"] == ["x"]
  assert "const" not in properties["const"]


def test_literal_data_in_defaults_and_examples_is_not_rewritten() -> None:
  from fsd.operator.wire import wire_schema

  class WithData(BaseModel):
    data: dict[str, str] = Field(default={"const": "literal"}, examples=[{"const": "example"}])

  data = wire_schema(WithData)["properties"]["data"]
  assert data["default"] == {"const": "literal"}
  assert data["examples"] == [{"const": "example"}]


def test_verdict_schema_is_preserved() -> None:
  from fsd.operator.wire import wire_schema

  assert wire_schema(Verdict) == Verdict.model_json_schema()
