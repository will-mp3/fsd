import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError
from fsd.operator.config import Settings
from fsd.operator.contracts import Event
from tests.benchmark.helpers import example_run, step_event


def test_events_preserve_order_without_serializing_messages(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial
  events = [
    Event("progress", "PRIVATE-MODEL-TEXT"),
    Event("action", "PRIVATE-MODEL-TEXT", metrics={"run_id": "run", "action": "click"}),
    Event("help", "PRIVATE-MODEL-TEXT", limit=True, metrics={"run_id": "run"}),
  ]

  for event in events:
    trial.write_event(event)

  content = (root / "events.jsonl").read_text()
  assert content.endswith("\n")
  assert "PRIVATE-MODEL-TEXT" not in content
  assert [json.loads(line) for line in content.splitlines()] == [
    {"kind": "progress", "limit": False, "metrics": {}},
    {"kind": "action", "limit": False, "metrics": {"run_id": "run", "action": "click"}},
    {"kind": "help", "limit": True, "metrics": {"run_id": "run"}},
  ]


def test_events_accept_the_engine_metric_vocabulary(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial
  metrics: dict[str, object] = {
    "run_id": "run",
    "step": 0,
    "frame_width": 100,
    "frame_height": 100,
    "frame_bytes": 500,
    "capture_seconds": 0.01,
    "bundle_id": None,
    "outcome": "performed",
    "invalid_cause": None,
    "visible_change": True,
    "stuck": None,
    "images_sent": 1,
    "decision": "act",
    "previous_result": "none",
    "encode_seconds": 0.001,
    "request_seconds": 0.1,
    "input_tokens": 100,
    "cached_input_tokens": 0,
    "output_tokens": 10,
    "cost": 0.0,
    "screenshot_to_decision_seconds": 0.2,
    "action": "click",
    "refusal": None,
    "execution_seconds": 0.01,
    "screenshot_to_action_seconds": 0.25,
  }

  trial.write_event(Event("metrics", "", metrics=metrics))

  assert json.loads((root / "events.jsonl").read_text())["metrics"] == metrics


def test_snapshot_is_archived_before_its_event_and_excluded_from_jsonl(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  root, trial = started_trial
  event = step_event(0, attempts=(("decision", "completed"),), warning="PRIVATE-EXPLANATION")
  assert event.snapshot is not None
  original_replace = os.replace
  publications: list[str] = []

  def observe(source: str | Path, destination: str | Path) -> None:
    assert (root / "events.jsonl").read_bytes() == b""
    publications.append(Path(destination).suffix)
    original_replace(source, destination)

  monkeypatch.setattr(os, "replace", observe)
  trial.write_event(event)

  folder = root / "frames" / "run"
  assert publications == [".png", ".json"]
  assert (folder / "0.png").read_bytes() == event.snapshot.png
  assert json.loads((folder / "0.json").read_text()) == event.snapshot.record
  content = (root / "events.jsonl").read_text()
  assert "PRIVATE-EXPLANATION" not in content
  assert set(json.loads(content)) == {"kind", "limit", "metrics"}


@pytest.mark.parametrize("key", ["message", "headers", "client", "settings", "snapshot"])
def test_unapproved_metric_keys_are_rejected_before_any_writes(
  started_trial: tuple[Path, storage.TrialStorage],
  key: str,
) -> None:
  root, trial = started_trial
  event = step_event(0, attempts=())
  event = replace(event, metrics={**(event.metrics or {}), key: "PRIVATE-DATA"})

  with pytest.raises(BenchmarkError) as caught:
    trial.write_event(event)

  assert "PRIVATE-DATA" not in str(caught.value)
  assert (root / "events.jsonl").read_bytes() == b""
  assert not (root / "frames").exists()


@pytest.mark.parametrize(
  "value",
  [
    object(),
    Settings(),
    b"bytes",
    {"set-member"},
    float("nan"),
    float("inf"),
    float("-inf"),
    {"api_key": "PRIVATE-DATA"},
    ["PRIVATE-DATA"],
    {"nested": [float("nan")]},
  ],
)
def test_non_scalar_or_nonfinite_metrics_are_rejected_before_any_writes(
  started_trial: tuple[Path, storage.TrialStorage],
  value: object,
) -> None:
  root, trial = started_trial
  event = step_event(0, attempts=())
  event = replace(event, metrics={**(event.metrics or {}), "cost": value})

  with pytest.raises(BenchmarkError) as caught:
    trial.write_event(event)

  assert isinstance(caught.value.__cause__, (TypeError, ValueError))
  assert len(str(caught.value)) <= 200
  assert "PRIVATE-DATA" not in str(caught.value)
  assert (root / "events.jsonl").read_bytes() == b""
  assert not (root / "frames").exists()


@pytest.mark.parametrize("claimed", [False, True])
def test_only_the_successfully_started_instance_can_write_events(
  tmp_path: Path, claimed: bool
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  if claimed:
    storage.TrialStorage(root).start(example_run())

  with pytest.raises(BenchmarkError):
    storage.TrialStorage(root).write_event(Event("progress", ""))

  assert not (root / "frames").exists()
  if claimed:
    assert (root / "events.jsonl").read_bytes() == b""
  else:
    assert not (root / "events.jsonl").exists()


@pytest.mark.parametrize("suffix", [".png", ".json"])
def test_archive_failures_do_not_append_a_snapshot_event(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
  suffix: str,
) -> None:
  root, trial = started_trial
  trial.write_event(Event("progress", ""))
  original = (root / "events.jsonl").read_bytes()
  original_replace = os.replace

  def fail(source: str | Path, destination: str | Path) -> None:
    if Path(destination).suffix == suffix:
      raise OSError("injected archive failure")
    original_replace(source, destination)

  monkeypatch.setattr(os, "replace", fail)
  with pytest.raises(BenchmarkError) as caught:
    trial.write_event(step_event(0, attempts=()))

  assert isinstance(caught.value.__cause__, OSError)
  assert (root / "events.jsonl").read_bytes() == original
  assert not (root / "frames" / "run" / "0.json").exists()
  assert (root / "frames" / "run" / "0.png").exists() == (suffix == ".json")
  assert (root / ".started").is_file()


@pytest.mark.parametrize("stage", ["open", "write", "close"])
def test_event_io_failures_preserve_previous_events_and_the_saved_snapshot(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
  stage: str,
) -> None:
  root, trial = started_trial
  trial.write_event(Event("progress", ""))
  original = (root / "events.jsonl").read_bytes()
  original_open = Path.open

  @contextmanager
  def failing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Iterator[Any]:
    inject = path == root / "events.jsonl" and mode == "a"
    if inject and stage == "open":
      raise OSError("injected event open failure")
    with original_open(path, mode, *args, **kwargs) as stream:
      if inject and stage == "write":

        def partial_write(text: str) -> int:
          stream.write(text[:5])
          raise OSError("injected partial event write failure")

        yield SimpleNamespace(write=partial_write)
      else:
        yield stream
    if inject and stage == "close":
      raise OSError("injected event close failure")

  monkeypatch.setattr(Path, "open", failing_open)
  with pytest.raises(BenchmarkError) as caught:
    trial.write_event(step_event(0, attempts=()))
  monkeypatch.setattr(Path, "open", original_open)

  assert isinstance(caught.value.__cause__, OSError)
  assert len(str(caught.value)) <= 200
  assert (root / "events.jsonl").read_bytes().startswith(original)
  assert (root / "frames" / "run" / "0.json").is_file()
  assert (root / ".started").is_file()
  assert not (root / "result.json").exists()


def test_duplicate_snapshot_preserves_original_archive_and_event_log(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial
  event = step_event(0, attempts=())
  assert event.snapshot is not None
  trial.write_event(event)
  original = (root / "events.jsonl").read_bytes()

  with pytest.raises(BenchmarkError):
    trial.write_event(replace(event, snapshot=replace(event.snapshot, png=b"replacement")))

  assert (root / "events.jsonl").read_bytes() == original
  assert (root / "frames" / "run" / "0.png").read_bytes() == event.snapshot.png
