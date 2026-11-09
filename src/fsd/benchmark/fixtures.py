import stat
from pathlib import Path

from fsd.benchmark.contracts import BenchmarkError, GoalScore, TaskSpec


class ArtifactMismatch(Exception):
  """An artifact does not satisfy the task's required filesystem structure."""


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


def _require_directory(path: Path) -> None:
  try:
    info = path.lstat()
  except FileNotFoundError as exc:
    raise ArtifactMismatch("A required fixture directory is missing.") from exc

  if not stat.S_ISDIR(info.st_mode):
    raise ArtifactMismatch("Expected a real fixture directory")


def _checked_target(workspace: Path, relative: str) -> Path:
  path = _fixture_path(relative)
  parent = workspace
  _require_directory(parent)

  for component in path.parts[:-1]:
    parent = parent / component
    _require_directory(parent)

  return parent / path.name


def read_regular(workspace: Path, relative: str, expected_size: int) -> bytes | None:
  if expected_size < 0:
    raise ValueError("Expected size must be nonnegative.")

  target = _checked_target(workspace, relative)
  try:
    info = target.lstat()
  except FileNotFoundError:
    return None

  if not stat.S_ISREG(info.st_mode):
    raise ArtifactMismatch("Expected a regular fixture file.")

  with target.open("rb") as stream:
    return stream.read(expected_size + 1)


def is_absent(workspace: Path, relative: str) -> bool:
  target = _checked_target(workspace, relative)
  try:
    target.lstat()
  except FileNotFoundError:
    return True
  return False


def score_workspace(workspace: Path, task: TaskSpec) -> GoalScore:
  try:
    for name, expected in task.final_files:
      if read_regular(workspace, name, len(expected)) != expected:
        return GoalScore(
          result="fail",
          evidence=f"Unexpected contents: {name}",
        )

    for name in task.absent_after:
      if not is_absent(workspace, name):
        return GoalScore(
          result="fail",
          evidence=f"Original path remains: {name}",
        )

  except ArtifactMismatch as exc:
    return GoalScore(result="fail", evidence=str(exc))
  except OSError:
    return GoalScore(
      result="error",
      evidence="Could not read the task artifacts.",
    )

  return GoalScore(
    result="pass",
    evidence="All required artifact conditions hold.",
  )


def validate_pristine(workspace: Path, task: TaskSpec) -> None:
  initial_paths = {_fixture_path(name) for name, _ in task.initial_files}
  directory_paths = tuple(_fixture_path(name) for name in task.directories)

  try:
    _require_directory(workspace)

    for name, expected in task.initial_files:
      if read_regular(workspace, name, len(expected)) != expected:
        raise ArtifactMismatch(f"Starting contents differ: {name}")

    for name in task.directories:
      _require_directory(_checked_target(workspace, name))

    for name, _ in task.final_files:
      if _fixture_path(name) not in initial_paths and not is_absent(workspace, name):
        raise ArtifactMismatch(f"Destination already exists: {name}")

    allowed = initial_paths | set(directory_paths)
    scan_directories = [workspace]
    scan_directories.extend(workspace / path for path in directory_paths)

    for directory in scan_directories:
      for entry in directory.iterdir():
        if entry.name == ".DS_Store":
          continue

        relative = entry.relative_to(workspace)
        if relative not in allowed:
          raise ArtifactMismatch(f"Unexpected workspace entry: {relative.as_posix()}")

  except ArtifactMismatch as exc:
    raise BenchmarkError(f"Workspace is not pristine: {exc}") from exc
  except OSError as exc:
    raise BenchmarkError("Could not inspect the starting workspace.") from exc
