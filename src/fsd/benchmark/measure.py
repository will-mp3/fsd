import json
import re
from typing import Literal

from pydantic import ConfigDict, Field

from fsd.benchmark.contracts import (
  BenchmarkError,
  FrameGeometry,
  Measurements,
  StoredModel,
  Termination,
)
from fsd.operator.contracts import Event, Reply
from fsd.operator.records import Purpose


class AttemptView(StoredModel):
  model_config = ConfigDict(extra="ignore")

  purpose: Purpose
  status: Literal["pending", "completed", "invalid", "interrupted", "error"]


class FrameView(FrameGeometry):
  model_config = ConfigDict(extra="ignore")

  filename: str


class StepView(StoredModel):
  model_config = ConfigDict(extra="ignore")

  schema_version: Literal[1]
  run_id: str
  step: int = Field(ge=0)
  outcome: str
  frame: FrameView
  attempts: tuple[AttemptView, ...]
  refusal: dict[str, str | None] | None


class TrialCollector:
  def __init__(self) -> None:
    self._run_id: str | None = None
    self._termination: Termination | None = None
    self._cancellation_recorded = False
    self._counts: dict[str, int] = {
      "help_events": 0,
      "limit_events": 0,
      "performed_actions": 0,
    }

  @property
  def run_id(self) -> str | None:
    return self._run_id

  @property
  def termination(self) -> Termination | None:
    return self._termination

  def measurements(self, duration_seconds: float) -> Measurements:
    return Measurements(
      duration_seconds=duration_seconds,
      **self._counts,
    )

  def _validate_run_id(self, event: Event) -> str | None:
    if event.kind == "progress" and not event.metrics and event.snapshot is None:
      return None

    candidate = (event.metrics or {}).get("run_id")
    if not isinstance(candidate, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate) is None:
      raise BenchmarkError("A benchmark event requires a valid run ID.")

    if self._run_id is not None and candidate != self._run_id:
      raise BenchmarkError("Received an event for a different run.")

    return candidate

  def _validate_snapshot(self, event: Event, run_id: str | None) -> StepView | None:
    snapshot = event.snapshot
    if snapshot is None:
      return None

    try:
      record = StepView.model_validate_json(json.dumps(snapshot.record, allow_nan=False))
    except (TypeError, ValueError) as exc:
      raise BenchmarkError("Invalid benchmark step record.") from exc

    if snapshot.run_id != run_id or record.run_id != run_id:
      raise BenchmarkError("Snapshot and event run IDs do not match.")

    return record

  def observe(self, event: Event) -> Reply | None:
    run_id = self._validate_run_id(event)
    self._validate_snapshot(event, run_id)

    if self._termination is not None:
      if (
        self._termination in {"help", "limit"}
        and event.kind == "cancelled"
        and not self._cancellation_recorded
      ):
        self._cancellation_recorded = True
        return None

      raise BenchmarkError("Received an event after the trial had stopped.")

    if run_id is not None:
      self._run_id = run_id

    if event.kind == "action":
      self._counts["performed_actions"] += 1

    if event.kind == "help":
      self._termination = "limit" if event.limit else "help"
      self._counts["limit_events" if event.limit else "help_events"] += 1
      return Reply(cancel=True)

    if event.kind == "done":
      self._termination = "done"
    elif event.kind == "failed":
      self._termination = "failed"
    elif event.kind == "cancelled":
      self._termination = "cancelled"

    return None
