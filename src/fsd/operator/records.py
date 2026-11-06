"""Allowlisted explanation records; the engine owns these, and the CLI persists them."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Literal

from fsd.operator.contracts import Decision, Snapshot, Verdict
from fsd.platform.base import Frame

Purpose = Literal["decision", "verification"]


@dataclass
class InferenceAttempt:
  purpose: Purpose
  number: int
  correction: str
  status: Literal["pending", "completed", "invalid", "interrupted", "error"] = "pending"
  response: dict[str, object] | None = None
  invalid_cause: str | None = None
  feedback: str = ""
  error_type: str | None = None

  def complete(self, response: Decision | Verdict) -> None:
    self.response = response.model_dump(mode="json")
    self.status = "completed"


@dataclass
class StepRecord:
  run_id: str
  step: int
  frame: Frame
  approved: frozenset[str]
  foreground_app: str | None = None
  observation: str | None = None
  goal: str | None = None
  previous_frame_step: int | None = None
  attempts: list[InferenceAttempt] = field(default_factory=list)
  refusal: dict[str, str | None] | None = None
  execution_status: str | None = None
  interruption: str | None = None
  pause: str | None = None

  def attempt(self, purpose: Purpose, correction: str) -> InferenceAttempt:
    attempt = InferenceAttempt(purpose, len(self.attempts) + 1, correction)
    self.attempts.append(attempt)
    return attempt

  def snapshot(self, outcome: str, feedback: str, warning: str) -> Snapshot:
    # Select fields explicitly: platform objects, HTTP state, and PNG bytes do not
    # belong in JSON. Detach nested values before delivering to an arbitrary sink.
    record: dict[str, object] = {
      "schema_version": 1,
      "run_id": self.run_id,
      "step": self.step,
      "outcome": outcome,
      "frame": {
        "filename": f"{self.step}.png",
        "width": self.frame.width,
        "height": self.frame.height,
        "screen_rect": asdict(self.frame.screen_rect),
      },
      "foreground_app": self.foreground_app,
      "input_approved_apps": sorted(self.approved),
      "observation": self.observation,
      "goal": self.goal,
      "previous_frame_step": self.previous_frame_step,
      "attempts": [asdict(attempt) for attempt in self.attempts],
      "refusal": self.refusal,
      "execution_status": self.execution_status,
      "interruption": self.interruption,
      "feedback": feedback,
      "warning": warning,
      "pause": self.pause,
    }
    return Snapshot(self.run_id, self.step, self.frame.png, deepcopy(record))
