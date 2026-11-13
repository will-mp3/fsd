from pathlib import Path

from fsd.archive import atomic_write
from fsd.benchmark.contracts import BenchmarkError, TaskManifest, TaskSpec
from fsd.benchmark.fixtures import ArtifactMismatch, create_workspace, read_regular
from fsd.benchmark.tasks import task_for, task_manifest

MAX_JSON_BYTES = 1024 * 1024


def prepare_trial(root: Path, task_id: str) -> TaskManifest:
  task = task_for(task_id)
  manifest = task_manifest(task)
  content = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"

  try:
    if root.is_symlink():
      raise BenchmarkError("The trial path must not be a symlink.")
    if not root.parent.is_dir():
      raise BenchmarkError("The trial parent directory must already exist.")
    root.mkdir()
  except FileExistsError as exc:
    raise BenchmarkError(
      "The benchmark trial already exists. Choose a fresh trial directory."
    ) from exc
  except OSError as exc:
    raise BenchmarkError("Could not create the benchmark trial directory.") from exc

  try:
    create_workspace(root / "workspace", task)
    atomic_write(root / "task.json", content)
  except OSError as exc:
    raise BenchmarkError("Could not prepare trial files; the partial trial was preserved.") from exc

  return manifest


def load_task(root: Path) -> tuple[TaskManifest, TaskSpec]:
  try:
    content = read_regular(root, "task.json", MAX_JSON_BYTES)
  except (ArtifactMismatch, OSError) as exc:
    raise BenchmarkError("Could not read the prepared task manifest.") from exc

  if content is None:
    raise BenchmarkError("The trial has no prepared task manifest.")
  if len(content) > MAX_JSON_BYTES:
    raise BenchmarkError("The prepared task manifest exceeds the 1 MiB limit.")

  try:
    manifest = TaskManifest.model_validate_json(content)
  except ValueError as exc:
    raise BenchmarkError("Invalid or unsupported prepared task manifest.") from exc

  try:
    task = task_for(manifest.task_id)
  except BenchmarkError as exc:
    raise BenchmarkError("The prepared task refers to an unsupported benchmark task.") from exc

  if manifest != task_manifest(task):
    raise BenchmarkError("The prepared task does not match the built-in benchmark definition.")

  return manifest, task
