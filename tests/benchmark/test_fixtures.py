from dataclasses import replace
from pathlib import Path

import pytest

from fsd.benchmark import fixtures
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


@pytest.mark.parametrize("content", [b"", b"saved text\n"], ids=("empty", "text"))
def test_read_regular_returns_exact_bytes(tmp_path: Path, content: bytes) -> None:
  (tmp_path / "note.txt").write_bytes(content)

  assert fixtures.read_regular(tmp_path, "note.txt", len(content)) == content


def test_read_regular_returns_none_for_missing_file(tmp_path: Path) -> None:
  assert fixtures.read_regular(tmp_path, "missing.txt", 10) is None


def test_read_regular_caps_output_at_expected_size_plus_one(tmp_path: Path) -> None:
  (tmp_path / "note.txt").write_bytes(b"x" * 100_000)

  assert fixtures.read_regular(tmp_path, "note.txt", 8) == b"x" * 9


def test_read_regular_rejects_negative_read_limit(tmp_path: Path) -> None:
  (tmp_path / "note.txt").write_bytes(b"contents")

  with pytest.raises(ValueError, match="nonnegative"):
    fixtures.read_regular(tmp_path, "note.txt", -1)


@pytest.mark.parametrize("boundary", ["workspace", "parent", "file", "dangling-file"])
def test_read_regular_rejects_symlinks(tmp_path: Path, boundary: str) -> None:
  external = tmp_path / "external"
  external.mkdir()
  (external / "note.txt").write_bytes(b"Outside the trial")
  workspace = tmp_path / "workspace"
  relative = "note.txt"
  if boundary == "workspace":
    workspace.symlink_to(external, target_is_directory=True)
  else:
    workspace.mkdir()
    if boundary == "parent":
      (workspace / "nested").symlink_to(external, target_is_directory=True)
      relative = "nested/note.txt"
    else:
      target = external / ("note.txt" if boundary == "file" else "missing.txt")
      (workspace / "note.txt").symlink_to(target)

  with pytest.raises(fixtures.ArtifactMismatch):
    fixtures.read_regular(workspace, relative, 100)


def test_read_regular_rejects_directory_instead_of_file(tmp_path: Path) -> None:
  (tmp_path / "note.txt").mkdir()

  with pytest.raises(fixtures.ArtifactMismatch):
    fixtures.read_regular(tmp_path, "note.txt", 10)


@pytest.mark.parametrize("missing", ["workspace", "parent"])
def test_missing_directory_is_a_mismatch_not_a_missing_file(tmp_path: Path, missing: str) -> None:
  workspace = tmp_path / "workspace" if missing == "workspace" else tmp_path

  with pytest.raises(fixtures.ArtifactMismatch):
    fixtures.read_regular(workspace, "nested/note.txt", 10)
  with pytest.raises(fixtures.ArtifactMismatch):
    fixtures.is_absent(workspace, "nested/note.txt")


def test_is_absent_accepts_only_a_missing_entry(tmp_path: Path) -> None:
  assert fixtures.is_absent(tmp_path, "missing.txt") is True


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling-symlink"])
def test_is_absent_rejects_existing_entries(tmp_path: Path, kind: str) -> None:
  target = tmp_path / "note.txt"
  if kind == "file":
    target.write_bytes(b"data")
  elif kind == "directory":
    target.mkdir()
  else:
    destination = tmp_path / "destination.txt"
    if kind == "symlink":
      destination.write_bytes(b"data")
    target.symlink_to(destination)

  assert fixtures.is_absent(tmp_path, "note.txt") is False


def test_read_regular_preserves_permission_errors(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  (tmp_path / "note.txt").write_bytes(b"data")

  def deny_open(self: Path, mode: str) -> None:
    raise PermissionError("Test read denied")

  monkeypatch.setattr(Path, "open", deny_open)

  with pytest.raises(PermissionError):
    fixtures.read_regular(tmp_path, "note.txt", 4)
