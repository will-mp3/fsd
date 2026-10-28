import asyncio
import json
from collections.abc import Callable, Collection
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from fsd.approval.store import ApprovalStore
from fsd.operator import engine as engine_module
from fsd.operator.client import InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.context import Observation, Session
from fsd.operator.contracts import Event, Hold, ModelResult, Reply, TypeText, VerificationResult
from fsd.operator.control import Control
from fsd.operator.engine import Engine
from fsd.platform.base import Capability, Frame, MissingPermission
from fsd.platform.fake import FakePlatform
from fsd.platform.held_input import ReleaseError
from tests.operator.helpers import (
  Recorder,
  ScriptedClient,
  decision,
  desktop,
  still_desktop,
  verdict,
)


def test_done_records_completion_without_input(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  session = Session(settings)
  recorder = Recorder()
  client = ScriptedClient([decision("done")])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Check whether the goal is complete", session, Control(), recorder
    )
  )
  assert platform.capture_requests == [frozenset({"app"})] * 2
  assert len(client.verifications) == 1
  assert platform.actions == []
  assert recorder.events[-1].kind == "done"
  assert session.history[-1]["status"] == "completed"
  assert session.history[-1]["action"] is None


def test_help_then_done_uses_fresh_observation_and_guidance(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  recorder = Recorder([Reply(text="The October document is already open")])
  client = ScriptedClient([decision("help"), decision("done")])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Find the October document", Session(settings), Control(), recorder
    )
  )
  assert platform.actions == []
  assert platform.capture_requests == [frozenset({"app"})] * 3
  assert len(client.observations) == 2
  assert client.observations[1].current.png != client.observations[0].current.png
  assert client.observations[1].previous is None
  assert "The October document is already open" in client.observations[1].text
  assert [event.kind for event in recorder.events if event.kind != "metrics"] == ["help", "done"]


def test_multiple_actions_do_not_require_confirmation(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision(combo="space"), decision("done")])
  recorder = Recorder()
  settings = Settings(verify_settle_ms=0)
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Complete the goal",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert platform.actions == [("press_keys", "return"), ("press_keys", "space")]
  assert len(platform.capture_requests) == 4
  assert all(request == frozenset({"app"}) for request in platform.capture_requests)
  assert not any(e.kind == "help" for e in recorder.events)
  assert recorder.events[-1].kind == "done"


def test_help_captures_again_and_keeps_running(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("help"), decision(), decision("done")])
  recorder = Recorder([Reply(text="Use the October document")])
  settings = Settings(verify_settle_ms=0)
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Open the document",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert len(platform.actions) == 1
  assert client.observations[1].previous is None
  assert "October" in client.observations[1].text
  assert client.observations[0].current.png != client.observations[1].current.png


def test_two_invalid_decisions_pause_without_input(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([InvalidDecision("schema"), InvalidDecision("schema")])
  settings = Settings(verify_settle_ms=0)
  recorder = Recorder([Reply(cancel=True)])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Do something",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert platform.actions == []
  assert any(e.kind == "help" for e in recorder.events)
  assert recorder.events[-1].kind == "cancelled"


def test_budget_requires_explicit_extension(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision("done")])
  recorder = Recorder([Reply(text="Keep going"), Reply(extend=True)])
  settings = Settings(verify_settle_ms=0, action_limit=1)
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Finish",
      Session(settings),
      Control(),
      recorder,
    )
  )
  help_events = [event for event in recorder.events if event.kind == "help"]
  assert len(help_events) == 2
  assert all(event.limit for event in help_events)
  assert recorder.events[-1].kind == "done"


def test_missing_permission_fails_before_capture(tmp_path: Path) -> None:
  _, store = desktop(tmp_path)
  platform = FakePlatform(missing_permissions=[MissingPermission("Screen Recording", "Grant it")])
  client = ScriptedClient([])
  recorder = Recorder()
  settings = Settings(verify_settle_ms=0)
  asyncio.run(
    Engine(platform, store, client, settings).run("Act", Session(settings), Control(), recorder)
  )
  assert platform.capture_requests == []
  assert platform.actions == []
  assert client.observations == []
  assert recorder.events[-1].kind == "failed"
  assert "Screen Recording" in recorder.events[-1].message


@pytest.mark.parametrize(
  "capabilities",
  [
    frozenset(),
    frozenset({Capability.FILTERED_CAPTURE}),
    frozenset({Capability.WINDOW_OWNER_LOOKUP}),
  ],
)
def test_missing_capability_fails_before_capture(
  tmp_path: Path, capabilities: frozenset[Capability]
) -> None:
  _, store = desktop(tmp_path)
  platform = FakePlatform(capabilities=capabilities)
  client = ScriptedClient([])
  recorder = Recorder()
  settings = Settings(verify_settle_ms=0)
  asyncio.run(
    Engine(platform, store, client, settings).run("Act", Session(settings), Control(), recorder)
  )
  assert platform.capture_requests == []
  assert platform.actions == []
  assert client.observations == []
  assert recorder.events[-1].kind == "failed"


def test_failed_startup_does_not_block_later_run(tmp_path: Path) -> None:
  _, store = desktop(tmp_path)
  platform = FakePlatform(missing_permissions=[MissingPermission("Screen Recording", "Grant it")])
  settings = Settings(verify_settle_ms=0)
  engine = Engine(platform, store, ScriptedClient([]), settings)
  recorder = Recorder()
  session = Session(settings)

  async def scenario() -> None:
    await engine.run("First goal", session, Control(), recorder)
    await engine.run("Second goal", session, Control(), recorder)

  asyncio.run(scenario())
  assert [event.kind for event in recorder.events] == ["failed", "failed"]
  assert all("Screen Recording" in event.message for event in recorder.events)


def test_cancel_after_model_response_prevents_input(tmp_path: Path) -> None:
  class CancellingClient(ScriptedClient):
    async def decide(
      self, observation: Observation, control: Control, correction: str = ""
    ) -> ModelResult:
      result = await super().decide(observation, control, correction)
      control.cancel()
      return result

  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  recorder = Recorder()
  asyncio.run(
    Engine(platform, store, CancellingClient([decision()]), settings).run(
      "Act", Session(settings), Control(), recorder
    )
  )
  assert platform.actions == []
  assert recorder.events[-1].kind == "cancelled"


def test_partial_typing_is_recorded_before_cancellation(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  control = Control()

  def interrupted_type(text: str, check: Callable[[], None]) -> None:
    check()
    platform.actions.append(("type_character", text[0]))
    control.cancel()
    check()

  platform.type_text_checked = interrupted_type  # type: ignore[method-assign]
  choice = decision().model_copy(update={"action": TypeText(kind="type", text="hello")})
  settings = Settings(verify_settle_ms=0)
  session = Session(settings)
  recorder = Recorder()
  asyncio.run(
    Engine(platform, store, ScriptedClient([choice]), settings).run(
      "Type hello", session, control, recorder
    )
  )
  assert platform.actions == [("type_character", "h")]
  assert "partially" in str(session.history[-1]["status"])
  assert recorder.events[-1].kind == "cancelled"


def test_failed_release_blocks_later_goals(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)

  def failed_hold(key: str, duration_ms: int, check: Callable[[], None]) -> None:
    check()
    platform.actions.append(("hold_key", key, duration_ms))
    raise ReleaseError("Key release failed")

  platform.hold_key = failed_hold  # type: ignore[method-assign]
  choice = decision().model_copy(update={"action": Hold(kind="hold", key="left", duration_ms=20)})
  client = ScriptedClient([choice, decision()])
  settings = Settings(verify_settle_ms=0)
  engine = Engine(platform, store, client, settings)
  recorder = Recorder()
  session = Session(settings)

  async def scenario() -> None:
    await engine.run("Move", session, Control(), recorder)
    await engine.run("Try again", session, Control(), recorder)

  asyncio.run(scenario())
  assert len(platform.actions) == 1
  assert len(client.observations) == 1
  assert "release failed" in str(session.history[-1]["status"])
  assert recorder.events[-1].kind == "failed"
  assert "restart" in recorder.events[-1].message


def test_metrics_distinguish_capture_inference_and_action_time(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  platform, store = desktop(tmp_path)
  now = 100.0
  monkeypatch.setattr(engine_module, "time", SimpleNamespace(monotonic=lambda: now))
  original_capture = platform.capture
  original_press_keys = platform.press_keys

  def capture(bundle_ids: Collection[str]) -> Frame:
    nonlocal now
    now += 2.0
    return original_capture(bundle_ids)

  def press_keys(combo: str) -> None:
    nonlocal now
    now += 5.0
    original_press_keys(combo)

  class TimedClient(ScriptedClient):
    async def decide(
      self, observation: Observation, control: Control, correction: str = ""
    ) -> ModelResult:
      nonlocal now
      result = await super().decide(observation, control, correction)
      now += 3.0
      return replace(result, request_seconds=3.0, cost=None)

  monkeypatch.setattr(platform, "capture", capture)
  monkeypatch.setattr(platform, "press_keys", press_keys)
  recorder = Recorder()

  async def emit(event: Event) -> Reply | None:
    nonlocal now
    if event.kind == "progress":
      now += 7.0
    return await recorder(event)

  settings = Settings(verify_settle_ms=0)
  client = TimedClient([decision(), decision("done")])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Act then inspect", Session(settings), Control(), emit
    )
  )
  metrics = [
    event.metrics
    for event in recorder.events
    if event.kind == "metrics"
    and event.metrics
    and event.metrics.get("decision") in {"act", "done"}
  ]
  assert len(metrics) == 2
  for payload in metrics:
    assert payload is not None
    assert payload["capture_seconds"] == 2.0
    assert payload["request_seconds"] == 3.0
    assert payload["screenshot_to_decision_seconds"] == 5.0
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] == 5
    assert payload["cost"] is None

  action_events = [event for event in recorder.events if event.kind == "action"]
  assert len(action_events) == 1
  action_metrics = action_events[0].metrics
  assert action_metrics is not None
  assert action_metrics["action"] == "key"
  assert action_metrics["execution_seconds"] == 5.0
  assert action_metrics["screenshot_to_action_seconds"] == 12.0
  assert platform.actions == [("press_keys", "return")]
  assert recorder.events[-1].kind == "done"


@pytest.mark.parametrize("outcome", ["none", "success", "failure", "uncertain"])
def test_metrics_preserve_model_assessment_of_previous_action(tmp_path: Path, outcome: str) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  recorder = Recorder()
  client = ScriptedClient(
    [
      decision().model_copy(update={"previous_result": "none"}),
      decision("done").model_copy(update={"previous_result": outcome}),
    ]
  )

  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Act then inspect", Session(settings), Control(), recorder
    )
  )

  metrics = [
    event.metrics
    for event in recorder.events
    if event.kind == "metrics"
    and event.metrics
    and event.metrics.get("decision") in {"act", "done"}
  ]
  assert len(metrics) == 2
  assert metrics[0] is not None
  assert metrics[0]["previous_result"] == "none"
  assert metrics[1] is not None
  assert metrics[1]["previous_result"] == outcome
  assert platform.actions == [("press_keys", "return")]


def test_cancellation_during_progress_prevents_input(tmp_path: Path) -> None:
  # The last await before input; cancelling there must stop the action.
  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  control = Control()
  events: list[Event] = []

  async def emit(event: Event) -> Reply | None:
    events.append(event)
    if event.kind == "progress":
      control.cancel()
    return None

  client = ScriptedClient([decision()])
  asyncio.run(
    Engine(platform, store, client, settings).run("Inspect", Session(settings), control, emit)
  )
  assert platform.actions == []
  assert events[-1].kind == "cancelled"


def test_cancellation_while_verifying_claims_nothing(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings(verify_settle_ms=0)
  control = Control()

  class CancellingVerifier(ScriptedClient):
    async def verify(
      self, goal: str, frame: Frame, control: Control, correction: str = ""
    ) -> VerificationResult:
      control.cancel()
      return await super().verify(goal, frame, control, correction)

  recorder = Recorder()
  asyncio.run(
    Engine(platform, store, CancellingVerifier([decision("done")]), settings).run(
      "Inspect", Session(settings), control, recorder
    )
  )
  assert [e.kind for e in recorder.events if e.kind in {"done", "cancelled"}] == ["cancelled"]


def run_engine(
  platform: FakePlatform,
  store: ApprovalStore,
  client: ScriptedClient,
  recorder: Recorder,
  settings: Settings | None = None,
) -> Session:
  settings = settings or Settings(verify_settle_ms=0)
  session = Session(settings)
  asyncio.run(Engine(platform, store, client, settings).run("Goal", session, Control(), recorder))
  return session


def steps(recorder: Recorder) -> list[dict[str, object]]:
  return [e.metrics for e in recorder.events if e.kind == "metrics" and e.metrics is not None]


def test_single_refusal_returns_hint_without_pausing(tmp_path: Path) -> None:
  # The main policy change: a refusal is feedback, not a stop.
  platform, store = desktop(tmp_path)
  platform.frontmost = "com.example.hidden"
  client = ScriptedClient([decision(), decision("done")])
  recorder = Recorder([Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  assert not any(e.kind == "help" for e in recorder.events)
  assert platform.actions == []
  assert recorder.events[-1].kind == "done"
  assert len(client.observations) == 2
  second = json.loads(client.observations[1].text)
  assert "Keyboard focus is on a window you cannot see" in second["feedback"]
  assert steps(recorder)[0]["outcome"] == "refused"
  assert steps(recorder)[0]["refusal"] == "keyboard_focus"


def test_agent_context_never_names_the_refusing_app(tmp_path: Path) -> None:
  # Bundle IDs are enforcement metadata; only the owner sees them, even after
  # the owner continues from the pause.
  platform, store = desktop(tmp_path)
  platform.frontmost = "com.example.hidden"
  client = ScriptedClient([decision()] * 3 + [decision("done")])
  recorder = Recorder([Reply(text="Try again"), Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  assert len(client.observations) == 4
  assert all("com.example.hidden" not in o.text for o in client.observations)
  help_event = next(e for e in recorder.events if e.kind == "help")
  assert "com.example.hidden" in help_event.message


def test_third_consecutive_refusal_pauses(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  platform.frontmost = "com.example.hidden"
  client = ScriptedClient([decision()] * 3)
  recorder = Recorder([Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  assert len(client.observations) == 3
  assert [e.kind for e in recorder.events][-2:] == ["help", "cancelled"]


def test_total_refusal_limit_is_wired_independently_of_streak(tmp_path: Path) -> None:
  # Interleaving is unit-tested in test_recovery; this checks the engine uses
  # the total limit at all.
  platform, store = desktop(tmp_path)
  platform.frontmost = "com.example.hidden"
  client = ScriptedClient([decision()] * 3)
  recorder = Recorder([Reply(cancel=True)])
  settings = Settings(verify_settle_ms=0, refusal_streak_limit=100, refusal_total_limit=2)
  run_engine(platform, store, client, recorder, settings)
  assert sum(1 for s in steps(recorder) if s.get("outcome") == "refused") == 2
  assert [e.kind for e in recorder.events][-2:] == ["help", "cancelled"]


def test_focus_moving_to_unapproved_app_still_pauses_immediately(tmp_path: Path) -> None:
  # Safety pause survives the policy change: it may need authorization.
  platform, store = desktop(tmp_path)
  original = platform.press_keys

  def press_keys(combo: str) -> None:
    original(combo)
    platform.frontmost = "com.example.hidden"

  platform.press_keys = press_keys  # type: ignore[method-assign]
  client = ScriptedClient([decision()])
  recorder = Recorder([Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  help_event = next(e for e in recorder.events if e.kind == "help")
  assert "unapproved" in help_event.message


def test_actions_without_visible_change_warn_then_escalate(tmp_path: Path) -> None:
  platform, store = still_desktop(tmp_path, [200] * 8)
  client = ScriptedClient([decision()] * 6)
  recorder = Recorder([Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  assert [s.get("stuck") for s in steps(recorder)] == [None, None, "warn", None, "escalate"]
  warned = next(o for o in client.observations if "no visible progress" in o.text)
  assert json.loads(warned.text)["failed_strategies"]
  assert any(e.kind == "help" for e in recorder.events)


def test_visible_changes_never_warn(tmp_path: Path) -> None:
  # Real progress must not be mistaken for being stuck.
  platform, store = still_desktop(tmp_path, [0, 40, 80, 120, 160, 200])
  client = ScriptedClient([decision()] * 4 + [decision("done")])
  recorder = Recorder()
  run_engine(platform, store, client, recorder)
  assert all("stuck" not in s for s in steps(recorder))
  assert recorder.events[-1].kind == "done"


def test_rejected_completion_continues_with_evidence(tmp_path: Path) -> None:
  # The case verification exists for: a premature done claim.
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done"), decision("done")], [verdict(False), verdict()])
  recorder = Recorder()
  run_engine(platform, store, client, recorder)
  assert recorder.events[-1].kind == "done"
  assert len(client.observations) == 2
  second = json.loads(client.observations[1].text)
  assert "Goal not visible" in second["feedback"]
  assert [s["outcome"] for s in steps(recorder)] == [
    "claimed_done",
    "rejected_done",
    "claimed_done",
    "done",
  ]


def test_second_rejected_completion_pauses(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done")] * 2, [verdict(False), verdict(False)])
  recorder = Recorder([Reply(cancel=True)])
  run_engine(platform, store, client, recorder)
  assert not any(e.kind == "done" for e in recorder.events)
  assert any(e.kind == "help" for e in recorder.events)


def test_verifier_receives_goal_and_fresh_frame(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done")])
  run_engine(platform, store, client, Recorder())
  assert len(client.verifications) == 1
  goal, frame = client.verifications[0]
  assert goal == "Goal"
  assert frame.png == b"frame-1"


def test_every_step_is_traced_with_run_identity(tmp_path: Path) -> None:
  # Gaps in the trace would bias stage 2 comparisons.
  platform, store = desktop(tmp_path)
  client = ScriptedClient([InvalidDecision("schema"), decision(), decision("done")])
  recorder = Recorder()
  run_engine(platform, store, client, recorder)
  records = steps(recorder)
  assert [r.get("step") for r in records] == list(range(len(records)))
  assert len({r["run_id"] for r in records}) == 1
  assert records[0]["invalid_cause"] == "schema"
  assert records[0]["outcome"] == "performed"
  assert records[0]["bundle_id"] == "app"
  assert records[0]["images_sent"] == 1
  assert all(r["cached_input_tokens"] is None for r in records if "decision" in r)
  snapshots = [e.snapshot for e in recorder.events if e.snapshot is not None]
  assert [s.step for s in snapshots] == [r["step"] for r in records]
  lifecycle = [e for e in recorder.events if e.kind in {"action", "done"}]
  assert all(e.metrics and e.metrics["run_id"] == records[0]["run_id"] for e in lifecycle)
