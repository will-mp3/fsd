import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from fsd.approval.store import ApprovalStore
from fsd.operator.client import InferenceError, InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.context import Observation, Session
from fsd.operator.contracts import Event, ModelResult, Reply
from fsd.operator.control import Control
from fsd.operator.engine import CORRECTION, Engine
from fsd.platform.fake import FakePlatform
from tests.operator.helpers import Recorder, ScriptedClient, decision, desktop, verdict


def run(
  platform: FakePlatform,
  store: ApprovalStore,
  client: ScriptedClient,
  recorder: Recorder | None = None,
) -> tuple[Recorder, list[dict[str, Any]]]:
  settings = Settings(verify_settle_ms=0)
  sink = recorder or Recorder([Reply(cancel=True)])
  asyncio.run(
    Engine(platform, store, client, settings).run("Inspect", Session(settings), Control(), sink)
  )
  return sink, records(sink)


def records(sink: Recorder) -> list[dict[str, Any]]:
  return [event.snapshot.record for event in sink.events if event.snapshot is not None]


@pytest.mark.parametrize("phase", ["decision", "verification"])
def test_corrected_attempts_keep_both_results_and_the_exact_sent_correction(
  tmp_path: Path, phase: str
) -> None:
  platform, store = desktop(tmp_path)
  invalid = InvalidDecision("schema", "invalid-response-feedback")
  chosen = decision()
  client = (
    ScriptedClient([invalid, chosen, decision("done")])
    if phase == "decision"
    else ScriptedClient([decision("done")], [invalid, verdict()])
  )
  sink, rows = run(platform, store, client)
  row = rows[0] if phase == "decision" else rows[1]
  first, second = row["attempts"]
  assert first["purpose"] == second["purpose"] == phase
  assert [first["number"], second["number"]] == [1, 2]
  assert first["status"] == "invalid"
  assert first["invalid_cause"] == "schema"
  assert first["feedback"] == "invalid-response-feedback"
  assert first["response"] is None
  assert first["correction"] == ""
  assert second["correction"] == f"{CORRECTION}\nFix these errors:\ninvalid-response-feedback"
  assert second["status"] == "completed"
  assert second["response"] == (chosen if phase == "decision" else verdict()).model_dump(
    mode="json"
  )
  assert "invalid-response-feedback" not in repr([event.metrics for event in sink.events])
  if phase == "decision":
    assert row["observation"] == client.observations[0].text
  else:
    assert row["observation"] is None
    assert row["goal"] == "Inspect"


def test_twice_invalid_retains_second_feedback_without_inventing_a_third_request(
  tmp_path: Path,
) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([InvalidDecision("schema", "first"), InvalidDecision("schema", "second")])
  _, rows = run(platform, store, client)
  assert len(rows) == 1
  assert rows[0]["outcome"] == "invalid"
  attempts = rows[0]["attempts"]
  assert len(attempts) == 2
  assert attempts[1]["feedback"] == "second"
  assert "second" not in attempts[1]["correction"]
  assert "two invalid responses" in rows[0]["feedback"]


def test_archive_keeps_both_verdict_outcomes_and_correlates_frames(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  client = ScriptedClient([decision("done"), decision("done")], [verdict(False), verdict()])
  sink, rows = run(platform, store, client)
  assert [row["outcome"] for row in rows] == [
    "claimed_done",
    "rejected_done",
    "claimed_done",
    "done",
  ]
  assert rows[1]["attempts"][0]["response"] == verdict(False).model_dump()
  assert rows[3]["attempts"][0]["response"] == verdict().model_dump()
  assert "Goal not visible" in rows[1]["feedback"]
  for index, row in enumerate(rows):
    assert row["schema_version"] == 1
    assert row["step"] == index
    assert row["run_id"] == rows[0]["run_id"]
    assert row["frame"] == {
      "filename": f"{index}.png",
      "width": 100,
      "height": 100,
      "screen_rect": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    assert row["foreground_app"] == "app"
    assert row["input_approved_apps"] == ["app"]
  assert "Goal visible" not in repr([event.metrics for event in sink.events])


def test_refused_action_retains_owner_arguments_and_corrective_feedback(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  platform.frontmost = "blocked.app"
  chosen = decision()
  _, rows = run(platform, store, ScriptedClient([chosen, decision("done")]))
  assert rows[0]["outcome"] == "refused"
  assert rows[0]["refusal"] == {"reason": "keyboard_focus", "owner": "blocked.app"}
  assert rows[0]["attempts"][0]["response"] == chosen.model_dump()
  assert "blocked.app" in rows[0]["feedback"]
  assert "Click inside" in rows[0]["feedback"]
  assert rows[0]["execution_status"].startswith("refused:")
  assert platform.actions == []


@pytest.mark.parametrize("cancel", [False, True])
def test_discarded_decision_is_retained_after_progress_boundary(
  tmp_path: Path, cancel: bool
) -> None:
  platform, store = desktop(tmp_path)
  control = Control()
  sink = Recorder()
  chosen = decision()
  settings = Settings(verify_settle_ms=0)

  async def emit(event: Event) -> Reply | None:
    if event.kind == "progress":
      if cancel:
        control.cancel()
      else:
        store.block("app")
    return await sink(event)

  asyncio.run(
    Engine(platform, store, ScriptedClient([chosen, decision("done")]), settings).run(
      "Inspect", Session(settings), control, emit
    )
  )
  row = records(sink)[0]
  assert row["outcome"] == ("interrupted" if cancel else "approvals_changed")
  assert row["attempts"][0]["response"] == chosen.model_dump()
  assert platform.actions == []


def test_inference_failure_records_category_without_exception_secrets(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  _, rows = run(platform, store, ScriptedClient([InferenceError("secret-transport-data")]))
  assert rows[0]["outcome"] == "interrupted"
  attempt = rows[0]["attempts"][0]
  assert attempt["status"] == "error"
  assert attempt["error_type"] == "InferenceError"
  assert attempt["response"] is None
  assert "secret-transport-data" not in json.dumps(rows)


def test_records_remain_detached_after_session_and_attempt_changes(tmp_path: Path) -> None:
  from fsd.operator.records import StepRecord

  platform, store = desktop(tmp_path)
  frame = platform.capture()
  record = StepRecord("run", 0, frame, store.approved())
  attempt = record.attempt("decision", "")
  attempt.complete(decision())
  record.observation = "original"
  snapshot = record.snapshot("performed", "feedback", "")
  attempt.response = {"changed": True}
  record.observation = "changed"
  assert snapshot.record["observation"] == "original"
  assert snapshot.record["attempts"][0]["response"] == decision().model_dump()  # type: ignore[index]


@pytest.mark.parametrize("task_cancel", [False, True])
def test_cancelled_inference_records_an_unfinished_attempt_once(
  tmp_path: Path, task_cancel: bool
) -> None:
  platform, store = desktop(tmp_path)
  settings = Settings()
  control = Control()
  sink = Recorder()

  async def exercise() -> None:
    started = asyncio.Event()

    class WaitingClient(ScriptedClient):
      async def decide(
        self, observation: Observation, control: Control, correction: str = ""
      ) -> ModelResult:
        started.set()
        await asyncio.Future[None]()
        raise AssertionError("Waiting request must not complete")

    engine = Engine(platform, store, WaitingClient([]), settings)
    task = asyncio.create_task(engine.run("Inspect", Session(settings), control, sink))
    await started.wait()
    if task_cancel:
      task.cancel()
      with pytest.raises(asyncio.CancelledError):
        await task
    else:
      control.cancel()
      await task
    assert engine._active is None

  asyncio.run(exercise())
  rows = records(sink)
  assert len(rows) == 1
  assert rows[0]["outcome"] == "interrupted"
  assert rows[0]["interruption"] == ("CancelledError" if task_cancel else "RunCancelled")
  assert rows[0]["attempts"][0]["status"] == "interrupted"
  assert rows[0]["attempts"][0]["response"] is None
  assert platform.actions == []


def test_previous_frame_links_to_its_original_step(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  _, rows = run(platform, store, ScriptedClient([decision(), decision(), decision("done")]))
  assert [row["previous_frame_step"] for row in rows] == [None, 0, 1, None]


def test_approval_change_during_verification_retains_the_discarded_verdict(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)

  class ChangedClient(ScriptedClient):
    async def verify(self, goal: str, frame: Any, control: Control, correction: str = "") -> Any:
      result = await super().verify(goal, frame, control, correction)
      store.block("app")
      return result

  _, rows = run(platform, store, ChangedClient([decision("done"), decision("help")]))
  assert rows[1]["outcome"] == "approvals_changed"
  assert rows[1]["attempts"][0]["response"] == verdict().model_dump()


def test_focus_change_help_is_archived_before_the_owner_can_cancel(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  original = platform.press_keys

  def switch_focus(combo: str) -> None:
    original(combo)
    platform.frontmost = "blocked.app"

  platform.press_keys = switch_focus  # type: ignore[method-assign]
  sink, rows = run(platform, store, ScriptedClient([decision()]))
  assert len(rows) == 1
  assert rows[0]["outcome"] == "performed"
  pause = next(event.message for event in sink.events if event.kind == "help")
  assert "unapproved" in pause
  assert "blocked.app" in pause
  assert rows[0]["pause"] == rows[0]["feedback"] == pause


def test_inflight_timeout_archives_budget_pause_and_unfinished_attempt(tmp_path: Path) -> None:
  platform, store = desktop(tmp_path)
  sink, rows = run(platform, store, ScriptedClient([TimeoutError("private-timeout-message")]))
  assert len(rows) == 1
  row = rows[0]
  assert row["outcome"] == "interrupted"
  assert row["interruption"] == "TimeoutError"
  assert row["attempts"][0]["status"] == "interrupted"
  pause = next(event.message for event in sink.events if event.kind == "help")
  assert row["pause"] == row["feedback"] == pause
  assert "budget" in pause
  assert "private-timeout-message" not in json.dumps(row)
