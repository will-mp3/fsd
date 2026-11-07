from fsd.benchmark.contracts import BenchmarkError, TaskSpec

_FINDER_CONTENTS = b"Benchmark fixture.\n"

_FINDER_SETUP = (
  "Open workspace/ in Finder using list view with file extensions visible.",
  "Keep the Finder window unobscured on the main display.",
  "Close unrelated task windows and dialogs; no file selection is required.",
  "Return focus to Finder during the countdown.",
)

_TASKS: tuple[TaskSpec, ...] = (
  TaskSpec(
    task_id="textedit-edit-save",
    version=1,
    app_id="com.apple.TextEdit",
    prompt=(
      "In the open TextEdit document, change 'Status: draft' to 'Status: ready'. "
      "Preserve all other text and save the document."
    ),
    initial_files=(("note.txt", b"Status: draft\nOwner: Alex\n"),),
    directories=(),
    final_files=(("note.txt", b"Status: ready\nOwner: Alex\n"),),
    absent_after=(),
    setup=(
      "Open workspace/note.txt in TextEdit as plain text.",
      "Keep the document unobscured on the main display.",
      "Close unrelated task windows and dialogs; no text selection is required.",
      "Return focus to TextEdit during the countdown.",
    ),
  ),
  TaskSpec(
    task_id="finder-rename",
    version=1,
    app_id="com.apple.finder",
    prompt=(
      "In the current Finder folder, rename draft.txt to final.txt. "
      "Keep the file contents unchanged."
    ),
    initial_files=(("draft.txt", _FINDER_CONTENTS),),
    directories=(),
    final_files=(("final.txt", _FINDER_CONTENTS),),
    absent_after=("draft.txt",),
    setup=_FINDER_SETUP,
  ),
  TaskSpec(
    task_id="finder-move",
    version=1,
    app_id="com.apple.finder",
    prompt=(
      "Move report.txt into the Archive folder in the current Finder folder. "
      "Keep the file name and contents unchanged."
    ),
    initial_files=(("report.txt", _FINDER_CONTENTS),),
    directories=("Archive",),
    final_files=(("Archive/report.txt", _FINDER_CONTENTS),),
    absent_after=("report.txt",),
    setup=_FINDER_SETUP,
  ),
)


def task_for(task_id: str) -> TaskSpec:
  for task in _TASKS:
    if task.task_id == task_id:
      return task

  supported = ", ".join(task.task_id for task in _TASKS) or "none registered"
  raise BenchmarkError(f"Unknown benchmark task {task_id!r}. Supported tasks: {supported}.")
