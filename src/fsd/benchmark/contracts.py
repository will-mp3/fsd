from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
