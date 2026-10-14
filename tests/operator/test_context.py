import json

import pytest

from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.contracts import Decision
from fsd.platform.base import Frame, Rect


def frame(value: bytes) -> Frame:
  return Frame(value, 100, 100, Rect(0, 0, 100, 100))


def opening_decision() -> Decision:
  return Decision.model_validate(
    {
      "kind": "act",
      "action": {"kind": "key", "combo": "return"},
      "message": "Opening",
      "expected": "Document opens",
      "notes": "October document",
      "previous_result": "none",
    }
  )


@pytest.mark.parametrize(
  "approved",
  [frozenset(), frozenset({"two"}), frozenset({"one", "two"})],
)
def test_previous_frame_is_dropped_after_approval_change(approved: frozenset[str]) -> None:
  session = Session(Settings())
  session.begin("Find the document")
  first = session.observe(frame(b"first"), frozenset({"one"}))
  second = session.observe(frame(b"second"), frozenset({"one"}))
  third = session.observe(frame(b"third"), approved)
  fourth = session.observe(frame(b"fourth"), approved)
  assert first.current.png == b"first"
  assert first.previous is None
  assert second.previous == first.current
  assert third.previous is None
  assert third.current.png == b"third"
  assert fourth.previous == third.current


def test_history_stays_bounded_and_followup_keeps_notes() -> None:
  session = Session(Settings(history_size=2))
  session.begin("Open a document")
  session.observe(frame(b"old"), frozenset({"one"}))
  session.guide("Use the file list")
  for index in range(5):
    decision = opening_decision().model_copy(update={"message": f"Opening {index}"})
    session.record(decision, "performed")
  session.begin("Now scroll down")
  observation = session.observe(frame(b"next"), frozenset({"one"}))
  data = json.loads(observation.text)
  assert [entry["message"] for entry in data["history"]] == ["Opening 3", "Opening 4"]
  assert data["history"][-1]["action"] == {"kind": "key", "combo": "return"}
  assert data["history"][-1]["expected"] == "Document opens"
  assert data["history"][-1]["status"] == "performed"
  assert data["notes"] == "October document"
  assert data["goal"] == "Now scroll down"
  assert data["recent_goals"] == ["Open a document", "Now scroll down"]
  assert data["guidance"] == []
  assert observation.previous is None


def test_guidance_discards_stale_visual_context() -> None:
  session = Session(Settings())
  session.observe(frame(b"old"), frozenset({"one"}))
  session.guide("I moved the window; continue")
  observation = session.observe(frame(b"fresh"), frozenset({"one"}))
  assert observation.previous is None
  assert json.loads(observation.text)["guidance"] == ["I moved the window; continue"]


def test_engine_notices_do_not_overwrite_user_guidance() -> None:
  session = Session(Settings())
  session.guide("Use the October document")
  session.observe(frame(b"old"), frozenset({"one"}))
  session.notice("Window moved; capture again")
  observation = session.observe(frame(b"new"), frozenset({"one"}))
  data = json.loads(observation.text)
  assert data["guidance"] == ["Use the October document"]
  assert data["feedback"] == "Window moved; capture again"
  assert observation.previous is None


def test_observation_is_a_snapshot_of_session_context() -> None:
  session = Session(Settings())
  session.begin("Open a document")
  session.record(opening_decision(), "performed")
  session.observe(frame(b"first"), frozenset({"one"}))
  observation = session.observe(frame(b"second"), frozenset({"one"}))
  original_text = observation.text

  session.guide("Use another document")
  session.record(opening_decision(), "blocked")
  session.begin("Now scroll down")
  session.observe(frame(b"third"), frozenset({"two"}))

  assert observation.text == original_text
  assert json.loads(observation.text)["goal"] == "Open a document"
  assert observation.current.png == b"second"
  assert observation.previous is not None
  assert observation.previous.png == b"first"
