from dataclasses import dataclass, fields
from datetime import UTC, datetime
from math import isfinite
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from fsd.operator.config import Settings
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


class RunManifest(StoredModel):
  schema_version: Literal[1] = 1
  trial_id: str = Field(pattern=r"^[0-9a-f]{16}$")
  task: TaskManifest
  settings: Settings
  memory_mode: Literal["off"] = "off"
  approved_apps: tuple[str, ...]
  revision: str | None = Field(default=None, max_length=200)
  started_at: AwareDatetime
  geometry: FrameGeometry | None = None

  @field_validator("settings")
  @classmethod
  def valid_execution_settings(cls, value: Settings) -> Settings:
    for definition in fields(Settings):
      if definition.type not in (int, float):
        continue

      number = getattr(value, definition.name)
      allowed_types = (int,) if definition.type is int else (int, float)
      if type(number) not in allowed_types:
        raise ValueError(f"{definition.name} has an invalid numeric type.")
      if isinstance(number, float) and not isfinite(number):
        raise ValueError(f"{definition.name} must be finite.")

      allows_zero = definition.name in {"retries", "verify_settle_ms"}
      if number < 0 or (number == 0 and not allows_zero):
        requirement = "nonnegative" if allows_zero else "positive"
        raise ValueError(f"{definition.name} must be {requirement}.")

    return value

  @field_validator("approved_apps")
  @classmethod
  def canonical_approved_apps(cls, value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not app or app != app.strip() for app in value):
      raise ValueError("Approved app IDs must be nonempty and have no surrounding whitespace.")
    if value != tuple(sorted(set(value))):
      raise ValueError("Approved app IDs must be sorted and unique.")
    return value

  @field_validator("started_at")
  @classmethod
  def utc_started_at(cls, value: datetime) -> datetime:
    return value.astimezone(UTC)
