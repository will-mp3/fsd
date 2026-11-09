from collections.abc import Iterator
from pathlib import Path

import pytest

from fsd.benchmark import fixtures
from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.tasks import task_for


@pytest.mark.parametrize("task_id", ["textedit-edit-save", "finder-rename", "finder-move"])
def test_fresh_workspace_is_ready_but_goal_is_not_complete(tmp_path: Path, task_id: str) -> None:
  task = task_for(task_id)
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)

  fixtures.validate_pristine(workspace, task)
  assert fixtures.score_workspace(workspace, task).result == "fail"


@pytest.mark.parametrize("change", ["edited", "missing"])
def test_changed_starting_file_is_rejected(tmp_path: Path, change: str) -> None:
  task = task_for("textedit-edit-save")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  original = workspace / "note.txt"
  if change == "edited":
    original.write_bytes(b"Status: ready\nOwner: Alex\n")
  else:
    original.unlink()

  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(workspace, task)


@pytest.mark.parametrize("extra_path", ["extra.txt", "Archive/extra.txt"])
def test_unexpected_entries_are_rejected_without_removal(tmp_path: Path, extra_path: str) -> None:
  task = task_for("finder-move")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  extra = workspace / extra_path
  extra.write_bytes(b"Keep this evidence")

  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(workspace, task)

  assert extra.read_bytes() == b"Keep this evidence"


@pytest.mark.parametrize(
  ("task_id", "destination"),
  [("finder-rename", "final.txt"), ("finder-move", "Archive/report.txt")],
)
def test_preexisting_destination_is_rejected(
  tmp_path: Path, task_id: str, destination: str
) -> None:
  task = task_for(task_id)
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  (workspace / destination).write_bytes(b"Benchmark fixture.\n")

  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(workspace, task)


@pytest.mark.parametrize("kind", ["missing", "file", "symlink"])
def test_required_directory_must_be_a_real_directory(tmp_path: Path, kind: str) -> None:
  task = task_for("finder-move")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  archive = workspace / "Archive"
  archive.rmdir()
  if kind == "file":
    archive.write_bytes(b"Wrong type")
  elif kind == "symlink":
    external = tmp_path / "external"
    external.mkdir()
    archive.symlink_to(external, target_is_directory=True)

  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(workspace, task)


@pytest.mark.parametrize("boundary", ["workspace", "file"])
def test_initial_fixture_cannot_be_redirected_by_symlink(tmp_path: Path, boundary: str) -> None:
  task = task_for("textedit-edit-save")
  real = tmp_path / "real"
  fixtures.create_workspace(real, task)
  if boundary == "workspace":
    workspace = tmp_path / "workspace"
    workspace.symlink_to(real, target_is_directory=True)
  else:
    workspace = real
    original = workspace / "note.txt"
    external = tmp_path / "external.txt"
    original.rename(external)
    original.symlink_to(external)

  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(workspace, task)


def test_finder_metadata_is_ignored_in_fixture_directories(tmp_path: Path) -> None:
  task = task_for("finder-move")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  for directory in (workspace, workspace / "Archive"):
    (directory / ".DS_Store").write_bytes(b"Finder metadata")

  fixtures.validate_pristine(workspace, task)


def test_unreadable_starting_file_prevents_readiness(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  task = task_for("textedit-edit-save")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)

  def deny_open(self: Path, mode: str) -> None:
    raise PermissionError("private diagnostic text")

  monkeypatch.setattr(Path, "open", deny_open)

  with pytest.raises(BenchmarkError, match="Could not inspect") as caught:
    fixtures.validate_pristine(workspace, task)

  assert "private diagnostic text" not in str(caught.value)


def test_unreadable_directory_prevents_readiness(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  task = task_for("finder-move")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)

  def deny_listing(self: Path) -> Iterator[Path]:
    raise PermissionError("Test listing denied")

  monkeypatch.setattr(Path, "iterdir", deny_listing)

  with pytest.raises(BenchmarkError, match="Could not inspect"):
    fixtures.validate_pristine(workspace, task)


def test_missing_workspace_is_not_ready(tmp_path: Path) -> None:
  with pytest.raises(BenchmarkError, match="not pristine"):
    fixtures.validate_pristine(tmp_path / "missing", task_for("textedit-edit-save"))
