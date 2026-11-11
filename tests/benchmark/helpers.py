from typing import Literal, cast

from fsd.operator.contracts import Event
from fsd.operator.records import Purpose, StepRecord
from fsd.platform.base import Frame, Rect
from tests.operator.helpers import decision, png, verdict

AttemptStatus = Literal["pending", "completed", "invalid", "interrupted", "error"]


def step_event(
  step: int,
  *,
  attempts: tuple[tuple[str, str], ...],
  cost: float | None = None,
  outcome: str = "performed",
  frame: Frame | None = None,
) -> Event:
  if frame is None:
    frame = Frame(png(0), 100, 100, Rect(0.0, 0.0, 50.0, 50.0))
  record = StepRecord(
    "run",
    step,
    frame,
    frozenset({"app"}),
  )
  has_verification = any(purpose == "verification" for purpose, _ in attempts)
  for purpose, status in attempts:
    if purpose not in {"decision", "verification"}:
      raise ValueError(f"Unknown test attempt purpose: {purpose}")
    if status not in {"pending", "completed", "invalid", "interrupted", "error"}:
      raise ValueError(f"Unknown test attempt status: {status}")
    attempt = record.attempt(cast(Purpose, purpose), "")
    if status == "completed":
      attempt.complete(
        verdict() if purpose == "verification" else decision("done" if has_verification else "act")
      )
    else:
      attempt.status = cast(AttemptStatus, status)

  metrics: dict[str, object] = {
    "run_id": "run",
    "step": step,
    "frame_width": frame.width,
    "frame_height": frame.height,
    "outcome": outcome,
  }
  if cost is not None:
    metrics["cost"] = cost
  return Event(
    "metrics",
    "Step recorded",
    metrics=metrics,
    snapshot=record.snapshot(outcome, "", ""),
  )
