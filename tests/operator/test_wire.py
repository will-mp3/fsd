from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field

from fsd.operator.contracts import Decision, Verdict


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
