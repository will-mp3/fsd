from dataclasses import replace
from pathlib import Path

import pytest

from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.fixtures import create_workspace
from fsd.benchmark.tasks import task_for


@pytest.mark.parametrize(
  ("task_id", "files", "directories"),
  [
    ("textedit-edit-save", {"note.txt": b"Status: draft\nOwner: Alex\n"}, ()),
    ("finder-rename", {"draft.txt": b"Benchmark fixture.\n"}, ()),
    ("finder-move", {"report.txt": b"Benchmark fixture.\n"}, ("Archive",)),
  ],
  ids=("textedit", "rename", "move"),
)
def test_create_workspace_matches_initial_fixture(
  tmp_path: Path, task_id: str, files: dict[str, bytes], directories: tuple[str, ...]
) -> None:
  workspace = tmp_path / "workspace"

  create_workspace(workspace, task_for(task_id))

  for name, content in files.items():
    assert (workspace / name).read_bytes() == content
  for name in directories:
    assert (workspace / name).is_dir()
  assert {path.relative_to(workspace).as_posix() for path in workspace.rglob("*")} == (
    set(files) | set(directories)
  )


def test_existing_workspace_is_preserved(tmp_path: Path) -> None:
  workspace = tmp_path / "workspace"
  workspace.mkdir()
  original = workspace / "note.txt"
  original.write_bytes(b"Existing trial evidence\n")

  with pytest.raises(BenchmarkError, match="already exists"):
    create_workspace(workspace, task_for("textedit-edit-save"))

  assert original.read_bytes() == b"Existing trial evidence\n"
  assert list(workspace.iterdir()) == [original]


@pytest.mark.parametrize("entry", ["file", "directory"])
@pytest.mark.parametrize("relative", ["../outside.txt", "/outside.txt", "", "folder//file"])
def test_invalid_fixture_paths_are_rejected_before_creation(
  tmp_path: Path, entry: str, relative: str
) -> None:
  task = task_for("textedit-edit-save")
  if entry == "file":
    task = replace(task, initial_files=((relative, b"data"),))
  else:
    task = replace(task, directories=(relative,))
  workspace = tmp_path / "workspace"

  with pytest.raises(BenchmarkError, match="relative"):
    create_workspace(workspace, task)

  assert not workspace.exists()
  assert not (tmp_path / "outside.txt").exists()


def test_write_failure_preserves_partial_workspace(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  workspace = tmp_path / "workspace"

  def deny_open(self: Path, mode: str) -> None:
    raise PermissionError("Test write denied")

  monkeypatch.setattr(Path, "open", deny_open)

  with pytest.raises(BenchmarkError, match="partial workspace"):
    create_workspace(workspace, task_for("finder-rename"))

  assert workspace.is_dir()
