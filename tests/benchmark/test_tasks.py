import pytest

from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.tasks import task_for


def test_textedit_fixture_and_prompt_are_versioned() -> None:
  task = task_for("textedit-edit-save")

  assert task.version == 1
  assert task.app_id == "com.apple.TextEdit"
  assert task.initial_files == (("note.txt", b"Status: draft\nOwner: Alex\n"),)
  assert task.prompt == (
    "In the open TextEdit document, change 'Status: draft' to 'Status: ready'. "
    "Preserve all other text and save the document."
  )
  assert task.final_files == (("note.txt", b"Status: ready\nOwner: Alex\n"),)


@pytest.mark.parametrize(
  ("task_id", "initial_path", "final_path", "directories", "prompt"),
  [
    (
      "finder-rename",
      "draft.txt",
      "final.txt",
      (),
      "In the current Finder folder, rename draft.txt to final.txt. "
      "Keep the file contents unchanged.",
    ),
    (
      "finder-move",
      "report.txt",
      "Archive/report.txt",
      ("Archive",),
      "Move report.txt into the Archive folder in the current Finder folder. "
      "Keep the file name and contents unchanged.",
    ),
  ],
  ids=("rename", "move"),
)
def test_finder_tasks_preserve_contents_and_require_original_path_absent(
  task_id: str,
  initial_path: str,
  final_path: str,
  directories: tuple[str, ...],
  prompt: str,
) -> None:
  task = task_for(task_id)

  assert task.task_id == task_id
  assert task.version == 1
  assert task.app_id == "com.apple.finder"
  assert task.prompt == prompt
  assert task.initial_files == ((initial_path, b"Benchmark fixture.\n"),)
  assert task.directories == directories
  assert task.final_files == ((final_path, b"Benchmark fixture.\n"),)
  assert task.absent_after == (initial_path,)


def test_unknown_task_lists_supported_ids() -> None:
  with pytest.raises(BenchmarkError) as caught:
    task_for("not-a-task")

  message = str(caught.value)
  assert "not-a-task" in message
  assert "Supported tasks:" in message
  for task_id in ("textedit-edit-save", "finder-rename", "finder-move"):
    assert task_id in message
