from dataclasses import dataclass


class BenchmarkError(Exception):
  """A benchmark problem that can be reported without a traceback."""


@dataclass(frozen=True)
class TaskSpec:
  task_id: str
  version: int
  app_id: str
  prompt: str
  initial_files: tuple[tuple[str, bytes], ...]
  directories: tuple[str, ...]
  final_files: tuple[tuple[str, bytes], ...]
  absent_after: tuple[str, ...]
  setup: tuple[str, ...]
