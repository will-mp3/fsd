from pathlib import Path

import pytest

from fsd.benchmark import fixtures
from fsd.benchmark.tasks import task_for


@pytest.mark.parametrize(
  ("task_id", "source", "destination", "contents"),
  [
    ("textedit-edit-save", "note.txt", "note.txt", b"Status: ready\nOwner: Alex\n"),
    ("finder-rename", "draft.txt", "final.txt", b"Benchmark fixture.\n"),
    ("finder-move", "report.txt", "Archive/report.txt", b"Benchmark fixture.\n"),
  ],
  ids=("textedit", "rename", "move"),
)
def test_correct_artifacts_pass(
  tmp_path: Path, task_id: str, source: str, destination: str, contents: bytes
) -> None:
  task = task_for(task_id)
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  if source != destination:
    (workspace / source).rename(workspace / destination)
  (workspace / destination).write_bytes(contents)

  score = fixtures.score_workspace(workspace, task)

  assert score.result == "pass"
  assert score.evidence
  assert (workspace / destination).read_bytes() == contents


def test_rename_requires_both_name_and_unchanged_contents(tmp_path: Path) -> None:
  task = task_for("finder-rename")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  (workspace / "draft.txt").rename(workspace / "final.txt")

  assert fixtures.score_workspace(workspace, task).result == "pass"

  (workspace / "final.txt").write_bytes(b"Changed contents\n")

  assert fixtures.score_workspace(workspace, task).result == "fail"


@pytest.mark.parametrize(
  "contents",
  [
    b"Status: draft\nOwner: Alex\n",
    b"Status: Ready\nOwner: Alex\n",
    b"Status: ready\nOwner: Alex",
    b"Status: ready\nOwner: Sam\n",
    b"Status: ready\nOwner: Alex\n" + b"x" * 100_000,
  ],
  ids=("unsaved", "wrong-case", "missing-newline", "changed-other-text", "extra-bytes"),
)
def test_textedit_requires_exact_saved_contents(tmp_path: Path, contents: bytes) -> None:
  task = task_for("textedit-edit-save")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  (workspace / "note.txt").write_bytes(contents)

  score = fixtures.score_workspace(workspace, task)

  assert score.result == "fail"
  assert (workspace / "note.txt").read_bytes() == contents


def test_copy_is_not_a_successful_move(tmp_path: Path) -> None:
  task = task_for("finder-move")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)
  (workspace / "Archive" / "report.txt").write_bytes(b"Benchmark fixture.\n")

  score = fixtures.score_workspace(workspace, task)

  assert score.result == "fail"
  assert "report.txt" in score.evidence


def test_wrong_artifact_type_is_failure_not_scoring_error(tmp_path: Path) -> None:
  workspace = tmp_path / "workspace"
  workspace.mkdir()
  (workspace / "note.txt").mkdir()

  score = fixtures.score_workspace(workspace, task_for("textedit-edit-save"))

  assert score.result == "fail"


def test_missing_file_is_failure_not_scoring_error(tmp_path: Path) -> None:
  score = fixtures.score_workspace(tmp_path, task_for("textedit-edit-save"))

  assert score.result == "fail"


def test_unreadable_file_is_scoring_error_without_raw_exception(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  task = task_for("textedit-edit-save")
  workspace = tmp_path / "workspace"
  fixtures.create_workspace(workspace, task)

  def deny_open(self: Path, mode: str) -> None:
    raise PermissionError("private diagnostic text")

  monkeypatch.setattr(Path, "open", deny_open)

  score = fixtures.score_workspace(workspace, task)

  assert score.result == "error"
  assert score.evidence
  assert "private diagnostic text" not in score.evidence
