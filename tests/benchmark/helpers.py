from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from fsd.approval.store import ApprovalStore
from fsd.benchmark.contracts import GoalScore, Measurements, RunManifest, TrialResult
from fsd.benchmark.storage import prepare_trial
from fsd.benchmark.tasks import task_for, task_manifest
from fsd.operator.config import Settings
from fsd.operator.contracts import Event
from fsd.operator.records import Purpose, StepRecord
from fsd.platform.base import Frame, Rect, WindowInfo
from fsd.platform.fake import FakePlatform
from tests.operator.helpers import decision, png, verdict

AttemptStatus = Literal["pending", "completed", "invalid", "interrupted", "error"]


def prepared_desktop(tmp_path: Path, task_id: str) -> tuple[Path, FakePlatform, ApprovalStore]:
  root = tmp_path / "trial"
  manifest = prepare_trial(root, task_id)
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve(manifest.app_id)
  bounds = Rect(0.0, 0.0, 100.0, 100.0)
  platform = FakePlatform(
    frontmost=manifest.app_id,
    windows=[WindowInfo(manifest.app_id, bounds, 0)],
    frames=[Frame(png(index), 100, 100, bounds) for index in range(30)],
  )
  return root, platform, store


def example_run(
  *,
  trial_id: str = "0123456789abcdef",
  task_id: str = "finder-rename",
  action_limit: int = 100,
) -> RunManifest:
  return RunManifest(
    trial_id=trial_id,
    task=task_manifest(task_for(task_id)),
    settings=replace(Settings(), action_limit=action_limit),
    approved_apps=("com.apple.finder",),
    started_at=datetime(2026, 11, 13, 12, tzinfo=UTC),
  )


def example_result(*, trial_id: str = "0123456789abcdef") -> TrialResult:
  return TrialResult(
    trial_id=trial_id,
    engine_run_id="run",
    termination="done",
    score=GoalScore(result="pass", evidence="Expected file contents matched."),
    infrastructure="ok",
    measurements=Measurements(duration_seconds=1.5),
    ended_at=datetime(2026, 11, 13, 12, 0, 2, tzinfo=UTC),
  )


def step_event(
  step: int,
  *,
  attempts: tuple[tuple[str, str], ...],
  cost: float | None = None,
  outcome: str = "performed",
  frame: Frame | None = None,
  refusal: dict[str, str | None] | None = None,
  stuck: Literal["warn", "escalate"] | None = None,
  warning: str = "",
) -> Event:
  if frame is None:
    frame = Frame(png(0), 100, 100, Rect(0.0, 0.0, 50.0, 50.0))
  record = StepRecord(
    "run",
    step,
    frame,
    frozenset({"app"}),
    refusal=refusal,
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
        verdict(complete=outcome != "rejected_done")
        if purpose == "verification"
        else decision("done" if has_verification else "act")
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
  if stuck is not None:
    metrics["stuck"] = stuck
  return Event(
    "metrics",
    "Step recorded",
    metrics=metrics,
    snapshot=record.snapshot(outcome, "", warning),
  )
