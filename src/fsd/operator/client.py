import base64
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from fsd.operator.config import Settings
from fsd.operator.context import SYSTEM_PROMPT, Observation
from fsd.operator.contracts import Decision, ModelResult
from fsd.operator.control import Control


class InferenceError(Exception):
  pass


class InvalidDecision(InferenceError):
  pass


class DecisionClient(Protocol):
  async def decide(
    self,
    observation: Observation,
    control: Control,
    correction: str = "",
  ) -> ModelResult: ...


class Message(BaseModel):
  content: str | None = None


class Choice(BaseModel):
  message: Message
  finish_reason: str | None = None


class Usage(BaseModel):
  model_config = ConfigDict(allow_inf_nan=False)

  prompt_tokens: int = Field(default=0, ge=0)
  completion_tokens: int = Field(default=0, ge=0)
  cost: float | None = Field(default=0, ge=0)


class Envelope(BaseModel):
  choices: list[Choice]
  usage: Usage | None = None


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
