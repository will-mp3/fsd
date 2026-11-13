import os
from pathlib import Path

import pytest

from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError, TaskManifest
from fsd.benchmark.fixtures import validate_pristine
from fsd.benchmark.tasks import task_for, task_manifest


def test_prepare_never_overwrites_a_trial(tmp_path: Path) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  task_path = root / "task.json"
  assert task_path.is_file()
  original = task_path.read_bytes()

  with pytest.raises(BenchmarkError, match="already exists"):
    storage.prepare_trial(root, "finder-move")

  assert task_path.read_bytes() == original
  assert (root / "workspace" / "draft.txt").read_bytes() == b"Benchmark fixture.\n"


@pytest.mark.parametrize("task_id", ["textedit-edit-save", "finder-rename", "finder-move"])
def test_prepare_publishes_the_canonical_task_and_pristine_workspace(
  tmp_path: Path,
  task_id: str,
) -> None:
  root = tmp_path / "trial"

  manifest = storage.prepare_trial(root, task_id)

  assert (root / "task.json").is_file()
  saved = TaskManifest.model_validate_json((root / "task.json").read_bytes())
  task = task_for(task_id)
  assert saved == manifest == task_manifest(task)
  validate_pristine(root / "workspace", task)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_prepare_preserves_existing_paths(tmp_path: Path, kind: str) -> None:
  root = tmp_path / "trial"
  if kind == "file":
    root.write_bytes(b"existing evidence")
  else:
    root.mkdir()
    (root / "evidence.txt").write_bytes(b"existing evidence")

  with pytest.raises(BenchmarkError, match="already exists"):
    storage.prepare_trial(root, "finder-rename")

  evidence = root if kind == "file" else root / "evidence.txt"
  assert evidence.read_bytes() == b"existing evidence"


@pytest.mark.parametrize("target_exists", [False, True], ids=("dangling", "existing"))
def test_prepare_rejects_output_symlinks(tmp_path: Path, target_exists: bool) -> None:
  target = tmp_path / "target"
  if target_exists:
    target.mkdir()
  root = tmp_path / "trial"
  root.symlink_to(target, target_is_directory=True)

  with pytest.raises(BenchmarkError, match="symlink"):
    storage.prepare_trial(root, "finder-rename")

  assert root.is_symlink()
  assert target.exists() == target_exists
  if target_exists:
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("parent_is_file", [False, True], ids=("missing", "file"))
def test_prepare_requires_an_existing_parent_directory(
  tmp_path: Path,
  parent_is_file: bool,
) -> None:
  parent = tmp_path / "parent"
  if parent_is_file:
    parent.write_bytes(b"existing evidence")
  root = parent / "trial"

  with pytest.raises(BenchmarkError, match="parent"):
    storage.prepare_trial(root, "finder-rename")

  assert not root.exists()
  if parent_is_file:
    assert parent.read_bytes() == b"existing evidence"
  else:
    assert not parent.exists()


def test_unknown_task_does_not_create_a_trial_directory(tmp_path: Path) -> None:
  root = tmp_path / "trial"

  with pytest.raises(BenchmarkError, match="Unknown benchmark task"):
    storage.prepare_trial(root, "unknown")

  assert not root.exists()


def test_failed_manifest_publication_preserves_the_partial_trial(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  root = tmp_path / "trial"
  original_replace = os.replace

  def fail_manifest(source: str | Path, destination: str | Path) -> None:
    if Path(destination) == root / "task.json":
      raise OSError("injected publication failure")
    original_replace(source, destination)

  monkeypatch.setattr(os, "replace", fail_manifest)

  with pytest.raises(BenchmarkError, match="prepare"):
    storage.prepare_trial(root, "finder-rename")

  assert not (root / "task.json").exists()
  assert (root / "workspace" / "draft.txt").read_bytes() == b"Benchmark fixture.\n"
  assert sorted(path.name for path in root.iterdir()) == ["workspace"]
  with pytest.raises(BenchmarkError, match="already exists"):
    storage.prepare_trial(root, "finder-move")
