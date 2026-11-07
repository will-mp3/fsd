from fsd.benchmark.contracts import BenchmarkError, TaskSpec

_TASKS: tuple[TaskSpec, ...] = ()


def task_for(task_id: str) -> TaskSpec:
  for task in _TASKS:
    if task.task_id == task_id:
      return task

  supported = ", ".join(task.task_id for task in _TASKS) or "none registered"
  raise BenchmarkError(f"Unknown benchmark task {task_id!r}. Supported tasks: {supported}.")
