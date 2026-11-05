"""Schema adaptation at the model-client boundary."""

from typing import Any

from pydantic import BaseModel

# Traverse schema locations only; defaults and examples can contain literal data.
SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
SCHEMA_MAPS = ("properties", "$defs")
SCHEMA_SINGLE = ("items", "additionalProperties", "not")


def wire_schema(model: type[BaseModel]) -> dict[str, Any]:
  """Express const constraints as equivalent single-value enums."""
  schema = model.model_json_schema()
  _rewrite(schema)
  return schema


def _rewrite(node: Any) -> None:
  if not isinstance(node, dict):
    return

  if "const" in node:
    node["enum"] = [node.pop("const")]

  for key in SCHEMA_LISTS:
    for child in node.get(key, []):
      _rewrite(child)

  for key in SCHEMA_MAPS:
    for child in node.get(key, {}).values():
      _rewrite(child)

  for key in SCHEMA_SINGLE:
    _rewrite(node.get(key))
