from pathlib import Path

from fsd.benchmark.contracts import BenchmarkError, TaskSpec


def _fixture_path(relative: str) -> Path:
  parts = relative.split("/")
  if any(part in {"", ".", ".."} for part in parts) or "\\" in relative or ":" in relative:
    raise BenchmarkError("Fixture paths must be relative, with no empty or traversal components.")
  return Path(*parts)


def create_workspace(workspace: Path, task: TaskSpec) -> None:
  directories = tuple(_fixture_path(name) for name in task.directories)
  files = tuple((_fixture_path(name), content) for name, content in task.initial_files)

  try:
    workspace.mkdir(exist_ok=False)
  except FileExistsError as exc:
    raise BenchmarkError(
      "The benchmark workspace already exists. Choose a fresh trial directory."
    ) from exc
  except OSError as exc:
    raise BenchmarkError("Could not create the benchmark workspace.") from exc

  try:
    for directory in directories:
      (workspace / directory).mkdir(exist_ok=False)

    for relative, content in files:
      with (workspace / relative).open("xb") as stream:
        stream.write(content)
  except OSError as exc:
    raise BenchmarkError(
      "Could not prepare fixture files; the partial workspace was preserved."
    ) from exc
