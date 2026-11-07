from fsd.benchmark.contracts import BenchmarkError, TaskSpec

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
)


def task_for(task_id: str) -> TaskSpec:
  for task in _TASKS:
    if task.task_id == task_id:
      return task

  supported = ", ".join(task.task_id for task in _TASKS) or "none registered"
  raise BenchmarkError(f"Unknown benchmark task {task_id!r}. Supported tasks: {supported}.")
