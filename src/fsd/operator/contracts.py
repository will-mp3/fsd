from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fsd.operator.config import MAX_WAIT_MS
from fsd.platform.base import MAX_HOLD_MS, SUPPORTED_KEYS, parse_combo

Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
ShortText = Annotated[str, Field(max_length=500)]


class StrictModel(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Click(StrictModel):
  kind: Literal["click"]
  x: Coordinate
  y: Coordinate


class Scroll(StrictModel):
  kind: Literal["scroll"]
  x: Coordinate
  y: Coordinate
  dx: Annotated[int, Field(ge=-100, le=100)]
  dy: Annotated[int, Field(ge=-100, le=100)]


class TypeText(StrictModel):
  kind: Literal["type"]
  text: Annotated[str, Field(min_length=1, max_length=2000)]


class Key(StrictModel):
  kind: Literal["key"]
  combo: Annotated[str, Field(min_length=1, max_length=80)]

  @field_validator("combo")
  @classmethod
  def valid_combo(cls, value: str) -> str:
    parse_combo(value)
    return value


class Hold(StrictModel):
  kind: Literal["hold"]
  key: Annotated[
    str,
    Field(
      min_length=1,
      max_length=30,
      json_schema_extra={"enum": sorted(SUPPORTED_KEYS)},
    ),
  ]
  duration_ms: Annotated[int, Field(gt=0, le=MAX_HOLD_MS)]

  @field_validator("key")
  @classmethod
  def ordinary_key(cls, value: str) -> str:
    parsed = parse_combo(value)
    if parsed.modifiers:
      raise ValueError("Hold accepts one ordinary key")
    return parsed.key


class Wait(StrictModel):
  kind: Literal["wait"]
  duration_ms: Annotated[int, Field(gt=0, le=MAX_WAIT_MS)]


Action = Click | Scroll | TypeText | Key | Hold | Wait


class Decision(StrictModel):
  kind: Literal["act", "done", "help"]
  action: Action | None
  message: ShortText
  expected: ShortText
  notes: Annotated[str, Field(max_length=2000)]
  previous_result: Literal["none", "success", "failure", "uncertain"]

  @model_validator(mode="after")
  def consistent(self) -> Self:
    if (self.kind == "act") != (self.action is not None):
      raise ValueError("Only act decisions may contain an action")
    if not self.message.strip():
      raise ValueError("A concise status message is required")
    if self.kind == "act" and not self.expected.strip():
      raise ValueError("An action must describe its expected visible result")
    return self


class Verdict(StrictModel):
  complete: bool
  evidence: ShortText

  @field_validator("evidence")
  @classmethod
  def describes_evidence(cls, value: str) -> str:
    if not value.strip():
      raise ValueError("A verdict must describe the visible evidence")
    return value


@dataclass(frozen=True)
class ModelResult:
  decision: Decision
  request_seconds: float
  input_tokens: int = 0
  output_tokens: int = 0
  cost: float | None = None
  encode_seconds: float = 0.0
  cached_input_tokens: int | None = None


@dataclass(frozen=True)
class VerificationResult:
  verdict: Verdict
  request_seconds: float
  input_tokens: int = 0
  output_tokens: int = 0
  cost: float | None = None
  encode_seconds: float = 0.0
  cached_input_tokens: int | None = None


@dataclass(frozen=True)
class Snapshot:
  run_id: str
  step: int
  png: bytes


@dataclass(frozen=True)
class Event:
  kind: Literal["progress", "action", "help", "done", "failed", "cancelled", "metrics"]
  message: str
  limit: bool = False
  metrics: dict[str, object] | None = None
  snapshot: Snapshot | None = None


@dataclass(frozen=True)
class Reply:
  text: str = ""
  cancel: bool = False
  extend: bool = False
