from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fsd.platform.base import Rect

Termination = Literal["done", "help", "limit", "cancelled", "failed", "interrupted"]


class BenchmarkError(Exception):
  """A benchmark problem that can be reported without a traceback."""


@dataclass(frozen=True)
class TaskSpec:
  task_id: str
  version: int
  app_id: str
  prompt: str
  initial_files: tuple[tuple[str, bytes], ...]
  directories: tuple[str, ...]
  final_files: tuple[tuple[str, bytes], ...]
  absent_after: tuple[str, ...]
  setup: tuple[str, ...]


class StoredModel(BaseModel):
  model_config = ConfigDict(
    extra="forbid",
    frozen=True,
    allow_inf_nan=False,
    strict=True,
  )

  @field_validator(
    "schema_version",
    "task_version",
    "setup_protocol",
    mode="before",
    check_fields=False,
  )
  @classmethod
  def integer_version(cls, value: object) -> object:
    if type(value) is not int:
      raise ValueError("Version fields must be integers.")
    return value


class TaskManifest(StoredModel):
  schema_version: Literal[1] = 1
  task_id: str
  task_version: int = Field(ge=1)
  prompt: str
  app_id: str
  setup_protocol: Literal[1] = 1
  initial_sha256: dict[str, str]
  directories: tuple[str, ...]


class GoalScore(StoredModel):
  result: Literal["pass", "fail", "error"]
  evidence: str = Field(max_length=500)


class FrameGeometry(StoredModel):
  width: int = Field(gt=0)
  height: int = Field(gt=0)
  screen_rect: Rect


class Measurements(StoredModel):
  captured_steps: int = Field(default=0, ge=0)
  performed_actions: int = Field(default=0, ge=0)
  decision_attempts: int = Field(default=0, ge=0)
  verification_attempts: int = Field(default=0, ge=0)
  invalid_attempts: int = Field(default=0, ge=0)
  refusals: int = Field(default=0, ge=0)
  stuck_warnings: int = Field(default=0, ge=0)
  stuck_escalations: int = Field(default=0, ge=0)
  help_events: int = Field(default=0, ge=0)
  limit_events: int = Field(default=0, ge=0)
  completion_rejections: int = Field(default=0, ge=0)
  duration_seconds: float = Field(ge=0)
  reported_cost: float | None = Field(default=None, ge=0)
  cost_measurements: int = Field(default=0, ge=0)
  attempts_without_cost: int = Field(default=0, ge=0)
