"""Schema adaptation at the model-client boundary."""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from fsd.operator.contracts import ACTION_MODELS

FEEDBACK_LIMIT = 1500

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


def validation_feedback(error: ValidationError, text: str) -> str:
  """Report validation errors for the selected action within a fixed budget."""
  tag = _action_tag(text)
  branch = ACTION_MODELS.get(tag) if tag is not None else None
  lines = []

  if tag is not None and branch is None:
    lines.append(f"- action.kind: must be one of {', '.join(ACTION_MODELS)}")

  for item in error.errors(include_url=False, include_context=False, include_input=False):
    loc = item["loc"]

    if tag is not None and loc[:1] == ("action",) and len(loc) > 1:
      if branch is None or loc[1] != branch.__name__:
        continue
      loc = ("action", *loc[2:])

    lines.append(f"- {'.'.join(map(str, loc)) or 'decision'}: {item['msg']}")

  return "\n".join(lines)[:FEEDBACK_LIMIT]


def _action_tag(text: str) -> str | None:
  try:
    action = json.loads(text).get("action")
  except (ValueError, AttributeError):
    return None

  tag = action.get("kind") if isinstance(action, dict) else None
  return tag if isinstance(tag, str) else None
