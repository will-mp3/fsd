import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any

import pytest

from fsd import archive
from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError, FrameGeometry, RunManifest, TrialResult
from fsd.operator.contracts import Event
from fsd.platform.base import Rect
from tests.benchmark.helpers import example_result, example_run

GEOMETRY = FrameGeometry(width=200, height=100, screen_rect=Rect(0.0, 0.0, 100.0, 50.0))


def test_geometry_publication_preserves_all_other_run_fields(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial
  original = RunManifest.model_validate_json((root / "run.json").read_bytes())

  trial.set_geometry(GEOMETRY)

  saved = RunManifest.model_validate_json((root / "run.json").read_bytes())
  assert saved.geometry == GEOMETRY
  assert saved.model_dump(exclude={"geometry"}) == original.model_dump(exclude={"geometry"})
  assert (root / ".started").read_text() == original.trial_id + "\n"


@pytest.mark.parametrize("same_geometry", [False, True])
def test_geometry_cannot_be_published_twice(
  started_trial: tuple[Path, storage.TrialStorage],
  same_geometry: bool,
) -> None:
  root, trial = started_trial
  trial.set_geometry(GEOMETRY)
  original = (root / "run.json").read_bytes()
  second = GEOMETRY if same_geometry else GEOMETRY.model_copy(update={"width": 400})

  with pytest.raises(BenchmarkError):
    trial.set_geometry(second)

  assert (root / "run.json").read_bytes() == original


@pytest.mark.parametrize("operation", ["geometry", "finish"])
@pytest.mark.parametrize("claimed", [False, True])
def test_only_the_started_instance_can_publish_geometry_or_result(
  tmp_path: Path,
  operation: str,
  claimed: bool,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  if claimed:
    storage.TrialStorage(root).start(example_run())
  original_names = sorted(path.name for path in root.iterdir())

  with pytest.raises(BenchmarkError):
    trial = storage.TrialStorage(root)
    if operation == "geometry":
      trial.set_geometry(GEOMETRY)
    else:
      trial.finish(example_result())

  assert sorted(path.name for path in root.iterdir()) == original_names
  assert not (root / "result.json").exists()


def test_finish_publishes_result_and_closes_all_further_writes(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial
  trial.set_geometry(GEOMETRY)
  trial.write_event(Event("done", "", metrics={"run_id": "run"}))
  result = example_result()

  trial.finish(result)

  assert TrialResult.model_validate_json((root / "result.json").read_bytes()) == result
  original = {
    name: (root / name).read_bytes()
    for name in (".started", "task.json", "run.json", "events.jsonl", "result.json")
  }
  operations: tuple[Callable[[], None], ...] = (
    lambda: trial.start(example_run()),
    lambda: trial.write_event(Event("progress", "")),
    lambda: trial.set_geometry(GEOMETRY),
    lambda: trial.finish(result),
  )
  for operation in operations:
    with pytest.raises(BenchmarkError):
      operation()
  assert {name: (root / name).read_bytes() for name in original} == original


def test_finish_rejects_a_result_for_another_trial(
  started_trial: tuple[Path, storage.TrialStorage],
) -> None:
  root, trial = started_trial

  with pytest.raises(BenchmarkError):
    trial.finish(example_result(trial_id="fedcba9876543210"))

  assert not (root / "result.json").exists()
  trial.finish(example_result())
  assert TrialResult.model_validate_json((root / "result.json").read_bytes()) == example_result()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling-symlink"])
def test_finish_preserves_an_existing_result_path(
  started_trial: tuple[Path, storage.TrialStorage],
  kind: str,
) -> None:
  root, trial = started_trial
  result_path = root / "result.json"
  target = root.parent / "existing-result"
  if kind == "file":
    result_path.write_bytes(b"previous result")
  elif kind == "directory":
    result_path.mkdir()
    (result_path / "evidence").write_bytes(b"previous result")
  else:
    if kind == "symlink":
      target.write_bytes(b"previous result")
    result_path.symlink_to(target)

  with pytest.raises(BenchmarkError):
    trial.finish(example_result())

  if kind == "file":
    assert result_path.read_bytes() == b"previous result"
  elif kind == "directory":
    assert (result_path / "evidence").read_bytes() == b"previous result"
  else:
    assert result_path.is_symlink()
    assert result_path.readlink() == target
    assert target.exists() == (kind == "symlink")
    if target.exists():
      assert target.read_bytes() == b"previous result"


@pytest.mark.parametrize("operation", ["geometry", "finish"])
def test_failed_atomic_publication_preserves_evidence_and_does_not_advance_state(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
  operation: str,
) -> None:
  root, trial = started_trial
  original_run = (root / "run.json").read_bytes()
  target = root / ("run.json" if operation == "geometry" else "result.json")
  original_replace = os.replace

  def fail(source: str | Path, destination: str | Path) -> None:
    if Path(destination) == target:
      raise OSError("injected publication failure")
    original_replace(source, destination)

  with monkeypatch.context() as patch:
    patch.setattr(os, "replace", fail)
    with pytest.raises(BenchmarkError) as caught:
      if operation == "geometry":
        trial.set_geometry(GEOMETRY)
      else:
        trial.finish(example_result())

  assert isinstance(caught.value.__cause__, OSError)
  assert len(str(caught.value)) <= 200
  assert (root / "run.json").read_bytes() == original_run
  assert not (root / "result.json").exists()
  assert (root / ".started").is_file()
  if operation == "geometry":
    trial.set_geometry(GEOMETRY)
    assert RunManifest.model_validate_json((root / "run.json").read_bytes()).geometry == GEOMETRY
  error_result = example_result().model_copy(
    update={"infrastructure": "error", "error_category": "recording"}
  )
  trial.finish(error_result)
  saved = TrialResult.model_validate_json((root / "result.json").read_bytes())
  assert saved == error_result
  assert saved.unassisted_success is False


@pytest.mark.parametrize("stage", ["write", "close"])
def test_failed_final_file_write_or_close_never_publishes_a_result(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
  stage: str,
) -> None:
  root, trial = started_trial

  @contextmanager
  def failing_file(**kwargs: Any) -> Iterator[Any]:
    with NamedTemporaryFile(**kwargs) as stream:

      def write(data: bytes) -> int:
        if stage == "write":
          stream.write(data[:5])
          raise OSError("injected partial result write failure")
        return stream.write(data)

      yield SimpleNamespace(name=stream.name, write=write)
      if stage == "close":
        raise OSError("injected result close failure")

  with monkeypatch.context() as patch:
    patch.setattr(archive, "NamedTemporaryFile", failing_file)
    with pytest.raises(BenchmarkError) as caught:
      trial.finish(example_result())

  assert isinstance(caught.value.__cause__, OSError)
  assert not (root / "result.json").exists()
  assert not list(root.glob(".result.json.*.tmp"))
  assert (root / ".started").is_file()


@pytest.mark.parametrize("operation", ["geometry", "finish"])
def test_record_encoding_failures_are_reported_without_publishing(
  started_trial: tuple[Path, storage.TrialStorage],
  monkeypatch: pytest.MonkeyPatch,
  operation: str,
) -> None:
  root, trial = started_trial
  original_run = (root / "run.json").read_bytes()

  def fail_encoding(self: object, *args: Any, **kwargs: Any) -> str:
    raise ValueError("injected encoding failure")

  model = RunManifest if operation == "geometry" else TrialResult
  monkeypatch.setattr(model, "model_dump_json", fail_encoding)

  with pytest.raises(BenchmarkError) as caught:
    if operation == "geometry":
      trial.set_geometry(GEOMETRY)
    else:
      trial.finish(example_result())

  assert isinstance(caught.value.__cause__, ValueError)
  assert (root / "run.json").read_bytes() == original_run
  assert not (root / "result.json").exists()
