import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from fsd.operator.client import InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.context import Observation, Session
from fsd.operator.contracts import Event, Hold, ModelResult, Reply, TypeText
from fsd.operator.control import Control
from fsd.operator.engine import Engine
from fsd.platform.base import Capability, MissingPermission
from fsd.platform.fake import FakePlatform
from fsd.platform.held_input import ReleaseError
from tests.operator.helpers import Recorder, ScriptedClient, decision, desktop


def test_done_records_completion_without_input(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings()
  session = Session(settings)
  recorder = Recorder()
  client = ScriptedClient([decision("done")])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Check whether the goal is complete", session, Control(), recorder
    )
  )
  assert platform.capture_requests == [frozenset({"app"})]
  assert platform.actions == []
  assert recorder.events[-1].kind == "done"
  assert session.history[-1]["status"] == "completed"
  assert session.history[-1]["action"] is None


def test_help_then_done_uses_fresh_observation_and_guidance(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings()
  recorder = Recorder([Reply(text="The October document is already open")])
  client = ScriptedClient([decision("help"), decision("done")])
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Find the October document", Session(settings), Control(), recorder
    )
  )
  assert platform.actions == []
  assert platform.capture_requests == [frozenset({"app"}), frozenset({"app"})]
  assert len(client.observations) == 2
  assert client.observations[1].current.png != client.observations[0].current.png
  assert client.observations[1].previous is None
  assert "The October document is already open" in client.observations[1].text
  assert [event.kind for event in recorder.events if event.kind != "metrics"] == ["help", "done"]


def test_multiple_actions_do_not_require_confirmation(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision(combo="space"), decision("done")])
  recorder = Recorder()
  settings = Settings()
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Complete the goal",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert platform.actions == [("press_keys", "return"), ("press_keys", "space")]
  assert len(platform.capture_requests) == 3
  assert all(request == frozenset({"app"}) for request in platform.capture_requests)
  assert not any(e.kind == "help" for e in recorder.events)
  assert recorder.events[-1].kind == "done"


def test_help_captures_again_and_keeps_running(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("help"), decision(), decision("done")])
  recorder = Recorder([Reply(text="Use the October document")])
  settings = Settings()
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
  client = ScriptedClient([InvalidDecision("bad"), InvalidDecision("bad")])
  settings = Settings()
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


def test_gate_refusal_does_not_replay_pending_action(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  platform.frontmost = "unapproved"
  client = ScriptedClient([decision(), decision("done")])
  recorder = Recorder([Reply(text="Cancel that keystroke; goal already complete")])
  settings = Settings()

  async def emit(event: Event) -> Reply | None:
    if event.kind == "help":
      platform.frontmost = "app"
    return await recorder(event)

  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Inspect",
      Session(settings),
      Control(),
      emit,
    )
  )
  assert platform.actions == []
  assert len(client.observations) == 2
  assert platform.frontmost == "app"
  assert recorder.events[-1].kind == "done"


def test_budget_requires_explicit_extension(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision("done")])
  recorder = Recorder([Reply(text="Keep going"), Reply(extend=True)])
  settings = Settings(action_limit=1)
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
  settings = Settings()
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
  settings = Settings()
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
  settings = Settings()
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
  settings = Settings()
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
  settings = Settings()
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
  settings = Settings()
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
