import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from typing import IO, Any

import pytest

from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError, RunManifest
from tests.benchmark.helpers import example_run


def test_start_publishes_manifest_and_preserves_prepared_files(tmp_path: Path) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  original_task = (root / "task.json").read_bytes()
  run = example_run()
  trial = storage.TrialStorage(root)

  trial.start(run)

  assert (root / ".started").read_text() == run.trial_id + "\n"
  assert (root / "events.jsonl").read_bytes() == b""
  assert RunManifest.model_validate_json((root / "run.json").read_bytes()) == run
  assert (root / "task.json").read_bytes() == original_task
  assert (root / "workspace" / "draft.txt").read_bytes() == b"Benchmark fixture.\n"
  assert not (root / "result.json").exists()

  original_run = (root / "run.json").read_bytes()
  for contender in (trial, storage.TrialStorage(root)):
    with pytest.raises(BenchmarkError):
      contender.start(example_run(trial_id="fedcba9876543210"))
  assert (root / "run.json").read_bytes() == original_run
  assert (root / ".started").read_text() == run.trial_id + "\n"


@pytest.mark.parametrize("name", [".started", "run.json", "result.json", "events.jsonl", "frames"])
@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling-symlink"])
def test_start_preserves_existing_execution_artifacts(
  tmp_path: Path,
  name: str,
  kind: str,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  existing = root / name
  target = tmp_path / "target"
  if kind == "file":
    existing.write_bytes(b"original evidence")
  elif kind == "directory":
    existing.mkdir()
    (existing / "evidence").write_bytes(b"original evidence")
  else:
    if kind == "symlink":
      target.write_bytes(b"original evidence")
    existing.symlink_to(target)
  original_names = sorted(path.name for path in root.iterdir())

  with pytest.raises(BenchmarkError):
    storage.TrialStorage(root).start(example_run())

  assert sorted(path.name for path in root.iterdir()) == original_names
  if kind == "file":
    assert existing.read_bytes() == b"original evidence"
  elif kind == "directory":
    assert (existing / "evidence").read_bytes() == b"original evidence"
  else:
    assert existing.is_symlink()
    assert existing.readlink() == target
    assert target.exists() == (kind == "symlink")
    if target.exists():
      assert target.read_bytes() == b"original evidence"


@pytest.mark.parametrize("change", ["run-task", "stored-prompt", "stored-schema"])
def test_start_rechecks_task_identity_before_claiming(tmp_path: Path, change: str) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  run = example_run(task_id="finder-move" if change == "run-task" else "finder-rename")
  task_path = root / "task.json"
  if change != "run-task":
    payload = json.loads(task_path.read_bytes())
    payload["prompt" if change == "stored-prompt" else "schema_version"] = (
      "Changed instructions" if change == "stored-prompt" else 2
    )
    task_path.write_text(json.dumps(payload))
  original = task_path.read_bytes()

  with pytest.raises(BenchmarkError):
    storage.TrialStorage(root).start(run)

  assert sorted(path.name for path in root.iterdir()) == ["task.json", "workspace"]
  assert task_path.read_bytes() == original


def test_concurrent_starts_have_exactly_one_winner(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  original_open = Path.open
  contenders_ready = Barrier(2, timeout=5)

  def synchronized_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
    if path == root / ".started" and mode == "x":
      # Both starters must pass preflight before either can claim the trial.
      contenders_ready.wait()
    return original_open(path, mode, *args, **kwargs)

  monkeypatch.setattr(Path, "open", synchronized_open)

  def start(run: RunManifest) -> str | None:
    try:
      storage.TrialStorage(root).start(run)
    except BenchmarkError:
      return None
    return run.trial_id

  runs = [example_run(), example_run(trial_id="fedcba9876543210")]
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(start, runs))

  winners = [result for result in results if result is not None]
  assert len(winners) == 1
  assert (root / ".started").read_text() == winners[0] + "\n"
  saved = RunManifest.model_validate_json((root / "run.json").read_bytes())
  assert saved == next(run for run in runs if run.trial_id == winners[0])


def test_manifest_publication_failure_preserves_claim_and_prevents_retry(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  original_replace = os.replace

  def fail_manifest(source: str | Path, destination: str | Path) -> None:
    if Path(destination) == root / "run.json":
      raise OSError("injected publication failure")
    original_replace(source, destination)

  monkeypatch.setattr(os, "replace", fail_manifest)
  trial = storage.TrialStorage(root)
  with pytest.raises(BenchmarkError) as caught:
    trial.start(example_run())

  assert isinstance(caught.value.__cause__, OSError)
  assert len(str(caught.value)) <= 200
  assert (root / ".started").read_text() == example_run().trial_id + "\n"
  assert (root / "events.jsonl").read_bytes() == b""
  assert not (root / "run.json").exists()
  monkeypatch.setattr(os, "replace", original_replace)
  for contender in (trial, storage.TrialStorage(root)):
    with pytest.raises(BenchmarkError):
      contender.start(example_run())
  assert not (root / "run.json").exists()


@pytest.mark.parametrize("name", [".started", "events.jsonl"])
@pytest.mark.parametrize("stage", ["open", "close"])
def test_start_file_failures_are_bounded_and_preserve_partial_evidence(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  name: str,
  stage: str,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  original_open = Path.open

  @contextmanager
  def failing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Iterator[IO[Any]]:
    inject = path == root / name and mode == "x"
    if inject and stage == "open":
      raise OSError("injected open failure")
    with original_open(path, mode, *args, **kwargs) as stream:
      yield stream
    if inject and stage == "close":
      raise OSError("injected close failure")

  monkeypatch.setattr(Path, "open", failing_open)
  with pytest.raises(BenchmarkError) as caught:
    storage.TrialStorage(root).start(example_run())
  monkeypatch.setattr(Path, "open", original_open)

  assert isinstance(caught.value.__cause__, OSError)
  assert len(str(caught.value)) <= 200
  claimed = name != ".started" or stage == "close"
  assert (root / ".started").exists() == claimed
  assert (root / "events.jsonl").exists() == (name == "events.jsonl" and stage == "close")
  assert not (root / "run.json").exists()
  if claimed:
    with pytest.raises(BenchmarkError):
      storage.TrialStorage(root).start(example_run())
