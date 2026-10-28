import io
from collections import deque
from pathlib import Path

from PIL import Image

from fsd.approval.store import ApprovalStore
from fsd.operator.context import Observation
from fsd.operator.contracts import Decision, Event, ModelResult, Reply, Verdict, VerificationResult
from fsd.operator.control import Control
from fsd.platform.base import Frame, Rect, WindowInfo
from fsd.platform.fake import FakePlatform


def decision(kind: str = "act", combo: str = "return") -> Decision:
  return Decision.model_validate(
    {
      "kind": kind,
      "action": {"kind": "key", "combo": combo} if kind == "act" else None,
      "message": "Continue" if kind == "act" else "Task complete",
      "expected": "Visible change",
      "notes": "Progress",
      "previous_result": "success",
    }
  )


def verdict(complete: bool = True) -> Verdict:
  return Verdict(complete=complete, evidence="Goal visible" if complete else "Goal not visible")


class ScriptedClient:
  def __init__(
    self,
    decisions: list[Decision | Exception],
    verdicts: list[Verdict | Exception] | None = None,
  ) -> None:
    self.decisions = deque(decisions)
    self.verdicts = deque(verdicts or [])
    self.observations: list[Observation] = []
    self.verifications: list[tuple[str, Frame]] = []

  async def decide(
    self,
    observation: Observation,
    control: Control,
    correction: str = "",
  ) -> ModelResult:
    self.observations.append(observation)
    control.check()
    item = self.decisions.popleft()
    if isinstance(item, Exception):
      raise item
    return ModelResult(item, 0.01, 10, 5, 0.0001)

  async def verify(
    self,
    goal: str,
    frame: Frame,
    control: Control,
    correction: str = "",
  ) -> VerificationResult:
    self.verifications.append((goal, frame))
    control.check()
    item = self.verdicts.popleft() if self.verdicts else verdict()
    if isinstance(item, Exception):
      raise item
    return VerificationResult(item, 0.01, 10, 5, 0.0001)


class Recorder:
  def __init__(self, replies: list[Reply] | None = None) -> None:
    self.events: list[Event] = []
    self.replies = deque(replies or [])

  async def __call__(self, event: Event) -> Reply | None:
    self.events.append(event)
    return self.replies.popleft() if event.kind == "help" else None


def desktop(tmp_path: Path) -> tuple[FakePlatform, ApprovalStore]:
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve("app")
  frames = [Frame(f"frame-{n}".encode(), 100, 100, Rect(0, 0, 100, 100)) for n in range(30)]
  platform = FakePlatform(
    frontmost="app", frames=frames, windows=[WindowInfo("app", Rect(0, 0, 100, 100), 0)]
  )
  return platform, store


def png(shade: int) -> bytes:
  buffer = io.BytesIO()
  Image.new("L", (100, 100), shade).save(buffer, format="PNG")
  return buffer.getvalue()


def still_desktop(tmp_path: Path, shades: list[int]) -> tuple[FakePlatform, ApprovalStore]:
  store = ApprovalStore(tmp_path / "approvals.json")
  store.approve("app")
  frames = [Frame(png(shade), 100, 100, Rect(0, 0, 100, 100)) for shade in shades]
  platform = FakePlatform(
    frontmost="app", frames=frames, windows=[WindowInfo("app", Rect(0, 0, 100, 100), 0)]
  )
  return platform, store
