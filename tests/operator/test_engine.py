import asyncio
from pathlib import Path

from fsd.operator.client import InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.contracts import Reply
from fsd.operator.control import Control
from fsd.operator.engine import Engine
from tests.operator.helpers import Recorder, ScriptedClient, decision, desktop


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
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Inspect",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert platform.actions == []
  assert len(client.observations) == 2


def test_budget_requires_explicit_extension(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision(), decision("done")])
  recorder = Recorder([Reply(extend=True)])
  settings = Settings(action_limit=1)
  asyncio.run(
    Engine(platform, store, client, settings).run(
      "Finish",
      Session(settings),
      Control(),
      recorder,
    )
  )
  assert any(e.kind == "help" and e.limit for e in recorder.events)
  assert recorder.events[-1].kind == "done"
