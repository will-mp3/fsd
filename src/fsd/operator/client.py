import base64

from fsd.operator.config import Settings
from fsd.operator.context import SYSTEM_PROMPT, Observation
from fsd.operator.contracts import Decision


def request_body(
  observation: Observation, settings: Settings, correction: str
) -> dict[str, object]:
  content: list[dict[str, object]] = [
    {"type": "text", "text": observation.text},
  ]
  if correction:
    content.append({"type": "text", "text": correction})

  for label, frame in (
    ("previous", observation.previous),
    ("current", observation.current),
  ):
    if frame is not None:
      data = base64.b64encode(frame.png).decode("ascii")
      content.extend(
        [
          {"type": "text", "text": f"{label} screenshot"},
          {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{data}"},
          },
        ]
      )

  return {
    "model": settings.model,
    "messages": [
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user", "content": content},
    ],
    "stream": False,
    "max_tokens": settings.max_output_tokens,
    "provider": {"require_parameters": True},
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "computer_decision",
        "strict": True,
        "schema": Decision.model_json_schema(),
      },
    },
  }
