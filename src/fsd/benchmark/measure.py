import json
import math
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
    self._geometry: FrameGeometry | None = None
    self._seen_steps: set[tuple[str, int]] = set()
    self._known_cost = 0.0
    self._counts: dict[str, int] = {
      "help_events": 0,
      "limit_events": 0,
      "performed_actions": 0,
      "captured_steps": 0,
      "decision_attempts": 0,
      "verification_attempts": 0,
      "invalid_attempts": 0,
      "refusals": 0,
      "completion_rejections": 0,
      "stuck_warnings": 0,
      "stuck_escalations": 0,
      "cost_measurements": 0,
      "attempts_without_cost": 0,
    }

  @property
  def run_id(self) -> str | None:
    return self._run_id

  @property
  def termination(self) -> Termination | None:
    return self._termination

  @property
  def geometry(self) -> FrameGeometry | None:
    return self._geometry

  def measurements(self, duration_seconds: float) -> Measurements:
    return Measurements(
      duration_seconds=duration_seconds,
      reported_cost=self._known_cost if self._counts["cost_measurements"] else None,
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

    if type(snapshot.step) is not int or snapshot.step != record.step:
      raise BenchmarkError("Snapshot and record step numbers do not match.")

    metrics = event.metrics or {}
    expected_numbers = {
      "step": record.step,
      "frame_width": record.frame.width,
      "frame_height": record.frame.height,
    }
    for name, expected in expected_numbers.items():
      actual = metrics.get(name)
      if type(actual) is not int or actual != expected:
        raise BenchmarkError(f"Event {name} does not match the step record.")

    if record.frame.filename != f"{record.step}.png":
      raise BenchmarkError("Snapshot filename does not match its step number.")

    if metrics.get("outcome") != record.outcome:
      raise BenchmarkError("Event outcome does not match the step record.")

    return record

  def _validate_cost(self, event: Event, record: StepView) -> float | None:
    raw = (event.metrics or {}).get("cost")
    if raw is None:
      return None

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
      raise BenchmarkError("Invalid reported cost in a step record.")

    try:
      cost = float(raw)
    except OverflowError as exc:
      raise BenchmarkError("Invalid reported cost in a step record.") from exc

    if not math.isfinite(cost) or cost < 0:
      raise BenchmarkError("Invalid reported cost in a step record.")

    if not any(attempt.status == "completed" for attempt in record.attempts):
      raise BenchmarkError("A reported cost requires a completed inference attempt.")

    return cost

  def observe(self, event: Event) -> Reply | None:
    run_id = self._validate_run_id(event)
    record = self._validate_snapshot(event, run_id)

    if self._termination is not None:
      if (
        self._termination in {"help", "limit"}
        and event.kind == "cancelled"
        and not self._cancellation_recorded
      ):
        self._cancellation_recorded = True
        return None

      raise BenchmarkError("Received an event after the trial had stopped.")

    geometry = self._geometry
    cost: float | None = None
    known_cost = self._known_cost
    if record is not None:
      if (record.run_id, record.step) in self._seen_steps:
        raise BenchmarkError("Duplicate captured step.")

      geometry = FrameGeometry(
        width=record.frame.width,
        height=record.frame.height,
        screen_rect=record.frame.screen_rect,
      )
      if self._geometry is not None and geometry != self._geometry:
        raise BenchmarkError("Capture geometry changed during the trial.")

      cost = self._validate_cost(event, record)
      if cost is not None:
        known_cost += cost
        if not math.isfinite(known_cost):
          raise BenchmarkError("Reported cost total is not finite.")

    if run_id is not None:
      self._run_id = run_id

    if record is not None:
      self._seen_steps.add((record.run_id, record.step))
      self._geometry = geometry
      self._known_cost = known_cost
      self._counts["captured_steps"] += 1
      if cost is not None:
        self._counts["cost_measurements"] += 1
      self._counts["attempts_without_cost"] += max(0, len(record.attempts) - int(cost is not None))
      for attempt in record.attempts:
        self._counts[f"{attempt.purpose}_attempts"] += 1
        if attempt.status == "invalid":
          self._counts["invalid_attempts"] += 1

      if record.refusal is not None:
        self._counts["refusals"] += 1
      if record.outcome == "rejected_done":
        self._counts["completion_rejections"] += 1

      stuck = (event.metrics or {}).get("stuck")
      if stuck == "warn":
        self._counts["stuck_warnings"] += 1
      elif stuck == "escalate":
        self._counts["stuck_escalations"] += 1

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
