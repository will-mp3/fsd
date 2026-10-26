import asyncio
import base64
import time
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fsd.operator.config import Settings
from fsd.operator.context import SYSTEM_PROMPT, Observation
from fsd.operator.contracts import Decision, ModelResult
from fsd.operator.control import Control, controlled


class InferenceError(Exception):
  pass


InvalidCause = Literal["envelope", "finish_reason", "empty", "schema"]


class InvalidDecision(InferenceError):
  def __init__(self, cause: InvalidCause) -> None:
    super().__init__("Model returned an invalid or imcomplete response.")
    self.cause = cause


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
  cost: float | None = Field(default=None, ge=0)


class Envelope(BaseModel):
  choices: list[Choice]
  usage: Usage | None = None


def parse[T: BaseModel](content: bytes, schema: type[T]) -> tuple[T, Usage]:
  try:
    envelope = Envelope.model_validate_json(content)
  except ValidationError:
    raise InvalidDecision("envelope") from None

  if not envelope.choices:
    raise InvalidDecision("envelope")
  if envelope.choices[0].finish_reason != "stop":
    raise InvalidDecision("finish_reason")

  text = envelope.choices[0].message.content
  if text is None:
    raise InvalidDecision("empty")

  try:
    parsed = schema.model_validate_json(text)
  except ValidationError:
    raise InvalidDecision("schema") from None

  return parsed, envelope.usage or Usage()


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


class OpenRouterClient:
  def __init__(
    self,
    http: httpx.AsyncClient,
    api_key: str,
    settings: Settings,
  ) -> None:
    self._http = http
    self._key = api_key
    self._settings = settings

  async def decide(
    self,
    observation: Observation,
    control: Control,
    correction: str = "",
  ) -> ModelResult:
    started = time.monotonic()
    body = request_body(observation, self._settings, correction)

    for attempt in range(self._settings.retries + 1):
      control.check()
      try:
        response = await controlled(
          self._http.post(
            self._settings.api_url,
            json=body,
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=self._settings.request_seconds,
          ),
          control,
          self._settings.request_seconds,
        )
      except (httpx.RequestError, TimeoutError):
        if attempt == self._settings.retries:
          raise InferenceError(
            "Inference connection timed out or failed; no action performed."
          ) from None
      else:
        if response.status_code in {401, 403}:
          raise InferenceError("OpenRouter rejected the API key or access permissions.")
        if response.status_code == 402:
          raise InferenceError("OpenRouter credits are exhausted.")

        if response.status_code == 429 or response.status_code >= 500:
          if attempt == self._settings.retries:
            raise InferenceError("Inference provider remained unavailable after bounded retries.")
        elif response.is_error:
          raise InferenceError(
            f"Provider rejected the request (HTTP {response.status_code}); "
            "check model/schema support."
          )
        else:
          decision, usage = parse(response.content, Decision)
          control.check()
          return ModelResult(
            decision=decision,
            request_seconds=time.monotonic() - started,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost=usage.cost,
          )

      delay = min(0.25 * 2**attempt, 1.0)
      await controlled(asyncio.sleep(delay), control, 2)

    raise InferenceError("Inference did not produce a response.")
